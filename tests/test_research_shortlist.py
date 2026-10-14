"""Research observations must never bypass trading eligibility or data-quality gates."""
import hashlib
import json

import pandas as pd

from bankis_scout.engine import screen_bundle
from bankis_scout.feed import write_feed
from bankis_scout.research import research_observations

ASOF = "2026-10-15T08:00:00+09:00"


def bundle():
    days = pd.bdate_range(end="2026-10-14", periods=26)
    bars = []
    for i, d in enumerate(days):
        close = 100_000 + i * 1000
        volume = 1_000_000 if i < 25 else 4_000_000
        bars.append({
            "date": d.strftime("%Y-%m-%d"), "code": "111111",
            "name": "관찰용A", "market": "KOSPI", "sector": "TEST",
            "open": close - 600, "high": close + 1000, "low": close - 1400,
            "close": close, "volume": volume,
            "turnover_krw": close * volume, "source": "KIS:KRX:UNADJUSTED",
        })
    index = [{"date": d.strftime("%Y-%m-%d"), "market": "KOSPI",
              "close": 1000 + i * 2, "source": "KIS:KRX:INDEX"}
             for i, d in enumerate(days)]
    return {
        "daily": pd.DataFrame(bars),
        "index": pd.DataFrame(index),
        "eligibility": pd.DataFrame(columns=[
            "code", "eligible", "risk_level", "checked_at", "source_url"]),
        "events": pd.DataFrame(columns=[
            "code", "published_at", "event_type", "title", "source_url",
            "verified", "materiality"]),
    }


def inspect(b, status="COMPLETE"):
    return research_observations(
        b, ASOF, environment="vps", collection_status=status)


def test_unknown_eligibility_keeps_watch_zero_but_generates_research_observation():
    b = bundle()
    original = screen_bundle(b, ASOF)
    assert original["coverage"]["watch"] == 0
    assert original["records"][0]["status"] == "DATA_BLOCKED"
    assert original["records"][0]["score"] is None
    report = inspect(b)
    assert report["status"] == "OBSERVATIONS_AVAILABLE"
    assert report["diagnostics"]["strict_watch"] == 0
    assert report["diagnostics"]["eligibility_unverified"] == 1
    assert report["diagnostics"]["price_liquidity_gate_passed_eligibility_unknown"] == 1
    assert len(report["observations"]) == 1
    row = report["observations"][0]
    assert row["code"] == "111111"
    assert row["original_engine_status"] == "DATA_BLOCKED"
    assert row["approval_gate"] == ["ELIGIBILITY_UNVERIFIED"]
    assert row["research_only"] is True
    assert row["last_date"] == "2026-10-14"
    assert row["rs5_pctp"] > 0
    assert row["rvol_eod"] > 1.2
    assert report["independent_source_verification"] is False
    assert report["contest_eligibility_verified"] is False


def test_known_ineligible_or_disclosure_risk_never_becomes_research_candidate():
    b = bundle()
    b["eligibility"] = pd.DataFrame([{
        "code": "111111", "eligible": False, "risk_level": "HALT",
        "checked_at": "2026-10-14T17:00:00+09:00",
        "source_url": "https://example.com/official-rule",
    }])
    assert inspect(b)["observations"] == []
    b = bundle()
    b["events"] = pd.DataFrame([{
        "code": "111111", "published_at": "2026-10-14T16:00:00+09:00",
        "event_type": "corporate", "title": "유상증자 검토",
        "source_url": "https://example.com/disclosure",
        "verified": True, "materiality": 0,
    }])
    assert inspect(b)["observations"] == []


def test_session_gap_synthetic_partial_and_unknown_source_do_not_emit_candidates():
    b = bundle()
    b["daily"] = b["daily"].drop(index=[3])
    assert inspect(b)["observations"] == []
    b = bundle()
    b["daily"].loc[0, "source"] = "SYNTHETIC:DEMO"
    assert inspect(b)["status"] == "NO_RESEARCH_SYNTHETIC_INPUT"
    b = bundle()
    assert inspect(b, "PARTIAL")["observations"] == []
    b = bundle()
    b["daily"]["source"] = "MOCK_TEST"
    assert inspect(b)["observations"] == []


def test_future_same_day_bar_cannot_change_preopen_research_selection():
    b = bundle()
    expected = inspect(b)["observations"]
    last = b["daily"].iloc[-1].to_dict()
    last.update(date="2026-10-15", open=1000, high=10_000_000, low=1000,
                close=10_000_000, volume=1_000_000_000, turnover_krw=1e15)
    b["daily"] = pd.concat([b["daily"], pd.DataFrame([last])], ignore_index=True)
    assert inspect(b)["observations"] == expected


def test_authenticated_feed_exposes_separate_research_json_and_preserves_primary_zero(tmp_path):
    b = bundle()
    b["daily"]["account_number"] = "DO-NOT-EXPORT"
    for f in ("briefing.md", "intelligence.html", "preopen.html"):
        (tmp_path / f).write_text("## 2부 뱅키스 관찰종목 부록\n후보 없음\n## 성과 및 연결 상태\n", encoding="utf-8")
    (tmp_path / "status.json").write_text(json.dumps({
        "generated_at": ASOF, "watch": 0, "environment": "vps",
        "collection_status": "COMPLETE"}), encoding="utf-8")
    meta = {"generated_at": ASOF, "watch": 0,
            "environment": "vps", "collection_status": "COMPLETE"}
    manifest = write_feed(tmp_path, b, meta)
    notes = json.loads((tmp_path / "research_shortlist.json").read_text(encoding="utf-8"))
    status = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    assert status["watch"] == 0
    assert status["research_observation_count"] == 1
    assert notes["observations"][0]["approval_gate"] == ["ELIGIBILITY_UNVERIFIED"]
    assert manifest["research_observation_count"] == 1
    assert "DATA_BLOCKED" not in (tmp_path / "briefing.md").read_text(encoding="utf-8")  # only research commentary
    assert "매수 승인 아님" in (tmp_path / "briefing.md").read_text(encoding="utf-8")
    for name, expected in manifest["files"].items():
        value = (tmp_path / name).read_bytes()
        assert len(value) == expected["bytes"]
        assert hashlib.sha256(value).hexdigest() == expected["sha256"]
        assert b"DO-NOT-EXPORT" not in value
