"""GitHub delivery: public execution receipt, authenticated report artifact."""
import argparse
import base64
import json
import os
import re
import secrets
import shutil
import threading
from datetime import datetime
from http.server import ThreadingHTTPServer
from pathlib import Path

import requests

from .briefing_server import handler_class
from .collect_all import atomic_json
from .runtime import project_root
from .settings import KST
from .verify_feed import verify


def restore(root):
    state = root / "data/cloud_state"
    if (state / "previous.json").exists() and (state / "previous_id").exists():
        stamp = (state / "previous_id").read_text().strip()
        if not re.fullmatch(r"[0-9]{8}T[0-9]{12}", stamp):
            raise ValueError("Invalid cached snapshot")
        target = root / "reports/runs" / stamp
        target.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(state / "previous.json", target / "intelligence.json")
        (root / "reports/published").mkdir(parents=True, exist_ok=True)
        (root / "reports/published/CURRENT").write_text(stamp, encoding="utf-8")


def prepare(root):
    folder = root / "reports/published"
    token = secrets.token_urlsafe(32)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_class(folder, token))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        verified = verify(f"http://127.0.0.1:{server.server_port}", token, local=True)
    finally:
        server.shutdown()
        server.server_close()
        worker.join()
    stamp = verified["snapshot_id"]
    intelligence = json.loads((root / "reports/runs" / stamp / "intelligence.json").read_text(encoding="utf-8"))
    if intelligence.get("sample") is not False:
        raise ValueError("Synthetic or unknown intelligence provenance")
    out = root / "cloud-export"
    if out.exists():
        raise ValueError("Refuse to overwrite prepared export")
    shutil.copytree(folder / stamp, out)
    for name in ("intelligence.json", "data_quality.json", "performance.json"):
        shutil.copyfile(root / "reports/runs" / stamp / name, out / name)
    atomic_json(out / "delivery_check.json", verified)
    ledger = root / "data/forward_validation"
    if (ledger / "plan.json").exists():
        (out / "forward_validation").mkdir()
        shutil.copyfile(ledger / "plan.json", out / "forward_validation/plan.json")
        if (ledger / "snapshots").exists():
            shutil.copytree(ledger / "snapshots", out / "forward_validation/snapshots")
    state = root / "data/cloud_state"
    state.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(root / "reports/runs" / stamp / "intelligence.json", state / "previous.json")
    (state / "previous_id").write_text(stamp, encoding="utf-8")
    return verified


def publish_receipt(root, status):
    repo = os.environ["GITHUB_REPOSITORY"]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ValueError("Invalid repository")
    run_id = int(os.environ["GITHUB_RUN_ID"])
    receipt = {"schema_version": 1, "status": status, "checked_at": datetime.now(KST).isoformat(),
               "repository": repo, "run_id": run_id, "run_attempt": int(os.getenv("GITHUB_RUN_ATTEMPT", "1")),
               "run_url": f"https://github.com/{repo}/actions/runs/{run_id}",
               "artifact_id": None, "artifact_name": f"bankis-report-{run_id}-{os.getenv('GITHUB_RUN_ATTEMPT', '1')}",
               "artifact_requires_github_access": True, "account_data_included": False}
    if status == "READY":
        artifact_id = int(os.environ["REPORT_ARTIFACT_ID"])
        if artifact_id <= 0:
            raise ValueError("Missing artifact")
        manifest = json.loads((root / "cloud-export/manifest.json").read_text(encoding="utf-8"))
        receipt.update(artifact_id=artifact_id, snapshot_id=manifest["snapshot_id"],
                       generated_at=manifest["generated_at"], collection_finished_at=manifest["collection_finished_at"],
                       environment=manifest["environment"], collection_status=manifest["collection_status"],
                       received_symbols=manifest["received_symbols"], expected_symbols=manifest["expected_symbols"])
    session = requests.Session()
    session.headers.update({"Authorization": "Bearer " + os.environ["GITHUB_TOKEN"],
                            "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
    endpoint = f"https://api.github.com/repos/{repo}/contents/delivery/latest.json"
    existing = session.get(endpoint, timeout=30, allow_redirects=False)
    if existing.status_code not in (200, 404):
        raise ValueError("Receipt read denied")
    body = {"message": f"Update briefing delivery receipt: {status} [skip ci]",
            "content": base64.b64encode(json.dumps(receipt, ensure_ascii=False, indent=2).encode()).decode(),
            "branch": os.environ["GITHUB_REF_NAME"]}
    if existing.status_code == 200:
        body["sha"] = existing.json()["sha"]
    response = session.put(endpoint, json=body, timeout=30, allow_redirects=False)
    if response.status_code not in (200, 201):
        raise ValueError("Receipt write denied")
    print(json.dumps(receipt, ensure_ascii=False))
    return receipt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("restore", "prepare", "running", "ready", "failed"))
    args = parser.parse_args()
    root = project_root()
    try:
        if args.command == "restore":
            restore(root)
        elif args.command == "prepare":
            print(json.dumps(prepare(root), ensure_ascii=False))
        else:
            publish_receipt(root, args.command.upper())
        return 0
    except Exception as exc:
        # Exception messages can carry URLs or tokens. Never print them.
        print(json.dumps({"status": "FAILED", "error_type": type(exc).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
