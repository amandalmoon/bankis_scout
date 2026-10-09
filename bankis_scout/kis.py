"""KIS official read-only HTTP adapter. Absolutely no trading/order endpoints."""
from __future__ import annotations
import json
import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import requests
import pandas as pd
from .settings import parse_asof, last_allowed_daily_date

KIS_QUOTE_DOMAINS = {"prod":"https://openapi.koreainvestment.com:9443", "vps":"https://openapivts.koreainvestment.com:29443"}
INDEX_CODES = {"KOSPI":"0001", "KOSDAQ":"1001"}

class KISDataError(RuntimeError):
    pass

class KISClient:
    def __init__(self, key=None, secret=None, env=None, session=None, sleep_seconds=.42):
        self.key = key if key is not None else os.getenv("KIS_APP_KEY", "")
        self.secret = secret if secret is not None else os.getenv("KIS_APP_SECRET", "")
        self.env = env if env is not None else os.getenv("KIS_ENV", "prod")
        if self.env not in KIS_QUOTE_DOMAINS:
            raise KISDataError("KIS_ENV must be 'prod' or 'vps'; unapproved URLs cannot receive credentials")
        if not self.key or not self.secret:
            raise KISDataError("Missing KIS_APP_KEY / KIS_APP_SECRET. Obtain read-only market-data credentials yourself.")
        self.base = KIS_QUOTE_DOMAINS[self.env]
        self.session = session or requests.Session()
        self.token = None
        self.token_expiry = 0
        self.sleep_seconds = max(0, sleep_seconds)

    def authenticate(self):
        if self.token and time.time() < self.token_expiry - 60:
            return self.token
        try:
            response = self.session.post(self.base+"/oauth2/tokenP", json={"grant_type":"client_credentials", "appkey":self.key,"appsecret":self.secret}, timeout=16)
            response.raise_for_status()
            body = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise KISDataError("KIS token request failed; credentials, access permission or network may be unavailable") from exc
        token = body.get("access_token")
        if not token:
            raise KISDataError("KIS token response missing access_token (no credentials logged)")
        self.token = token
        self.token_expiry = time.time()+int(body.get("expires_in", 3600))
        return token

    def get(self, path: str, tr_id: str, params: dict) -> dict:
        # Strict allowlist prevents any order endpoint or arbitrary external endpoint.
        allowed = {
            "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
            "/uapi/domestic-stock/v1/quotations/inquire-daily-indexchartprice",
            "/uapi/domestic-stock/v1/quotations/volume-rank",
            "/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice",
            "/uapi/domestic-stock/v1/quotations/inquire-asking-price-exp-ccn",
        }
        if path not in allowed:
            raise KISDataError("Denied: KIS adapter is quote-only; trading endpoints are forbidden")
        self.authenticate()
        headers = {"authorization":f"Bearer {self.token}","appkey":self.key,"appsecret":self.secret,
                   "tr_id":tr_id,"content-type":"application/json; charset=utf-8","custtype":"P"}
        for attempt in range(3):
            if self.sleep_seconds: time.sleep(self.sleep_seconds)
            try:
                response = self.session.get(self.base+path,headers=headers,params=params,timeout=18)
                if response.status_code in (429,500,502,503,504):
                    if attempt < 2:
                        time.sleep(min(3.0, (attempt+1)*.7))
                        continue
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict) or str(payload.get("rt_cd")) != "0":
                    raise KISDataError("KIS API response missing success status or returned failure (details suppressed; check entitlements)")
                return payload
            except (requests.RequestException, ValueError) as exc:
                if attempt >= 2:
                    raise KISDataError("KIS market-data query failed after retries; check API permissions/rate limit/network") from exc
        raise KISDataError("KIS market-data query unavailable")

    def stock_daily(self, code: str, market: str, name: str, sector: str, start: date, end: date) -> list[dict]:
        rows = []
        cursor = end
        # Official API returns at most 100 rows; paginate manually by moving the end date.
        for page in range(6):
            data = self.get("/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice", "FHKST03010100", {
                "FID_COND_MRKT_DIV_CODE":"J", "FID_INPUT_ISCD":code,
                "FID_INPUT_DATE_1":start.strftime("%Y%m%d"),"FID_INPUT_DATE_2":cursor.strftime("%Y%m%d"),
                "FID_PERIOD_DIV_CODE":"D","FID_ORG_ADJ_PRC":"1"})
            batch=data.get("output2",[])
            if not isinstance(batch,list) or not batch: break
            seen_dates=[]
            for b in batch:
                ds=str(b.get("stck_bsop_date", ""))
                if len(ds)!=8 or not ds.isdigit(): continue
                dt=date.fromisoformat(f"{ds[:4]}-{ds[4:6]}-{ds[6:8]}")
                if not(start <= dt <=end): continue
                row={"date":dt.isoformat(),"code":code,"name":name,"market":market,"sector":sector,
                     "open":b.get("stck_oprc"),"high":b.get("stck_hgpr"),"low":b.get("stck_lwpr"),
                     "close":b.get("stck_clpr"),"volume":b.get("acml_vol"),
                     "turnover_krw":b.get("acml_tr_pbmn"),"source":"KIS:KRX:UNADJUSTED"}
                # Do not silently approximate traded value; incomplete API response must be rejected by schema validation.
                rows.append(row)
                seen_dates.append(dt)
            if not seen_dates or min(seen_dates) <= start or len(batch)<90: break
            next_cursor=min(seen_dates)-timedelta(days=1)
            if next_cursor >= cursor: break
            cursor=next_cursor
        return sorted({(x["date"],x["code"]):x for x in rows}.values(), key=lambda r:r["date"])

    def index_daily(self, market: str, start: date, end: date) -> list[dict]:
        rows=[]
        cursor=end
        for page in range(6):
            response=self.get("/uapi/domestic-stock/v1/quotations/inquire-daily-indexchartprice", "FHKUP03500100",{
                "FID_COND_MRKT_DIV_CODE":"U","FID_INPUT_ISCD":INDEX_CODES[market],
                "FID_INPUT_DATE_1":start.strftime("%Y%m%d"),"FID_INPUT_DATE_2":cursor.strftime("%Y%m%d"),
                "FID_PERIOD_DIV_CODE":"D"})
            batch=response.get("output2",[])
            if not isinstance(batch,list) or not batch:break
            dates=[]
            for b in batch:
                ds=str(b.get("stck_bsop_date", ""))
                if len(ds)!=8 or not ds.isdigit():continue
                dt=date.fromisoformat(f"{ds[:4]}-{ds[4:6]}-{ds[6:8]}")
                if not(start<=dt<=end):continue
                rows.append({"date":dt.isoformat(),"market":market,
                             "close":b.get("bstp_nmix_prpr"),"source":"KIS:KRX:INDEX"})
                dates.append(dt)
            if not dates or min(dates)<=start or len(batch)<90:break
            cursor=min(dates)-timedelta(days=1)
        return sorted({x["date"]:x for x in rows}.values(),key=lambda x:x["date"])

    def volume_rank(self, venue="J", max_count=30) -> list[dict]:
        body=self.get("/uapi/domestic-stock/v1/quotations/volume-rank","FHPST01710000",{
            "FID_COND_MRKT_DIV_CODE":venue,"FID_COND_SCR_DIV_CODE":"20171","FID_INPUT_ISCD":"0000",
            "FID_DIV_CLS_CODE":"1","FID_BLNG_CLS_CODE":"3","FID_TRGT_CLS_CODE":"0",
            "FID_TRGT_EXLS_CLS_CODE":"0000000000","FID_INPUT_PRICE_1":"","FID_INPUT_PRICE_2":"",
            "FID_VOL_CNT":"","FID_INPUT_DATE_1":""})
        output=body.get("output",[])
        return [{"code":str(x.get("mksc_shrn_iscd", "")).zfill(6),"name":str(x.get("hts_kor_isnm", "")),
                 "rank":x.get("data_rank"),"source":"KIS_VOLUME_RANK_CURRENT_UNVERIFIED_ASOF"} for x in output[:max_count]
                if x.get("mksc_shrn_iscd")]


def _append_data(path:Path, items:list[dict], ordered_cols:list[str]):
    path.parent.mkdir(parents=True,exist_ok=True)
    new=pd.DataFrame(items,columns=ordered_cols)
    if path.exists():
        old=pd.read_csv(path,dtype={"code":"string"})
        new=pd.concat([old,new],ignore_index=True)
    # Keep conflicts in input rather than silently overwrite. Engine validates them.
    new.to_csv(path,index=False,encoding="utf-8-sig")
    return len(items)


def fetch_bundle(client:KISClient, universe_csv, out_folder, asof, lookback_days=130, max_symbols=45) -> dict:
    from .data import DAILY_FIELDS, INDEX_FIELDS
    u=pd.read_csv(universe_csv,dtype={"code":"string"},keep_default_na=False)
    required={"code","name","market","sector"}
    if not required.issubset(u.columns):raise KISDataError(f"universe.csv needs {sorted(required)}")
    if len(u)>max_symbols:raise KISDataError(f"Too many symbols ({len(u)}); batch at most {max_symbols} to control KIS rate limits")
    if u["code"].duplicated().any():raise KISDataError("Duplicate ticker in universe.csv")
    now=parse_asof(asof)
    end=last_allowed_daily_date(now)
    start=end-timedelta(days=lookback_days)
    result={"asof":now.isoformat(),"query_end_date":str(end),"symbols_attempted":len(u),"symbols_ok":[],"failed":[],"markets_ok":[]}
    out=Path(out_folder)
    for market in INDEX_CODES:
        try:
            items=client.index_daily(market,start,end)
            if len(items)<25: raise KISDataError("under 25 rows")
            _append_data(out/"index_daily.csv",items, INDEX_FIELDS)
            result["markets_ok"].append(market)
        except (KISDataError,ValueError) as e:
            result["failed"].append({"asset":market,"cause":str(e)})
    for _,item in u.iterrows():
        market=str(item["market"]).upper()
        code=str(item["code"]).zfill(6)
        if market not in INDEX_CODES or not code.isdigit() or len(code)!=6:
            result["failed"].append({"asset":code,"cause":"invalid code or market"});continue
        try:
            items=client.stock_daily(code,market,str(item["name"]),str(item["sector"]),start,end)
            if len(items)<25:raise KISDataError("under 25 returned daily rows")
            _append_data(out/"daily.csv",items,DAILY_FIELDS)
            result["symbols_ok"].append(code)
        except (KISDataError,ValueError) as exc:
            result["failed"].append({"asset":code,"cause":str(exc)})
    (out/"kis_fetch_receipt.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    return result

# Minute-based intraday recheck is deliberately strict: if source data is not complete,
# it refuses to manufacture 5-minute VWAP, opening-range highs, or bid/ask spreads.
def _to_five_minute(bars:list[dict], code:str, quote:dict, asof) -> list[dict]:
    now=parse_asof(asof)
    if not bars:return []
    mins=pd.DataFrame(bars)
    for x in ("open","high","low","close","vol","cumulative_traded_value"):
        mins[x]=pd.to_numeric(mins[x],errors="coerce")
    mins["when"]=pd.to_datetime(mins["when"],utc=True,errors="coerce").dt.tz_convert("Asia/Seoul")
    mins=mins[(mins["when"].dt.date == now.date()) & (mins["when"] <= pd.Timestamp(now))]
    mins=mins.drop_duplicates(subset=["when"],keep="last").sort_values("when")
    if len(mins)<15:return []
    # Required: cumulative value measured in KRW and monotonically nondecreasing.
    if mins[["open","high","low","close","vol","cumulative_traded_value"]].isna().any().any():return []
    if (mins["cumulative_traded_value"].diff().fillna(0) < 0).any():return []
    if mins["when"].diff().dropna().dt.total_seconds().gt(60).any():
        return []  # historical gap: volume/turnover cannot be safely attributed
    mins["bar_value"] = mins["cumulative_traded_value"].diff()
    # First known minute's total turnover is cumulative from session open.
    first=mins.iloc[0]["when"]
    if first.time() > datetime.strptime("09:01", "%H:%M").time():return []
    mins.loc[mins.index[0],"bar_value"]=mins.iloc[0]["cumulative_traded_value"]
    if (mins["bar_value"] <= 0).any():return []
    # API field units differ across endpoints. Detect a 1,000x turnover error
    # before a fake VWAP is calculated. Compare traded-value/volume with OHLC.
    if (mins["vol"] <= 0).any():return []
    avg_price=mins["bar_value"] / mins["vol"]
    if ((avg_price < mins["low"]*0.7) | (avg_price > mins["high"]*1.3)).any():return []
    # Minute timestamps are bar ends; raw 09:00 can be an opening auction event and is excluded.
    mins=mins[mins["when"].dt.time > datetime.strptime("09:00","%H:%M").time()]
    mins["five_end"] = mins["when"].dt.ceil("5min")
    output=[]
    for end,group in mins.groupby("five_end"):
        if len(group)!=5: continue
        # Last bar must have closed at least 1 minute ago: protect against incomplete updates.
        if end > pd.Timestamp(now)-pd.Timedelta(minutes=1): continue
        g=group.sort_values("when")
        output.append({"bar_end":end.isoformat(),"code":code,"venue":"KRX",
                       "open":g.iloc[0]["open"],"high":float(g["high"].max()),"low":float(g["low"].min()),
                       "close":g.iloc[-1]["close"],"volume":float(g["vol"].sum()),
                       "turnover_krw":float(g["bar_value"].sum()),"bid":0,"ask":0,"source":"KIS:KRX:1MIN_AGGREGATED"})
    if output:
        output[-1]["bid"]=quote.get("bid",0)
        output[-1]["ask"]=quote.get("ask",0)
    return output


def _fetch_stock_minute(client:KISClient, code:str, asof) -> list[dict]:
    now=parse_asof(asof)
    if now.time()<datetime.strptime("09:20","%H:%M").time():return []
    # The KIS endpoint generally returns a short rolling window; query checkpoints.
    checkpoints=pd.date_range(now.replace(hour=9,minute=30,second=0),
                              now.replace(second=0,microsecond=0)+timedelta(minutes=20),freq="25min")
    if not len(checkpoints):checkpoints=[now]
    raw=[]
    for chk in checkpoints:
        hhmmss=min(pd.Timestamp(chk).to_pydatetime(),now).strftime("%H%M%S")
        res=client.get("/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice",
            "FHKST03010200",{
            "FID_COND_MRKT_DIV_CODE":"J","FID_INPUT_ISCD":code,
            "FID_INPUT_HOUR_1":hhmmss,"FID_PW_DATA_INCU_YN":"N","FID_ETC_CLS_CODE":""})
        for x in res.get("output2",[]):
            hour=str(x.get("stck_cntg_hour", "")).zfill(6)
            if len(hour)!=6 or not hour.isdigit():continue
            date_part=str(x.get("stck_bsop_date",now.strftime("%Y%m%d")))
            if len(date_part)!=8 or not date_part.isdigit():continue
            ds=f"{date_part[:4]}-{date_part[4:6]}-{date_part[6:8]}T{hour[:2]}:{hour[2:4]}:{hour[4:6]}+09:00"
            raw.append({"when":ds,"open":x.get("stck_oprc"),"high":x.get("stck_hgpr"),
                "low":x.get("stck_lwpr"),"close":x.get("stck_prpr"),"vol":x.get("cntg_vol"),
                "cumulative_traded_value":x.get("acml_tr_pbmn")})
    return raw


def fetch_intraday_from_kis(client:KISClient, watch_json, out_csv, asof) -> dict:
    from .data import INTRADAY_FIELDS
    base=json.loads(Path(watch_json).read_text(encoding="utf-8"))
    if base.get("mode")!="PREOPEN_WATCHLIST_ONLY":raise KISDataError("Supply a preopen.json watchlist")
    data=[];failed=[]
    for r in base["records"]:
        if r["status"]!="WATCH":continue
        code=r["code"]
        try:
            minute=_fetch_stock_minute(client,code,asof)
            reply=client.get("/uapi/domestic-stock/v1/quotations/inquire-asking-price-exp-ccn", "FHKST01010200", {
                "FID_COND_MRKT_DIV_CODE":"J","FID_INPUT_ISCD":code})
            quote=reply.get("output1",{})
            out=_to_five_minute(minute,code,{"bid":float(quote.get("bidp1",0)),"ask":float(quote.get("askp1",0))},asof)
            if not out:raise KISDataError("Could not verify continuous minute history and cumulative turnover; VWAP must remain unavailable")
            data.extend(out)
        except (KISDataError,ValueError,KeyError) as exc:
            failed.append({"code":code,"error":str(exc)})
    p=Path(out_csv);p.parent.mkdir(parents=True,exist_ok=True)
    pd.DataFrame(data,columns=INTRADAY_FIELDS).to_csv(p,index=False,encoding="utf-8-sig")
    return {"requested":sum(r["status"]=="WATCH" for r in base["records"]),"bars":len(data),"failed":failed,
            "caution":"REST snapshots may omit opening history or exact bid/ask quote time; blocks are expected rather than fabricated"}
