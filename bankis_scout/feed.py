"""Publish a reproducible report and market-data snapshot, never account files."""
import hashlib
import json
from pathlib import Path

from .data import DAILY_FIELDS, INDEX_FIELDS

REPORT_FILES = ("briefing.md", "intelligence.html", "preopen.html", "status.json")
DATA_FILES = {"market_daily.csv": ("daily", DAILY_FIELDS),
              "index_daily.csv": ("index", INDEX_FIELDS)}
FEED_FILES = frozenset((*REPORT_FILES, *DATA_FILES, "manifest.json"))


def write_feed(export, bundle, status):
    export = Path(export)
    for name, (key, fields) in DATA_FILES.items():
        # An explicit schema prevents future account/custom columns leaking out.
        bundle[key].loc[:, fields].to_csv(export / name, index=False, encoding="utf-8")
    files = {}
    for name in (*REPORT_FILES, *DATA_FILES):
        payload = (export / name).read_bytes()
        files[name] = {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
    manifest = {"schema_version": 1, "snapshot_id": export.name, **status,
                "files": files, "market_daily_rows": len(bundle["daily"]),
                "index_daily_rows": len(bundle["index"]),
                "account_data_included": False,
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
