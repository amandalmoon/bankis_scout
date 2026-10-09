from datetime import date
import pandas as pd
import pytest
from bankis_scout.data import load_bundle
from bankis_scout.demo import create_demo
from bankis_scout.engine import screen_bundle
from bankis_scout.monitor import recheck
from bankis_scout.settings import Settings,last_allowed_daily_date,parse_asof

ASOF="2026-10-09T08:00:00+09:00"
@pytest.fixture
def bundle(tmp_path):
    return load_bundle(create_demo(tmp_path/"demo"))

def by_code(result,code):return next(r for r in result["records"] if r["code"]==code)

def test_screen_watch_and_hard_reject(bundle):
    x=screen_bundle(bundle,ASOF)
    assert x["coverage"]["watch"]==1
    assert by_code(x,"SYN001")["status"]=="WATCH"
    assert by_code(x,"SYN002")["status"]=="REJECTED"
    assert "RISK_FLAG:HALT" in by_code(x,"SYN002")["reasons"]
    assert by_code(x,"SYN003")["status"]=="REJECTED"
    assert "LOW_TURNOVER" in by_code(x,"SYN003")["reasons"]

def test_invalid_price_blocks_even_big_volume(bundle):
    x=screen_bundle(bundle,ASOF)
    r=by_code(x,"SYN006")
    assert r["status"]=="DATA_BLOCKED"
    assert "INVALID_OHLC_OR_SOURCE" in r["reasons"]
    assert r["score"] is None

def test_min_history_blocks(bundle):
    x=screen_bundle(bundle,ASOF)
    r=by_code(x,"SYN004")
    assert r["status"]=="DATA_BLOCKED"
    assert "INSUFFICIENT_HISTORY" in r["reasons"]

def test_no_future_close_at_8am(bundle):
    x=screen_bundle(bundle,ASOF)
    bundle["daily"]=pd.concat([bundle["daily"],pd.DataFrame([{
        "date":"2026-10-09","code":"SYN001","name":"가짜 미래","market":"KOSDAQ","sector":"반도체",
        "open":1,"high":10000000,"low":1,"close":10000000,"volume":9999999,"turnover_krw":1e15,"source":"FUTURE"}])],ignore_index=True)
    y=screen_bundle(bundle,ASOF)
    assert by_code(x,"SYN001")==by_code(y,"SYN001")

def test_missing_eligibility_fails_closed(bundle):
    bundle["eligibility"]=bundle["eligibility"][bundle["eligibility"]["code"]!="SYN001"]
    r=by_code(screen_bundle(bundle,ASOF),"SYN001")
    assert r["status"]=="DATA_BLOCKED"
    assert "ELIGIBILITY_UNVERIFIED" in r["reasons"]

def test_missing_benchmark_fails_closed(bundle):
    bundle["index"]=bundle["index"][bundle["index"]["market"]!="KOSDAQ"]
    r=by_code(screen_bundle(bundle,ASOF),"SYN001")
    assert r["status"]=="DATA_BLOCKED"
    assert "MISSING_BENCHMARK" in r["reasons"]

def test_conflicting_duplicate_fails_closed(bundle):
    last=bundle["daily"][(bundle["daily"]["code"]=="SYN001")].iloc[-1].to_dict()
    last["close"]=last["close"]-100
    bundle["daily"]=pd.concat([bundle["daily"],pd.DataFrame([last])],ignore_index=True)
    r=by_code(screen_bundle(bundle,ASOF),"SYN001")
    assert "CONFLICTING_DUPLICATE" in r["reasons"]
    assert r["status"]=="DATA_BLOCKED"

def test_event_future_published_not_counted(bundle):
    bundle["events"].loc[bundle["events"]["code"]=="SYN001","published_at"]="2026-10-09T18:00:00+09:00"
    r=by_code(screen_bundle(bundle,ASOF),"SYN001")
    assert r["components"]["공시 촉매"]==0

def test_eod_before_cutoff():
    assert str(last_allowed_daily_date(parse_asof("2026-10-09T08:00:00+09:00")))=="2026-10-08"
    assert str(last_allowed_daily_date(parse_asof("2026-10-09T16:00:00+09:00")))=="2026-10-09"

def test_wait_until_after_opening_range(bundle):
    base=screen_bundle(bundle,ASOF)
    r=by_code(recheck(base,bundle["intraday"],"2026-10-12T09:10:00+09:00"),"SYN001")
    assert r["intraday_status"]=="WAIT_FOR_0920"

def test_orb_confirmed_on_completed_bars(bundle):
    base=screen_bundle(bundle,ASOF)
    r=by_code(recheck(base,bundle["intraday"],"2026-10-12T09:37:00+09:00"),"SYN001")
    assert r["intraday_status"]=="CONFIRMED_PATTERN"
    assert r["intraday"]["vwap"]>0

def test_wide_quote_rejection(bundle):
    base=screen_bundle(bundle,ASOF)
    bundle["intraday"].loc[bundle["intraday"]["bar_end"].str.contains("09:35"),"ask"]=17000
    r=by_code(recheck(base,bundle["intraday"],"2026-10-12T09:37:00+09:00"),"SYN001")
    assert r["intraday_status"]=="REJECTED"
    assert "SPREAD_TOO_WIDE" in r["intraday_reasons"]

def test_missing_quote_fails_closed(bundle):
    base=screen_bundle(bundle,ASOF)
    bundle["intraday"].loc[bundle["intraday"]["bar_end"].str.contains("09:35"),"bid"]=float("nan")
    r=by_code(recheck(base,bundle["intraday"],"2026-10-12T09:37:00+09:00"),"SYN001")
    assert r["intraday_status"]=="DATA_BLOCKED"

def test_no_opening_range_cannot_confirm(bundle):
    base=screen_bundle(bundle,ASOF)
    incomplete=bundle["intraday"][~bundle["intraday"]["bar_end"].str.contains("09:10")]
    r=by_code(recheck(base,incomplete,"2026-10-12T09:37:00+09:00"),"SYN001")
    assert r["intraday_status"]=="DATA_BLOCKED"
    assert "OPENING_RANGE_INCOMPLETE" in r["intraday_reasons"]

def test_false_breakout_reject(bundle):
    base=screen_bundle(bundle,ASOF)
    rows=bundle["intraday"].copy()
    rows.loc[rows["bar_end"].str.contains("09:30"),"high"]=15950
    for time in ("09:30","09:35"):
        mask=rows["bar_end"].str.contains(time)
        rows.loc[mask,"open"]=15670
        rows.loc[mask,"high"]=16000 if time=="09:30" else 15690
        rows.loc[mask,"low"]=15520
        rows.loc[mask,"close"]=15630
    r=by_code(recheck(base,rows,"2026-10-12T09:37:00+09:00"),"SYN001")
    assert r["intraday_status"]=="REJECTED"
    assert "FALSE_BREAKOUT_CONFIRMED" in r["intraday_reasons"]


def test_recheck_blocks_wrong_venue_scope(bundle):
    base=screen_bundle(bundle,ASOF)
    altered=bundle["intraday"].copy()
    altered.loc[altered["code"]=="SYN001","venue"]="NXT"
    item=by_code(recheck(base,altered,"2026-10-12T09:37:00+09:00"),"SYN001")
    assert item["intraday_status"]=="DATA_BLOCKED"
    assert "VENUE_SCOPE_NOT_KRX" in item["intraday_reasons"]
