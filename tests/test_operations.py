import json
import threading
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer

import pandas as pd
import pytest
import requests

from bankis_scout.account import KISAccountReader, BALANCE
from bankis_scout.briefing_server import handler_class
from bankis_scout.collect_all import validate_stock
from bankis_scout.data import DAILY_FIELDS
from bankis_scout.kis import KISClient, KISDataError
from bankis_scout.performance import freeze_snapshot, evaluate_forward
from bankis_scout.settings import KST
from bankis_scout.universe import parse_master
from bankis_scout.feed import write_feed, FEED_FILES


def bar(code="005930", day="2026-10-08"):
    return {"code": code, "date": day, "name": "sample", "market": "KOSPI", "sector": "",
            "open": "100", "high": "110", "low": "90", "close": "105", "volume": "1000",
            "turnover_krw": "105000", "source": "MOCK_TEST"}


def test_master_keeps_alphanumeric_equities_excludes_etf():
    def line(code, group, name):
        return (code.ljust(9) + "KR7000000001" + name + " " * 10 + group + "0" * 225 + "\n").encode("cp949")
    rows, excluded = parse_master(line("0001A0", "ST", "종목") + line("123456", "EF", "펀드"), "KOSPI")
    assert [x["code"] for x in rows] == ["0001A0"]
    assert rows[0]["name"] == "종목"
    assert excluded == {"EF": 1}


def test_master_rejects_short_or_duplicate_records():
    with pytest.raises(ValueError):
        parse_master(b"short\n", "KOSPI")


def test_stock_contract_rejects_nonfinite_and_invalid_ohlc():
    for field, value in [("open", "inf"), ("high", "80"), ("turnover_krw", "")]:
        row = {**bar(), field: value}
        with pytest.raises(ValueError):
            validate_stock([row], datetime(2026, 10, 9).date())


class Response:
    def __init__(self, more=False, cursor="cursor"):
        self.headers = {"tr_cont": "M" if more else "D"}
        self.more, self.cursor = more, cursor
    def raise_for_status(self):
        pass
    def json(self):
        return {"rt_cd": "0", "output1": [{"pdno": "005930"}], "output2": [{}],
                "ctx_area_fk100": self.cursor, "ctx_area_nk100": "next"}


class Session:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []
    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


def reader(monkeypatch, responses):
    monkeypatch.setattr("bankis_scout.account.time.sleep", lambda _: None)
    session = Session(responses)
    client = KISClient(key="fake", secret="fake", env="vps", session=session)
    client.token, client.token_expiry = "fake-token", 9999999999
    return KISAccountReader(client, "12345678", "01"), session


def test_account_requires_actual_product_code():
    with pytest.raises(ValueError):
        KISAccountReader(None, "12345678", "")


def test_account_denies_orders_before_network(monkeypatch):
    account, session = reader(monkeypatch, [])
    with pytest.raises(KISDataError):
        account.pages("/uapi/domestic-stock/v1/trading/order-cash", {})
    assert session.calls == []


def test_account_pagination_uses_sandbox_id_and_preserves_all_pages(monkeypatch):
    account, session = reader(monkeypatch, [Response(True), Response(False)])
    assert len(account.balance()) == 2
    assert session.calls[0][1]["headers"]["tr_id"] == "VTTC8434R"
    assert session.calls[1][1]["headers"]["tr_cont"] == "N"
    assert session.calls[1][1]["params"]["CTX_AREA_FK100"] == "cursor"


def test_account_repeated_cursor_is_failure(monkeypatch):
    account, _ = reader(monkeypatch, [Response(True), Response(True)])
    with pytest.raises(KISDataError):
        account.balance()


def test_forward_records_never_overwrite_or_accept_late_selection(tmp_path):
    now = datetime(2026, 10, 8, 8, tzinfo=KST)
    report = {"asof": now.isoformat(), "records": [{"code": "005930", "status": "WATCH", "score": 70,
              "reasons": [], "features": {"last_date": "2026-10-07", "last_turnover_krw": 100}}]}
    receipt = {"status": "COMPLETE", "finished_at": (now - timedelta(minutes=5)).isoformat()}
    assert freeze_snapshot(report, receipt, tmp_path, now=now)["status"] == "RECORDED"
    assert freeze_snapshot(report, receipt, tmp_path, now=now)["status"] == "EXISTING_RECORD_PRESERVED"
    assert freeze_snapshot(report, receipt, tmp_path, now=now.replace(hour=10))["status"] == "NO_FORWARD_RECORD"
    bundle = {"daily": pd.DataFrame([bar()], columns=DAILY_FIELDS), "index": pd.DataFrame([{"date": "2026-10-08"}])}
    result = evaluate_forward(bundle, tmp_path)
    assert result["status"] == "EXPLORATORY_PAPER_RESULTS"
    assert result["independent_profitability_verified"] is False
    assert result["summary"]["n"] == 1
    assert result["summary"]["scenarios"][1]["selected_mean_net_pct"] == pytest.approx(4.67)


def test_forward_rejects_partial_collection_and_tampered_record(tmp_path):
    now = datetime(2026, 10, 8, 8, tzinfo=KST)
    report = {"asof": now.isoformat(), "records": []}
    receipt = {"status": "PARTIAL", "finished_at": now.isoformat()}
    assert freeze_snapshot(report, receipt, tmp_path, now=now)["reason"] == "INCOMPLETE_UNIVERSE_COLLECTION"
    receipt["status"] = "COMPLETE"
    freeze_snapshot(report, receipt, tmp_path, now=now)
    path = tmp_path / "snapshots" / "2026-10-08.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["selected"] = ["005930"]
    path.write_text(json.dumps(data), encoding="utf-8")
    result = evaluate_forward({"daily": pd.DataFrame([bar()]), "index": pd.DataFrame([{"date": "2026-10-08"}])}, tmp_path)
    assert result["status"] == "NOT_MEASURABLE"
    assert result["excluded"][0]["reason"] == "RECORD_INTEGRITY_OR_PLAN_MISMATCH"


@pytest.fixture
def report_server(tmp_path):
    now = datetime.now(KST)
    stamp = now.strftime("%Y%m%dT%H%M%S%f")
    export = tmp_path / stamp
    export.mkdir()
    (tmp_path / "CURRENT").write_text(stamp, encoding="utf-8")
    status = {"generated_at": now.isoformat(), "collection_finished_at": (now - timedelta(minutes=5)).isoformat(),
              "environment": "vps", "received_symbols": 1}
    (export / "status.json").write_text(json.dumps(status), encoding="utf-8")
    (export / "briefing.md").write_text("market report", encoding="utf-8")
    for name in ("intelligence.html", "preopen.html"):
        (export / name).write_text("report", encoding="utf-8")
    bundle = {"daily": pd.DataFrame([bar()], columns=DAILY_FIELDS),
              "index": pd.DataFrame([{"date": "2026-10-08", "market": "KOSPI", "close": 100, "source": "MOCK_TEST"}])}
    write_feed(export, bundle, status)
    token = "testtoken" * 5
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_class(tmp_path, token))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    yield f"http://127.0.0.1:{server.server_port}", token, export
    server.shutdown()
    server.server_close()
    worker.join()


def test_report_server_excludes_secrets_and_requires_read_token(report_server):
    url, token, _ = report_server
    assert requests.get(url + "/wrong/briefing.md", timeout=3).status_code == 404
    assert requests.get(url + "/" + token + "/.env", timeout=3).status_code == 404
    assert requests.get(url + "/" + token + "/briefing.md", timeout=3).text == "market report"


def test_report_server_refuses_old_report(report_server):
    url, token, export = report_server
    (export / "status.json").write_text(json.dumps({"generated_at": (datetime.now(KST) - timedelta(days=1)).isoformat()}), encoding="utf-8")
    assert requests.get(url + "/" + token + "/briefing.md", timeout=3).status_code == 503


def test_full_collection_resumes_and_does_not_approve_eligibility(tmp_path, monkeypatch):
    import bankis_scout.collect_all as collection
    def master(folder):
        frame = pd.DataFrame([{"code": code, "market": "KOSPI", "name": code, "sector": ""}
                              for code in ("005930", "0001A0")])
        receipt = {"symbols": 2, "historical_constituents_verified": False}
        frame.to_csv(folder / "universe.csv", index=False)
        (folder / "universe_receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
        return frame, receipt
    class FakeClient:
        calls = 0
        def __init__(self, **kwargs):
            self.env, self.key, self.secret = "vps", "fake", "fake"
            self.token, self.token_expiry = "fake", 9999999999
        def authenticate(self):
            return self.token
        def index_daily(self, market, start, end):
            return [{"date": "2026-10-08", "market": market, "close": 100, "source": "MOCK_TEST"}]
        def stock_daily(self, code, market, name, sector, start, end):
            FakeClient.calls += 1
            return [bar(code)]
    monkeypatch.setattr(collection, "download_universe", master)
    monkeypatch.setattr(collection, "KISClient", FakeClient)
    first = collection.collect_all(FakeClient(), tmp_path, asof="2026-10-09T22:00:00+09:00")
    second = collection.collect_all(FakeClient(), tmp_path, asof="2026-10-09T22:00:00+09:00", refresh_master=False)
    assert first["status"] == second["status"] == "COMPLETE"
    assert FakeClient.calls == 2
    assert first["adequate_history"] == 0
    assert pd.read_csv(tmp_path / "eligibility.csv").empty
    assert set(pd.read_csv(tmp_path / "daily.csv").code.astype(str)) == {"005930", "0001A0"}


def test_pipeline_preserves_synthetic_flag_and_exports_only_curated_files(tmp_path):
    from bankis_scout.demo import create_demo
    from bankis_scout.pipeline import build_briefing
    data = tmp_path / "data" / "kis_all"
    create_demo(data)
    receipt = {"finished_at": datetime.now(KST).isoformat(), "status": "COMPLETE", "environment": "vps",
               "expected_symbols": 6, "ok": 6, "adequate_history": 6}
    (data / "collection_status.json").write_text(json.dumps(receipt), encoding="utf-8")
    status = build_briefing(tmp_path, data)
    assert status["forward_record"] == {"status": "BLOCKED", "reason": "SYNTHETIC_INPUT"}
    assert status["watch"] == 0
    exported = tmp_path / "reports" / "published"
    run = (exported / "CURRENT").read_text(encoding="utf-8")
    assert {p.name for p in (exported / run).iterdir()} == FEED_FILES
    intel = json.loads((tmp_path / "reports" / "runs" / run / "intelligence.json").read_text(encoding="utf-8"))
    assert intel["sample"] is True


def test_feed_pins_snapshot_and_detects_corrupted_data(report_server):
    url, token, export = report_server
    manifest = requests.get(f"{url}/{token}/manifest.json", timeout=3).json()
    assert manifest["snapshot_id"] == export.name
    assert manifest["account_data_included"] is False
    data_url = f"{url}/{token}/{export.name}/market_daily.csv"
    assert requests.get(data_url, timeout=3).status_code == 200
    (export.parent / "CURRENT").write_text("invalid", encoding="utf-8")
    assert requests.get(data_url, timeout=3).status_code == 200
    (export / "market_daily.csv").write_text("corrupted", encoding="utf-8")
    assert requests.get(data_url, timeout=3).status_code == 503


def test_feed_exports_explicit_market_schema_only(tmp_path):
    bundle = {"daily": pd.DataFrame([{**bar(), "account_number": "private"}], columns=[*DAILY_FIELDS, "account_number"]),
              "index": pd.DataFrame([{"date": "2026-10-08", "market": "KOSPI", "close": 100, "source": "MOCK_TEST"}])}
    for name in ("briefing.md", "intelligence.html", "preopen.html", "status.json"):
        (tmp_path / name).write_text("report", encoding="utf-8")
    write_feed(tmp_path, bundle, {"generated_at": datetime.now(KST).isoformat()})
    csv = (tmp_path / "market_daily.csv").read_text(encoding="utf-8")
    assert "account_number" not in csv and "private" not in csv


def test_feed_verifier_reads_all_files_but_does_not_claim_chatgpt_connection(report_server):
    from bankis_scout.verify_feed import verify
    url, token, _ = report_server
    result = verify(url, token, local=True)
    assert result["status"] == "LOCAL_HTTP_VERIFIED"
    assert len(result["verified_files"]) == 6
    assert result["chatgpt_scheduled_read"] == "NOT_VERIFIED"
    assert result["market_daily_rows"] == 1


def test_feed_verifier_rejects_remote_plaintext_or_embedded_credentials():
    from bankis_scout.verify_feed import verify
    for url in ("http://example.com", "https://user:password@example.com", "https://example.com?token=secret"):
        with pytest.raises(ValueError):
            verify(url, "testtoken" * 5)


def test_installed_runtime_uses_explicit_server_home(monkeypatch, tmp_path):
    from bankis_scout.runtime import project_root
    monkeypatch.setenv("BANKIS_HOME", str(tmp_path))
    assert project_root() == tmp_path.resolve()


def test_recent_session_audit_catches_gap_even_if_row_count_and_latest_are_valid():
    from bankis_scout.quality_audit import audit_recent_sessions
    dates = pd.bdate_range("2026-08-01", periods=30)
    index = pd.DataFrame([{"date": d.date().isoformat(), "market": "KOSPI", "close": 100, "source": "MOCK_TEST"} for d in dates])
    daily = pd.DataFrame([bar(day=d.date().isoformat()) for i, d in enumerate(dates) if i != 10])
    result = audit_recent_sessions({"daily": daily, "index": index}, "2026-10-09T08:00:00+09:00")
    assert result["recent_window_complete"] == 0
    assert result["failed"][0]["reason"] == "MISSING_RECENT_SESSION_BARS"
    assert len(result["failed"][0]["missing_dates"]) == 1


def test_repoll_keeps_first_known_time_but_real_revision_gets_new_time():
    from bankis_scout.pipeline import retain_known_availability
    old = {"id": "PRICE-005930", "value": 5, "fact": "unchanged fact", "available_at": "2026-10-08T16:00:00+09:00"}
    unchanged = {**old, "available_at": "2026-10-09T07:00:00+09:00", "ingested_at": "2026-10-09T07:00:00+09:00"}
    changed = {**old, "value": 6, "available_at": "2026-10-09T07:00:00+09:00"}
    retain_known_availability([unchanged, changed], {"observations": [old]})
    assert unchanged["available_at"] == old["available_at"]
    assert unchanged["ingested_at"] == "2026-10-09T07:00:00+09:00"
    assert changed["available_at"] == "2026-10-09T07:00:00+09:00"
