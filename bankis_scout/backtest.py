"""Point-in-time screening event study, NOT a broker fill simulator or strategy approval."""
from __future__ import annotations
from datetime import datetime, time, timedelta
from pathlib import Path
import json
import numpy as np
import pandas as pd
from .settings import Settings, KST
from .engine import screen_bundle


def _stats(items):
    a=np.asarray(items,dtype=float)
    if len(a)==0:return {"n":0,"mean_net_pct":None,"median_net_pct":None,"hit_rate":None,"p10_pct":None,"worst_pct":None}
    return {"n":int(len(a)),"mean_net_pct":round(float(a.mean()),4),
            "median_net_pct":round(float(np.median(a)),4),"hit_rate":round(float((a>0).mean()),4),
            "p10_pct":round(float(np.percentile(a,10)),4),"worst_pct":round(float(a.min()),4)}


def event_study(bundle:dict, hold_days=1, top_n=3, cost_bps=33.0, settings:Settings|None=None, max_signal_dates=100) -> dict:
    if hold_days<1 or hold_days>10:raise ValueError("hold_days must be between 1 and 10")
    if top_n<1:raise ValueError("top_n must be >=1")
    cfg=settings or Settings()
    stock=bundle["daily"].copy()
    stock["date"]=pd.to_datetime(stock["date"]).dt.date
    for field in ["open","close"]:stock[field]=pd.to_numeric(stock[field],errors="coerce")
    idx=bundle["index"].copy()
    idx["date"]=pd.to_datetime(idx["date"]).dt.date
    dates=sorted(idx[idx["market"]=="KOSPI"]["date"].unique())
    # Price history must extend beyond first usable signal, and past latest signals without future exit are dropped.
    if len(dates)<cfg.history_min+hold_days+5:
        return {"status":"INSUFFICIENT_HISTORY","trades":[],"baseline":[],"summary":{},"hold_days":hold_days,"note":"No performance claim"}
    candidates = dates[cfg.history_min-1:-hold_days]
    if max_signal_dates>0:candidates=candidates[-max_signal_dates:]
    trades=[]; baseline=[]; snapshots=[]
    for pos, day in enumerate(candidates):
        k=dates.index(day)
        entry_day=dates[k+1]; exit_day=dates[k+hold_days]
        # Screening at next session 08:00 can only use data available by the prior close.
        asof=datetime.combine(entry_day,time(8,0),tzinfo=KST)
        pre=screen_bundle(bundle,asof,cfg)
        valid=[r for r in pre["records"] if r["status"]=="WATCH" or (r["status"]=="REJECTED" and r["reasons"]==["SCORE_BELOW_WATCH_THRESHOLD"])]
        chosen=sorted((r for r in valid if r["status"]=="WATCH"),key=lambda r:-r["score"])[:top_n]
        chosen_codes={r["code"] for r in chosen}
        for group, subset, output in (("selected",chosen,trades),("baseline",valid,baseline)):
            for r in subset:
                ss=stock[(stock["code"].astype(str).str.zfill(6)==r["code"]) &
                         (stock["date"].isin([entry_day,exit_day]))]
                opens=ss.loc[ss["date"]==entry_day,"open"]
                closes=ss.loc[ss["date"]==exit_day,"close"]
                if len(opens)!=1 or len(closes)!=1 or opens.iloc[0]<=0 or closes.iloc[0]<=0:continue
                gross=(float(closes.iloc[0])/float(opens.iloc[0])-1)*100
                net=gross-cost_bps/100
                output.append({"signal_date":str(day),"entry_day":str(entry_day),"exit_day":str(exit_day),
                               "code":r["code"],"name":r["name"],"score":r["score"],"entry_open":float(opens.iloc[0]),
                               "exit_close":float(closes.iloc[0]),"gross_pct":round(gross,4),"net_pct":round(net,4)})
        snapshots.append({"signal_date":str(day),"eligible":len(valid),"watch":len(chosen),"data_blocked":pre["coverage"]["data_blocked"]})
    # Holdout is the last 20% of SIGNAL DATES, not last 20% of rows / symbols.
    unique_dates=sorted({r["signal_date"] for r in trades + baseline})
    split_idx=int(len(unique_dates)*.8)
    cutoff=unique_dates[split_idx] if split_idx<len(unique_dates) else None
    hold_trades=[r["net_pct"] for r in trades if cutoff and r["signal_date"]>=cutoff]
    hold_base=[r["net_pct"] for r in baseline if cutoff and r["signal_date"]>=cutoff]
    return {"status":"NO_TESTABLE_SELECTED_TRADES" if not trades else "DESCRIPTIVE_ONLY_NOT_VALIDATED","hold_days":hold_days,"top_n":top_n,
            "cost_bps":float(cost_bps),"date_range":[str(candidates[0]),str(candidates[-1])],
            "summary":{"selected_all":_stats([r["net_pct"] for r in trades]),"baseline_all":_stats([r["net_pct"] for r in baseline]),
                       "selected_holdout":_stats(hold_trades),"baseline_holdout":_stats(hold_base),
                       "holdout_first_signal_date":cutoff,"num_signal_days":len(unique_dates)},
            "trades":trades,"baseline":baseline,"coverage_snapshots":snapshots,
            "limitations":["Restricted to supplied universe, NOT full Korean market; survivorship risk if tickers omit delisted firms",
                           "Eligibility snapshots must exist as of each historic date, otherwise missing candidates are excluded",
                           "Uses next session open and horizon close; no intraday stops, order-book slippage, unfilled orders, trade-size constraints or gap risk",
                           "Simple event study, overlapping trades possible; means are not compound account returns",
                           "Weights/thresholds fixed by developer, NOT out-of-sample optimized; holdout measures descriptive only",
                           "Positive selected-minus-baseline does not establish causality or statistically significant alpha"]}
