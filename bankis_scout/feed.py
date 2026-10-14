"""Publish a reproducible report and market-data snapshot, never account files."""
import hashlib
import json

from .research import research_observations
from pathlib import Path

from .data import DAILY_FIELDS, INDEX_FIELDS

REPORT_FILES = ("briefing.md", "intelligence.html", "preopen.html", "status.json", "research_shortlist.json")
DATA_FILES = {"market_daily.csv": ("daily", DAILY_FIELDS),
              "index_daily.csv": ("index", INDEX_FIELDS)}
FEED_FILES = frozenset((*REPORT_FILES, *DATA_FILES, "manifest.json"))


def write_feed(export, bundle, status):
    export = Path(export)
    for name, (key, fields) in DATA_FILES.items():
        # An explicit schema prevents future account/custom columns leaking out.
        bundle[key].loc[:, fields].to_csv(export / name, index=False, encoding="utf-8")
    # Separate observational research from the frozen, fail-closed trading screen.
    # This overlay does not modify the WATCH output or forward validation plan.
    try:
        research = research_observations(bundle, status["generated_at"],
            environment=status.get("environment", "unknown"),
            collection_status=status.get("collection_status", "UNKNOWN"))
    except Exception as exc:
        # Supplemental research cannot turn a complete v2 collection into a
        # fabricated watchlist, nor suppress the verified market report.
        research = {"schema_version": 1, "status": "NO_RESEARCH_CALCULATION_FAILED",
                    "error_type": type(exc).__name__, "observations": [],
                    "mode": "EOD_RESEARCH_ONLY_NOT_CONTEST_APPROVED",
                    "disclaimer": "Do not infer an eligible trading candidate."}
    (export / "research_shortlist.json").write_text(
        json.dumps(research, ensure_ascii=False, indent=2), encoding="utf-8")

    markdown = (export / "briefing.md").read_text(encoding="utf-8")
    diagnostic = research.get("diagnostics", {})
    note = ["### 별도: 데이터 기반 연구 관찰목록 (매수 승인 아님)",
            "기존 검증된 WATCH 목록과 분리합니다. KIS 일별 KRX 시세의 상대강도·거래량을 관찰한 것이며,",
            "대회 거래가능 여부·기업 공시·시장경보·반대 증거·실시간 체결비용은 검증되지 않았습니다.",
            f"기존 WATCH: {status.get('watch', '미확인')}종목 / "
            f"추가 관찰목록: {len(research.get('observations', []))}종목 / "
            f"관찰 상태: {research['status']}.",
            f"거래자격 미확인: {diagnostic.get('eligibility_unverified', '미확인')}종목; "
            f"기존 유동성·데이터 조건 통과 후 자격만 미확인: "
            f"{diagnostic.get('price_liquidity_gate_passed_eligibility_unknown', '미확인')}종목.",
            "이 목록은 이전 거래일 시세만 사용하고 상승확률·수익성·대회 매매 적격성을 주장하지 않습니다."]
    for item in research.get("observations", []):
        name = str(item["name"]).replace("|", "/").replace("\n", " ")
        note.append(
            f"- **관찰 {item['research_rank']}: {name} ({item['code']})** "
            f"[{item['last_date']} / {item['market']} KRX]: "
            f"5일 시장초과 {item['rs5_pctp']:+.2f}%p, "
            f"거래량/과거20일중앙값 {item['rvol_eod']:.2f}배, "
            f"일별 거래대금 {item['last_turnover_krw']/1e8:,.1f}억원. "
            "대회자격·공시·호가 미확인. 주문 근거가 아님.")
    marker = "\n## 성과 및 연결 상태"
    if marker in markdown:
        markdown = markdown.replace(marker, "\n" + "\n".join(note) + "\n" + marker, 1)
    else:
        markdown += "\n\n" + "\n".join(note) + "\n"
    (export / "briefing.md").write_text(markdown, encoding="utf-8")
    try:
        exported_status = json.loads((export / "status.json").read_text(encoding="utf-8"))
        if isinstance(exported_status, dict):
            exported_status["research_observation_count"] = len(research.get("observations", []))
            exported_status["research_observation_status"] = research["status"]
            (export / "status.json").write_text(
                json.dumps(exported_status, ensure_ascii=False, indent=2), encoding="utf-8")
    except (ValueError, OSError):
        pass

    files = {}
    for name in (*REPORT_FILES, *DATA_FILES):
        payload = (export / name).read_bytes()
        files[name] = {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
    manifest = {"schema_version": 1, "snapshot_id": export.name, **status,
                "files": files, "market_daily_rows": len(bundle["daily"]),
                "index_daily_rows": len(bundle["index"]),
                "account_data_included": False,
                "research_observation_count": len(research.get("observations", [])),
                "research_observation_status": research["status"],
                "limits": ["Daily OHLCV, not live intraday quotes.",
                           "Receipt and local hashes are not independent source verification."]}
    (export / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def read_verified_artifact(export, name):
    if name not in FEED_FILES:
        raise ValueError("Artifact not allowed")
    export = Path(export)
    payload = (export / name).read_bytes()
    if name != "manifest.json":
        manifest = json.loads((export / "manifest.json").read_text(encoding="utf-8"))
        expected = manifest["files"][name]
        if len(payload) != expected["bytes"] or hashlib.sha256(payload).hexdigest() != expected["sha256"]:
            raise ValueError("Artifact integrity mismatch")
    return payload
