"""Deterministic market briefing; account data is never part of the published export."""
import argparse
import json
import os
import shutil
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from .collect_all import collect_all, atomic_json
from .data import load_bundle
from .engine import screen_bundle
from .intel_adapter import describe_daily_bundle
from .intel_report import write_intelligence
from .intelligence import evaluate_intelligence, evaluate_detection_kpis
from .kis import KISClient
from .performance import freeze_snapshot, evaluate_forward
from .report import write_artifacts
from .settings import KST
from .runtime import project_root
from .quality_audit import audit_recent_sessions
from .feed import write_feed, REPORT_FILES


def retain_known_availability(observations, previous):
    """A later poll is not a new publication when the evidence is unchanged."""
    old_by_id = {r["id"]: r for r in (previous or {}).get("observations", [])}
    fields = ("entity", "category", "metric", "value", "unit", "fact", "observed_at",
              "source_url", "source_name", "source_class", "venue")
    for row in observations:
        old = old_by_id.get(row["id"])
        if old and all(row.get(key) == old.get(key) for key in fields):
            row["available_at"] = old["available_at"]


def build_briefing(root, data_dir):
    root, data_dir = Path(root), Path(data_dir)
    now = datetime.now(KST)
    if (data_dir / "collection.lock").exists():
        raise ValueError("Collection locked; refuse inconsistent data")
    receipt = json.loads((data_dir / "collection_status.json").read_text(encoding="utf-8"))
    if receipt["status"] == "RUNNING":
        raise ValueError("Collection still running; refuse inconsistent data")
    received = datetime.fromisoformat(receipt["finished_at"])
    if received > now or (now - received).total_seconds() > 24 * 3600:
        raise ValueError("Future or stale collection receipt")
    stamp = now.strftime("%Y%m%dT%H%M%S%f")
    out = root / "reports" / "runs" / stamp
    out.mkdir(parents=True, exist_ok=False)
    bundle = load_bundle(data_dir)
    synthetic = bundle["daily"]["source"].astype(str).str.contains("SYNTHETIC", case=False).any()
    audit = audit_recent_sessions(bundle, now.isoformat())
    blocked_codes = {r["code"] for r in audit["failed"]}
    atomic_json(out / "data_quality.json", audit)
    observations, exclusions = describe_daily_bundle(data_dir, now.isoformat(),
        source_url="https://apiportal.koreainvestment.com/", available_at=received.isoformat(),
        ingested_at=received.isoformat(), max_items=12, blocked_codes=blocked_codes)
    environment = receipt["environment"]
    for row in observations:
        row["source_name"] = f"KIS {environment} API 직접 수신 / 독립 대조 전 / 공개시각은 수신시각의 보수적 대용치"
        row["source_class"] = "PRIMARY"
    published = root / "reports" / "published"
    previous = None
    if (published / "CURRENT").exists():
        old = (published / "CURRENT").read_text(encoding="utf-8").strip()
        if old and Path(old).name == old:
            path = root / "reports" / "runs" / old / "intelligence.json"
            if path.exists():
                previous = json.loads(path.read_text(encoding="utf-8"))
    retain_known_availability(observations, previous)
    intel = evaluate_intelligence(observations, [], now.isoformat(), previous=previous, sample=bool(synthetic))
    for row in intel["observations"]:
        row["issues"].append("PUBLICATION_TIMESTAMP_NOT_INDEPENDENTLY_VERIFIED")
    intel["adapter_exclusions"] = exclusions
    intel["collection_coverage"] = {k: receipt[k] for k in ("expected_symbols", "ok", "adequate_history", "status", "environment")}
    intel["collection_limits"] = ["Current KIS equity master only; historical constituent completeness unverified.",
                                    "Price/volume observations only; disclosures, consensus and calendar not collected."]
    scout = screen_bundle(bundle, now.isoformat())
    for row in scout["records"]:
        if row["code"] in blocked_codes:
            row["status"], row["score"], row["components"] = "DATA_BLOCKED", None, {}
            row["reasons"].append("MISSING_RECENT_SESSION_BARS")
    # A partial market scan cannot assert an exhaustive ranking or emit a watchlist.
    if receipt["status"] != "COMPLETE" or synthetic:
        for row in scout["records"]:
            row["status"] = "DATA_BLOCKED"
            row["score"] = None
            row["components"] = {}
            row["reasons"].append("SYNTHETIC_INPUT" if synthetic else "INCOMPLETE_UNIVERSE_COLLECTION")
        scout["coverage"]["watch"] = 0
        scout["coverage"]["rejected"] = 0
        scout["coverage"]["data_blocked"] = len(scout["records"])
    else:
        for key, status_name in (("watch", "WATCH"), ("rejected", "REJECTED"), ("data_blocked", "DATA_BLOCKED")):
            scout["coverage"][key] = sum(r["status"] == status_name for r in scout["records"])
    write_artifacts(scout, out)
    write_intelligence(intel, out, kpis=evaluate_detection_kpis(intel), bankis_link="preopen.html")
    ledger = root / "data" / "forward_validation"
    forward_record = ({"status": "BLOCKED", "reason": "SYNTHETIC_INPUT"} if synthetic else
                      freeze_snapshot(scout, receipt, ledger, now=now))
    performance = evaluate_forward(bundle, ledger)
    atomic_json(out / "performance.json", performance)
    brief = ["# 시장정보·뱅키스 브리핑", "", f"생성시각: {now.isoformat()}",
             "합성 입력 포함: 실제 시장 보고서가 아닙니다." if synthetic else "KIS 수신 데이터 기반 / 원거래소 독립 대조 전",
             f"데이터 서버: {environment} / 수집상태: {receipt['status']}",
             f"KIS 현재 주식목록 {receipt['expected_symbols']}종목 중 {receipt['ok']}종목 수신; 분석용 이력·최신일 충족 {receipt['adequate_history']}종목.",
             f"수신 지수 거래일과 대조한 최근 25거래일 자료 충족: {audit['recent_window_complete']}종목. 독립 거래소 달력 인증은 미완료.",
             "계좌번호·잔고·체결 원장은 이 보고서에 포함하지 않습니다.", "",
             "## 1부 전략 중립 시장정보", "가격·거래량 관찰에 한정. 공시·실적 예상치·예정 사건은 아직 미수집.", "",
             (out / "intelligence.md").read_text(encoding="utf-8"), "",
             "## 2부 뱅키스 관찰종목 부록", ""]
    watch = [r for r in scout["records"] if r["status"] == "WATCH"]
    if not watch:
        brief.append("검증된 관찰 후보 없음. 대회 거래 자격 미확인 등 차단 사유를 유지합니다.")
    for row in sorted(watch, key=lambda r: (-r["score"], r["code"]))[:3]:
        brief.append(f"- {row['name']} ({row['code']}): 연구용 관찰 후보. 매수 지시·독립 검증된 상승확률이 아닙니다.")
    brief.extend([f"차단 종목: {scout['coverage']['data_blocked']}; 후보: {len(watch)}", "",
                  "## 성과 및 연결 상태", f"사전 기록: {forward_record['status']}",
                  f"성과: {performance['status']}. 실제 수익성의 독립 입증: 미완료.",
                  "실전 서버·계좌·ChatGPT 예약 연결은 별도 연결 영수증과 실제 실행 결과로 확인해야 합니다."])
    (out / "briefing.md").write_text("\n".join(brief), encoding="utf-8")
    status = {"generated_at": now.isoformat(), "collection_finished_at": receipt["finished_at"],
              "environment": environment, "collection_status": receipt["status"],
              "expected_symbols": receipt["expected_symbols"], "received_symbols": receipt["ok"],
              "watch": len(watch), "forward_record": forward_record, "performance_status": performance["status"],
              "recent_window_complete": audit["recent_window_complete"],
              "source_content_independently_verified": False}
    atomic_json(out / "status.json", status)
    # Only these curated artifacts cross the server boundary.
    export = published / stamp
    export.mkdir(parents=True, exist_ok=False)
    for filename in REPORT_FILES:
        shutil.copyfile(out / filename, export / filename)
    write_feed(export, bundle, status)
    pointer = published / "CURRENT.tmp"
    pointer.write_text(stamp, encoding="utf-8")
    os.replace(pointer, published / "CURRENT")
    return status


def main():
    root = project_root()
    parser = argparse.ArgumentParser()
    parser.add_argument("--collect", action="store_true")
    parser.add_argument("--env-file", default=str(root / ".env"))
    parser.add_argument("--data-dir", default=str(root / "data" / "kis_all"))
    args = parser.parse_args()
    load_dotenv(args.env_file, override=False)
    reports = root / "reports"
    reports.mkdir(exist_ok=True)
    lock = reports / "pipeline.lock"
    try:
        with lock.open("x") as file:
            file.write(str(os.getpid()))
    except FileExistsError:
        print('{"status":"BLOCKED","reason":"PIPELINE_LOCK_EXISTS"}')
        return 2
    try:
        if args.collect:
            collect_all(KISClient(), args.data_dir)
        result = build_briefing(root, args.data_dir)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        atomic_json(reports / "pipeline_failure.json", {"failed_at": datetime.now(KST).isoformat(), "error_type": type(exc).__name__})
        print(json.dumps({"status": "FAILED", "error_type": type(exc).__name__}))
        return 1
    finally:
        lock.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
