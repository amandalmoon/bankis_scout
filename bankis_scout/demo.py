"""Entirely synthetic fixtures, intentionally non-tradable codes SYN001 etc."""
from __future__ import annotations
from datetime import datetime, timedelta
from pathlib import Path
import numpy as np
import pandas as pd
from .data import DAILY_FIELDS,INDEX_FIELDS,ELIGIBILITY_FIELDS,EVENT_FIELDS,INTRADAY_FIELDS


def create_demo(folder):
    p=Path(folder);p.mkdir(parents=True,exist_ok=True)
    dates=pd.bdate_range("2026-05-20","2026-10-08")[-90:]
    day_rows=[]; index_rows=[]; eligible=[]
    symbols=[("SYN001","가상 모멘텀 A","KOSDAQ","반도체",11500,1.005,4_500_000),
             ("SYN002","가상 경고 B","KOSDAQ","2차전지",13000,1.007,5_000_000),
             ("SYN003","가상 저유동 C","KOSPI","소비재",10000,1.003,30000),
             ("SYN004","가상 누락 D","KOSDAQ","바이오",8000,1.006,1_700_000),
             ("SYN005","가상 중립 E","KOSPI","서비스",12500,1.001,2_800_000),
             ("SYN006","가상 오류 F","KOSPI","기계",9000,1.007,3_000_000)]
    market_idx={"KOSPI":2700.0,"KOSDAQ":880.0}
    for i,dt in enumerate(dates):
        for market in market_idx:
            close=market_idx[market]*(1.0006**i)
            index_rows.append({"date":dt.date().isoformat(),"market":market,"close":round(close,3),"source":"SYNTHETIC_INDEX"})
        for k,(code,name,market,sector,base,ret,basevol) in enumerate(symbols):
            if code=="SYN004" and i<67: continue
            price=base*(ret**i) * (1+0.006*np.sin(i*.36+k))
            prev=base*(ret**max(i-1,0))*(1+0.006*np.sin(max(i-1,0)*.36+k))
            op=prev*(1+0.0008*np.cos(i*.6+k))
            hi=max(price,op)*1.012;lo=min(price,op)*.987
            vol=basevol*(1+0.15*np.sin(i*.19+k))
            if i==len(dates)-1 and code in ("SYN001","SYN002","SYN006"):
                vol*=2.6; price*=1.025; hi=max(hi,price*1.004)
            if code=="SYN006" and i==len(dates)-1:
                hi=price*.95 # deliberately invalid OHLC to test quarantine
            day_rows.append({"date":dt.date().isoformat(),"code":code,"name":name,"market":market,
                "sector":sector,"open":round(op,2),"high":round(hi,2),"low":round(lo,2),
                "close":round(price,2),"volume":round(vol),"turnover_krw":round(vol*(price+op)/2),"source":"SYNTHETIC_GENERATOR"})
            eligible.append({"code":code,"eligible":"true","risk_level":"HALT" if code=="SYN002" else "NONE",
                             "checked_at":dt.date().isoformat()+"T17:00:00+09:00", "source_url":"https://example.invalid/demo-eligibility"})
    ev=[{"code":"SYN001","published_at":"2026-10-07T16:10:00+09:00","event_type":"earnings",
         "title":"합성 예시: 실적 개선", "source_url":"https://example.invalid/synthetic-earnings", "verified":"true","materiality":5},
        {"code":"SYN002","published_at":"2026-10-07T17:00:00+09:00","event_type":"contract",
         "title":"합성 예시: 대형 계약", "source_url":"https://example.invalid/synthetic-contract", "verified":"true","materiality":5},
        {"code":"SYN005","published_at":"2026-10-06T16:00:00+09:00","event_type":"other",
         "title":"합성 예시: 근거 없는 관심 급증", "source_url":"https://example.invalid/synthetic-noise", "verified":"false","materiality":0}]
    bars=[]
    # All bar_end timestamps are 5-minute CLOSED bar ends, not bar starts.
    seq=[(9,5,15450,15520,15410,15500,1000000),(9,10,15500,15700,15490,15670,1150000),
         (9,15,15670,15800,15650,15770,1400000),(9,20,15770,15790,15680,15710,850000),
         (9,25,15710,15780,15670,15765,730000),(9,30,15765,15920,15755,15890,1250000),
         (9,35,15890,16100,15870,16070,2200000)]
    for hour,minute,op,hi,lo,cl,vol in seq:
        bars.append({"bar_end":f"2026-10-12T{hour:02d}:{minute:02d}:00+09:00","code":"SYN001",
                     "venue":"KRX","open":op,"high":hi,"low":lo,"close":cl,
                     "volume":vol,"turnover_krw":round(((op+hi+lo+cl)/4)*vol),"bid":cl-10,"ask":cl+10,"source":"SYNTHETIC_5MIN"})
    def put(fname,rows,cols):
        pd.DataFrame(rows,columns=cols).to_csv(p/fname,index=False,encoding="utf-8-sig")
    put("daily.csv",day_rows,DAILY_FIELDS);put("index_daily.csv",index_rows,INDEX_FIELDS)
    put("eligibility.csv",eligible,ELIGIBILITY_FIELDS);put("events.csv",ev,EVENT_FIELDS)
    put("intraday.csv",bars,INTRADAY_FIELDS)
    (p/"THIS_IS_SYNTHETIC.txt").write_text("ALL rows are artificially generated and NOT real market prices. SYN codes do not exist.\n",encoding="utf-8")
    return p
