import json
from pathlib import Path
import pandas as pd
import pytest
from bankis_scout.demo import create_demo
from bankis_scout.data import load_bundle
from bankis_scout.backtest import event_study
from bankis_scout.settings import Settings
from bankis_scout.kis import KISClient,KISDataError,_to_five_minute,_fetch_stock_minute,fetch_bundle
from bankis_scout.report import write_artifacts
from bankis_scout.engine import screen_bundle

class MockResponse:
    status_code=200
    def __init__(self,payload):self.payload=payload
    def raise_for_status(self):pass
    def json(self):return self.payload
class MockSession:
    def post(self,url,**kw):return MockResponse({"access_token":"not-a-real-token","expires_in":2000})
    def get(self,url,**kw):
        if "inquire-daily-itemchartprice" in url:
            d={"stck_bsop_date":"20261008","stck_oprc":"10000","stck_hgpr":"10200",
               "stck_lwpr":"9900","stck_clpr":"10150","acml_vol":"3000000","acml_tr_pbmn":"30000000000"}
            return MockResponse({"rt_cd":"0","output2":[d]})
        if "inquire-daily-indexchartprice" in url:
            return MockResponse({"rt_cd":"0","output2":[{"stck_bsop_date":"20261008","bstp_nmix_prpr":"3000"}]})
        if "volume-rank" in url:
            return MockResponse({"rt_cd":"0","output":[{"mksc_shrn_iscd":"005930","hts_kor_isnm":"삼성전자","data_rank":"1"}]})
        return MockResponse({"rt_cd":"0","output1":{"bidp1":"10000","askp1":"10010"}})

def test_kis_quote_only_endpoint_allowlist():
    client=KISClient(key="fake",secret="fake",session=MockSession(),sleep_seconds=0)
    assert len(client.volume_rank())==1
    with pytest.raises(KISDataError):
        client.get("/uapi/domestic-stock/v1/trading/order-cash","TTTC0802U",{})

def test_kis_daily_mock_contract():
    from datetime import date
    c=KISClient(key="fake",secret="fake",session=MockSession(),sleep_seconds=0)
    res=c.stock_daily("005930","KOSPI","삼성전자","반도체",date(2026,10,1),date(2026,10,8))
    assert len(res)==1
    assert float(res[0]["turnover_krw"])==30_000_000_000
    res2=c.index_daily("KOSPI",date(2026,10,1),date(2026,10,8))
    assert res2[0]["market"]=="KOSPI"

def test_api_credentials_required():
    with pytest.raises(KISDataError):
        KISClient(key="",secret="",sleep_seconds=0)

def test_minute_missing_baseline_returns_empty():
    assert _to_five_minute([],"005930",{"bid":10,"ask":11},"2026-10-12T09:40:00+09:00")==[]

def test_backtest_no_promised_edge_on_synthetic(tmp_path):
    b=load_bundle(create_demo(tmp_path/"demo"))
    r=event_study(b,hold_days=1,max_signal_dates=40)
    assert r["status"]=="NO_TESTABLE_SELECTED_TRADES"
    assert r["summary"]["selected_all"]["n"]==0
    assert r["summary"]["baseline_all"]["n"]>0
    assert "No performance claim" not in str(r["limitations"])

def test_backtest_has_selected_after_looser_explicit_threshold(tmp_path):
    b=load_bundle(create_demo(tmp_path/"demo"))
    x=event_study(b,settings=Settings(min_watch_score=30,min_turnover_krw=1_000_000_000,min_median_turnover_krw=1_000_000_000),max_signal_dates=60)
    assert x["summary"]["selected_all"]["n"]>0
    assert x["summary"]["holdout_first_signal_date"] is not None
    for r in x["trades"]:
        assert r["signal_date"] < r["entry_day"] <= r["exit_day"]

def test_html_output_is_saved_and_is_flagged_synthetic(tmp_path):
    b=load_bundle(create_demo(tmp_path/"demo"))
    x=screen_bundle(b,"2026-10-09T08:00:00+09:00")
    paths=write_artifacts(x,tmp_path/"output",sample=True)
    s=open(paths["html"],encoding="utf-8").read()
    assert "교육용 합성" in s
    assert "SYN001" in s and "DATA_BLOCKED" in s
    assert "강세점수" in s
    assert json.loads(Path(paths["json"]).read_text(encoding="utf-8"))["coverage"]["watch"]==1


def _minute_fake_batch(multiplier=1):
    points=[]; cum=0
    for m in range(1,21):
        cum += 100_000 * 10_000 * multiplier
        points.append({"when":f"2026-10-12T09:{m:02d}:00+09:00","open":10000,"high":10020,"low":9980,
                       "close":10000,"vol":100_000,"cumulative_traded_value":cum})
    return points


def test_minute_turnover_units_fail_closed():
    assert len(_to_five_minute(_minute_fake_batch(),"005930",{"bid":9990,"ask":10010},"2026-10-12T09:22:00+09:00"))==4
    assert _to_five_minute(_minute_fake_batch(1000),"005930",{"bid":9990,"ask":10010},"2026-10-12T09:22:00+09:00")==[]


def test_minute_api_calls_three_parameters_not_four():
    class GetSpy:
        def __init__(self):self.calls=[]
        def get(self,path,tr_id,params):
            self.calls.append((path,tr_id,params))
            return {"output2":[]}
    c=GetSpy()
    assert _fetch_stock_minute(c,"005930","2026-10-12T09:37:00+09:00")==[]
    assert all(len(x)==3 and x[1]=="FHKST03010200" for x in c.calls)


def test_recheck_older_than_six_days_rejected(tmp_path):
    from bankis_scout.monitor import recheck
    bundle=load_bundle(create_demo(tmp_path/"demo"))
    pre=screen_bundle(bundle,"2026-10-09T08:00:00+09:00")
    r=recheck(pre,bundle["intraday"],"2026-10-20T09:37:00+09:00")
    candidate=next(x for x in r["records"] if x["code"]=="SYN001")
    assert candidate["intraday_status"]=="DATA_BLOCKED"
    assert "PREOPEN_WATCHLIST_MISSING_FUTURE_OR_TOO_OLD" in candidate["intraday_reasons"]


def test_recheck_rejects_incompatible_turnover_units(tmp_path):
    from bankis_scout.monitor import recheck
    bundle=load_bundle(create_demo(tmp_path/"demo"))
    pre=screen_bundle(bundle,"2026-10-09T08:00:00+09:00")
    x=bundle["intraday"].copy()
    x.loc[x["code"]=="SYN001","turnover_krw"] = x.loc[x["code"]=="SYN001","turnover_krw"].astype(float)*1000
    r=recheck(pre,x,"2026-10-12T09:37:00+09:00")
    candidate=next(x for x in r["records"] if x["code"]=="SYN001")
    assert candidate["intraday_status"]=="DATA_BLOCKED"
    assert "TRADED_VALUE_UNITS_OR_PRICE_MISMATCH" in candidate["intraday_reasons"]
