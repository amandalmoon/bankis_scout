"""Read-only EOD research observations; never grant BankIS contest eligibility.

The registered trading strategy and its frozen prospective evaluation are separate.
A research observation is NOT an approved WATCH candidate or a buy instruction.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from math import isfinite

import pandas as pd

from .engine import screen_bundle
from .quality_audit import audit_recent_sessions
from .settings import parse_asof

_UNKNOWN_ELIGIBILITY = frozenset({
    "ELIGIBILITY_UNVERIFIED",
    "ELIGIBILITY_NOT_KNOWN_AT_ASOF",
    "ELIGIBILITY_STALE",
    "ELIGIBILITY_NO_SOURCE",
})
_UNVERIFIED_FACTS = [
    "Contest trade eligibility and permitted order types",
    "Same-day market warning, halt, rights issue and convertible bond filings",
    "Event catalysts, consensus and counterevidence",
    "Actual KRX/NXT integrated liquidity, order book and execution costs",
]


def _number(value):
    """Return a finite float only; missing features are not zero."""
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if isfinite(result) else None


def research_observations(bundle, asof, *, environment, collection_status, limit=5):
    """Shortlist price/volume observations blocked SOLELY by unknown contest status.

    The full-universe primary screen remains fail-closed. This independent display
    never changes WATCH, the forward snapshots, or the contest eligibility file.
    """
    now = parse_asof(asof)
    result = {
        "schema_version": 1,
        "mode": "EOD_RESEARCH_ONLY_NOT_CONTEST_APPROVED",
        "asof": now.isoformat(),
        "environment": environment,
        "collection_status": collection_status,
        "venue": "KRX_UNADJUSTED",
        "last_session": None,
        "observations": [],
        "diagnostics": {},
        "independent_source_verification": False,
        "contest_eligibility_verified": False,
        "ranking_rule": "positive 5-session stock-minus-market return, relative daily volume, closing location; sort by 5-session relative strength, then volume ratio, then turnover",
        "not_verified": _UNVERIFIED_FACTS,
        "disclaimer": "Research-only, uncalibrated EOD observations; NOT buys, trading approval, live signals or verified profitability.",
    }
    if collection_status != "COMPLETE":
        result["status"] = "NO_RESEARCH_INCOMPLETE_COLLECTION"
        return result
    if environment not in {"vps", "prod"}:
        result["status"] = "NO_RESEARCH_UNVERIFIED_ENVIRONMENT"
        return result
    if not isinstance(limit, int) or not 0 <= limit <= 5:
        raise ValueError("research shortlist limit must be 0..5")
    if not all(key in bundle for key in ("daily", "index", "eligibility")):
        result["status"] = "NO_RESEARCH_INCOMPLETE_INPUT"
        return result
    daily = bundle["daily"]
    if daily.empty or "source" not in daily:
        result["status"] = "NO_RESEARCH_MISSING_DAILY"
        return result
    if daily["source"].astype(str).str.contains("SYNTHETIC", case=False).any():
        result["status"] = "NO_RESEARCH_SYNTHETIC_INPUT"
        return result

    screened = screen_bundle(bundle, now.isoformat())
    audit = audit_recent_sessions(bundle, now.isoformat())
    invalid = {row["code"] for row in audit["failed"]}
    reasons = Counter(r for row in screened["records"] for r in row["reasons"])
    pool = []
    solely_unverified = 0
    for row in screened["records"]:
        flags = set(row["reasons"])
        # A confirmed NOT_CONTEST_ELIGIBLE, RISK_FLAG, invalid data or too-thin
        # turnover must never be reintroduced by the research display.
        if row["status"] != "DATA_BLOCKED" or not flags or not flags.issubset(_UNKNOWN_ELIGIBILITY):
            continue
        if row["code"] in invalid or "EXTENDED_DAILY_MOVE" in row["warnings"]:
            continue
        f = row["features"]
        if row["source_type"] != "KIS:KRX:UNADJUSTED":
            continue
        rs5 = _number(f.get("rs5_pctp"))
        rvol = _number(f.get("rvol_eod"))
        closing = _number(f.get("close_location"))
        turnover = _number(f.get("last_turnover_krw"))
        historical_turnover = _number(f.get("median_turnover20_krw"))
        rs1 = _number(f.get("rs1_pctp"))
        ret1 = _number(f.get("ret1_pct"))
        if any(x is None for x in (rs5, rvol, closing, turnover, historical_turnover, rs1, ret1)):
            continue
        # The primary engine already enforces 30bn KRW last-day and 10bn KRW
        # 20-day-median turnover here. Restate, never weaken those thresholds.
        if turnover < 30_000_000_000 or historical_turnover < 10_000_000_000:
            continue
        solely_unverified += 1
        # These thresholds are for displaying worthwhile research, not for
        # predicting profitability or verifying an entry.
        if rs5 <= 0 or rvol < 1.2 or closing < 0.45:
            continue
        pool.append({
            "code": row["code"],
            "name": row["name"],
            "market": row["market"],
            "sector": row["sector"],
            "last_date": f["last_date"],
            "last_close": f["last_close"],
            "last_turnover_krw": turnover,
            "median_turnover20_krw": historical_turnover,
            "rs1_pctp": rs1,
            "rs5_pctp": rs5,
            "rvol_eod": rvol,
            "ret1_pct": ret1,
            "close_location": closing,
            "source": row["source_type"],
            "original_engine_status": "DATA_BLOCKED",
            "approval_gate": sorted(flags),
            "research_only": True,
        })
    pool.sort(key=lambda r: (-r["rs5_pctp"], -r["rvol_eod"], -r["last_turnover_krw"], r["code"]))
    result["observations"] = [{**row, "research_rank": i + 1} for i, row in enumerate(pool[:limit])]
    result["diagnostics"] = {
        "input_symbols": screened["coverage"]["input_symbols"],
        "strict_watch": screened["coverage"]["watch"],
        "eligibility_unverified": sum(reasons[r] for r in _UNKNOWN_ELIGIBILITY),
        "price_liquidity_gate_passed_eligibility_unknown": solely_unverified,
        "research_signal_pool": len(pool),
        "displayed": len(result["observations"]),
        "data_audit_failed": len(invalid),
    }
    result["last_session"] = max((r["last_date"] for r in result["observations"]), default=None)
    result["status"] = "OBSERVATIONS_AVAILABLE" if pool else "NO_RESEARCH_SIGNAL"
    return result
