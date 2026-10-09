"""OpenDART disclosure importer: verified origin != manually verified positive economic impact."""
from __future__ import annotations
import os
from datetime import timedelta
import pandas as pd
import requests
from .settings import parse_asof
from .data import EVENT_FIELDS
from .engine import RISK_TERMS


def collect_disclosures(universe_file, out_events_file, asof, key=None, session=None) -> dict:
    api_key=key or os.getenv("DART_API_KEY", "")
    if not api_key:raise RuntimeError("DART_API_KEY not set; events remain missing, not zero impact")
    now=parse_asof(asof)
    end=now.date(); start=end-timedelta(days=7)
    u=pd.read_csv(universe_file,dtype={"code":"string","dart_corp_code":"string"},keep_default_na=False)
    if "dart_corp_code" not in u:raise ValueError("universe.csv requires dart_corp_code for DART")
    s=session or requests.Session()
    items=[]; errors=[]
    for _,row in u.iterrows():
        code=str(row["code"]).zfill(6); corp=str(row.get("dart_corp_code", ""))
        if not corp: continue
        try:
            res=s.get("https://opendart.fss.or.kr/api/list.json",params={"crtfc_key":api_key,
                "corp_code":corp,"bgn_de":start.strftime("%Y%m%d"),"end_de":end.strftime("%Y%m%d"),"page_count":"100"},timeout=14)
            res.raise_for_status(); obj=res.json()
            if obj.get("status")=="013": continue  # no disclosures
            if obj.get("status")!="000":raise ValueError("OpenDART status="+str(obj.get("status")))
            for e in obj.get("list",[]):
                title=str(e.get("report_nm", "")); rd=str(e.get("rcept_dt", "")); rn=str(e.get("rcept_no", ""))
                if len(rd)!=8 or not rn:continue
                # DART list API may not expose exact publication time: assume 23:59 KST to avoid any earlier-time lookahead.
                pub=f"{rd[:4]}-{rd[4:6]}-{rd[6:8]}T23:59:59+09:00"
                typ="risk" if any(term in title for term in RISK_TERMS) else ("contract" if "단일판매" in title else ("earnings" if "잠정" in title and "실적" in title else "other"))
                items.append({"code":code,"published_at":pub,"event_type":typ,"title":title,
                    "source_url":f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rn}","verified":"true",
                    "materiality":0}) # must be assessed manually: title alone is insufficient
        except (requests.RequestException,ValueError) as exc:
            errors.append({"code":code,"cause":str(exc)[:110]})
    target=out_events_file
    if items:
        if os.path.exists(target):
            previous=pd.read_csv(target,dtype={"code":"string"},keep_default_na=False)
            # Preserve prior manually assessed materiality if same disclosure URL.
            old=previous.set_index(["code","source_url"])
            for it in items:
                key=(it["code"],it["source_url"])
                if key in old.index:
                    try: it["materiality"]=old.loc[key]["materiality"]
                    except Exception:pass
            merged=pd.concat([previous,pd.DataFrame(items)],ignore_index=True)
            merged=merged.drop_duplicates(subset=["code","source_url"],keep="last")
        else:merged=pd.DataFrame(items)
        merged.to_csv(target,index=False,columns=EVENT_FIELDS,encoding="utf-8-sig")
    return {"retrieved":len(items),"errors":errors,"materiality_default":"0 (not auto-classified)","note":"DART list date has no exact publication time; conservatively tagged 23:59 KST"}
