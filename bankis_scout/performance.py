"""Forward records and paired paper outcomes; no historical or causal alpha claim."""
import hashlib
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from .settings import KST, Settings


def strategy_hash():
    root = Path(__file__).parent
    digest = hashlib.sha256()
    for name in ("engine.py", "settings.py", "data.py", "performance.py", "quality_audit.py",
                 "pipeline.py", "kis.py", "universe.py", "collect_all.py"):
        digest.update((root / name).read_bytes())
    return digest.hexdigest()


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def save_exclusive(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as file:
        json.dump(value, file, ensure_ascii=False, indent=2)


def register_plan(folder):
    folder = Path(folder)
    path = folder / "plan.json"
    if not path.exists():
        save_exclusive(path, {"registered_at": datetime.now(KST).isoformat(), "strategy_hash": strategy_hash(),
                             "settings": asdict(Settings()), "top_n": 3, "hold_sessions": 1,
                             "entry_rule": "Same session opening price after pre-09:00 record",
                             "exit_rule": "Same session closing price", "baseline": "Top trading value from identical risk-cleared eligible pool",
                             "cost_scenarios_bps": [10, 33, 60], "minimum_paired_sessions": 60,
                             "costs_verified": False, "actual_fill_model_verified": False,
                             "primary_metric": "Mean daily equal-weight selected minus turnover-baseline gross return",
                             "limits": ["Local files can be modified externally; this is not an independent audited registry.",
                                        "Paper close/open prices are not executable fill guarantees.",
                                        "No inference about a manager's PnL without decision and transaction records."]})
    return json.loads(path.read_text(encoding="utf-8"))


def freeze_snapshot(report, collection, folder, *, now=None):
    now = (now or datetime.now(KST)).astimezone(KST)
    plan = register_plan(folder)
    if strategy_hash() != plan["strategy_hash"]:
        return {"status": "BLOCKED", "reason": "STRATEGY_CHANGED_AFTER_REGISTRATION"}
    if now.weekday() >= 5 or now.hour >= 9:
        return {"status": "NO_FORWARD_RECORD", "reason": "OUTSIDE_PREOPEN_WEEKDAY_WINDOW"}
    if collection.get("status") != "COMPLETE":
        return {"status": "BLOCKED", "reason": "INCOMPLETE_UNIVERSE_COLLECTION"}
    if datetime.fromisoformat(collection["finished_at"]) > now:
        return {"status": "BLOCKED", "reason": "COLLECTION_NOT_KNOWN_AT_RECORD_TIME"}
    if datetime.fromisoformat(report["asof"]) > now:
        return {"status": "BLOCKED", "reason": "FUTURE_REPORT"}
    pool = [r for r in report["records"] if r["status"] == "WATCH" or
            (r["status"] == "REJECTED" and r["reasons"] == ["SCORE_BELOW_WATCH_THRESHOLD"])]
    for row in pool:
        if row.get("features", {}).get("last_date", "9999") >= now.date().isoformat():
            return {"status": "BLOCKED", "reason": "SAME_DAY_OR_UNKNOWN_BAR"}
    selected = sorted((r for r in pool if r["status"] == "WATCH"), key=lambda r: (-r["score"], r["code"]))[:plan["top_n"]]
    baseline = sorted(pool, key=lambda r: (-r["features"]["last_turnover_krw"], r["code"]))[:plan["top_n"]]
    value = {"recorded_at": now.isoformat(), "entry_session": now.date().isoformat(),
             "plan_hash": canonical_hash(plan), "strategy_hash": strategy_hash(),
             "collection_hash": canonical_hash(collection), "eligible_count": len(pool),
             "selected": [r["code"] for r in selected], "baseline": [r["code"] for r in baseline],
             "status": "RECORDED" if selected and baseline else "NO_TESTABLE_SELECTION"}
    value["checksum"] = canonical_hash(value)
    path = Path(folder) / "snapshots" / (now.date().isoformat() + ".json")
    try:
        save_exclusive(path, value)
    except FileExistsError:
        return {"status": "EXISTING_RECORD_PRESERVED"}
    return {"status": value["status"], "selected_count": len(selected), "baseline_count": len(baseline)}


def evaluate_forward(bundle, folder):
    folder = Path(folder)
    plan = register_plan(folder)
    now = datetime.now(KST)
    result = {"status": "NOT_MEASURABLE", "independent_profitability_verified": False,
              "plan_hash": canonical_hash(plan), "paired_sessions": [], "excluded": [],
              "reason": "No matured, pre-recorded selections and matching baseline outcomes",
              "historical_validation": "BLOCKED: historical constituent, eligibility and ingestion ledgers absent",
              "actual_account_performance": "NOT_MEASURABLE: verified costs, cash flows and decision-linked fills required",
              "limits": plan["limits"]}
    daily = bundle["daily"].copy()
    daily["code"] = daily.code.astype(str).str.zfill(6)
    index_dates = set(bundle["index"]["date"].astype(str))
    for path in sorted((folder / "snapshots").glob("*.json")):
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        checksum = snapshot.pop("checksum", None)
        day = snapshot["entry_session"]
        if checksum != canonical_hash(snapshot) or snapshot["plan_hash"] != canonical_hash(plan):
            result["excluded"].append({"date": day, "reason": "RECORD_INTEGRITY_OR_PLAN_MISMATCH"})
            continue
        recorded = datetime.fromisoformat(snapshot["recorded_at"]).astimezone(KST)
        if recorded.date().isoformat() != day or recorded.hour >= 9:
            result["excluded"].append({"date": day, "reason": "LATE_OR_BACKDATED_RECORD"})
            continue
        if day >= now.date().isoformat() or day not in index_dates:
            result["excluded"].append({"date": day, "reason": "OUTCOME_NOT_MATURE_OR_NON_SESSION"})
            continue
        returns = {}
        for group in ("selected", "baseline"):
            values = []
            for code in snapshot[group]:
                frame = daily[(daily.code == code) & (daily.date.astype(str) == day)]
                if len(frame) != 1:
                    values = []
                    break
                row = frame.iloc[0]
                opening, closing = float(row.open), float(row.close)
                if not np.isfinite(opening) or not np.isfinite(closing) or min(opening, closing) <= 0:
                    values = []
                    break
                values.append((closing / opening - 1) * 100)
            if values:
                returns[group] = float(np.mean(values))
        if len(returns) != 2:
            result["excluded"].append({"date": day, "reason": "MISSING_SELECTION_OR_OUTCOME"})
            continue
        result["paired_sessions"].append({"date": day, **returns, "difference_pct": returns["selected"] - returns["baseline"]})
    pairs = result["paired_sessions"]
    if pairs:
        diffs = np.array([p["difference_pct"] for p in pairs])
        result["status"] = "EXPLORATORY_PAPER_RESULTS"
        result["reason"] = "Hypothetical costs and paper fills; no verified profitability claim"
        result["summary"] = {"n": len(pairs), "mean_difference_pct": float(diffs.mean()),
                              "minimum_sample_reached": len(pairs) >= plan["minimum_paired_sessions"],
                              "scenarios": [{"cost_bps": c, "selected_mean_net_pct": float(np.mean([p["selected"] for p in pairs])) - c / 100,
                                             "baseline_mean_net_pct": float(np.mean([p["baseline"] for p in pairs])) - c / 100}
                                            for c in plan["cost_scenarios_bps"]]}
        if len(pairs) >= plan["minimum_paired_sessions"]:
            # Circular 5-session block bootstrap reduces false precision from serial dependence.
            rng = np.random.default_rng(20261009)
            means = []
            for _ in range(2000):
                starts = rng.integers(0, len(diffs), size=(len(diffs) + 4) // 5)
                sample = np.concatenate([diffs[(np.arange(5) + s) % len(diffs)] for s in starts])[:len(diffs)]
                means.append(sample.mean())
            result["summary"]["paired_block_bootstrap_95pct_interval"] = np.percentile(means, [2.5, 97.5]).tolist()
    return result
