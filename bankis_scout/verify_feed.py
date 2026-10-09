"""Read back every exported file; distinguish local HTTP from ChatGPT access."""
import argparse
import hashlib
import json
import os
import threading
from datetime import datetime
from http.server import ThreadingHTTPServer
from urllib.parse import urlsplit

import requests
from dotenv import load_dotenv

from .briefing_server import handler_class
from .collect_all import atomic_json
from .feed import REPORT_FILES, DATA_FILES
from .runtime import project_root
from .settings import KST


def verify(base_url, token, *, local=False):
    parsed = urlsplit(base_url)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Base URL must not contain credentials or a query")
    if parsed.scheme != "https" and not (local and parsed.scheme == "http" and parsed.hostname == "127.0.0.1"):
        raise ValueError("Remote feed requires HTTPS")
    base = base_url.rstrip("/") + "/" + token
    with requests.Session() as session:
        response = session.get(base + "/manifest.json", timeout=30, allow_redirects=False)
        if response.status_code != 200:
            raise ValueError("Manifest unavailable or redirect refused")
        manifest = response.json()
        now = datetime.now(KST)
        generated = datetime.fromisoformat(manifest["generated_at"])
        received = datetime.fromisoformat(manifest["collection_finished_at"])
        if generated.tzinfo is None or received.tzinfo is None:
            raise ValueError("Missing timezone")
        if generated.astimezone(KST).date() != now.date() or not received <= generated <= now:
            raise ValueError("Stale or future snapshot")
        if (generated - received).total_seconds() > 86400 or manifest["account_data_included"] is not False:
            raise ValueError("Invalid collection age or export scope")
        snapshot = manifest["snapshot_id"]
        import re
        if not re.fullmatch(r"[0-9]{8}T[0-9]{12}", snapshot):
            raise ValueError("Invalid snapshot")
        required = set(REPORT_FILES) | set(DATA_FILES)
        if set(manifest["files"]) != required:
            raise ValueError("Unexpected export files")
        verified = []
        for name in sorted(required):
            expected = manifest["files"][name]
            size = expected["bytes"]
            if not isinstance(size, int) or not 0 < size <= 128 * 1024 * 1024:
                raise ValueError("Invalid export size")
            digest, total = hashlib.sha256(), 0
            with session.get(f"{base}/{snapshot}/{name}", timeout=60, allow_redirects=False, stream=True) as artifact:
                if artifact.status_code != 200:
                    raise ValueError("Artifact unavailable or redirect refused")
                for chunk in artifact.iter_content(1024 * 1024):
                    total += len(chunk)
                    if total > size:
                        raise ValueError("Artifact larger than declared size")
                    digest.update(chunk)
            if total != size or digest.hexdigest() != expected["sha256"]:
                raise ValueError("Artifact mismatch")
            verified.append(name)
    return {"status": "LOCAL_HTTP_VERIFIED" if local else "REMOTE_HTTP_VERIFIED",
            "checked_at": now.isoformat(), "snapshot_id": snapshot,
            "generated_at": manifest["generated_at"], "environment": manifest["environment"],
            "received_symbols": manifest["received_symbols"],
            "market_daily_rows": manifest["market_daily_rows"], "verified_files": verified,
            "manifest_read": True, "chatgpt_scheduled_read": "NOT_VERIFIED",
            "unattended_cloud_collection": "NOT_VERIFIED"}


def main():
    root = project_root()
    load_dotenv(root / ".env", override=False)
    parser = argparse.ArgumentParser()
    parser.add_argument("--local", action="store_true")
    args = parser.parse_args()
    token = os.getenv("BRIEFING_READ_TOKEN", "")
    server = worker = None
    try:
        if len(token) < 32:
            raise ValueError("Missing read token")
        base = os.getenv("BRIEFING_BASE_URL", "")
        if args.local:
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler_class(root / "reports" / "published", token))
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            base = f"http://127.0.0.1:{server.server_port}"
        result = verify(base, token, local=args.local)
        code = 0
    except Exception as exc:
        # Requests exceptions include secret URLs; never persist their messages.
        result = {"status": "NOT_CONNECTED", "checked_at": datetime.now(KST).isoformat(),
                  "error_type": type(exc).__name__, "chatgpt_scheduled_read": "NOT_VERIFIED"}
        code = 1
    finally:
        if server:
            server.shutdown()
            server.server_close()
            worker.join()
    atomic_json(root / "reports" / ("feed_local_check.json" if args.local else "feed_remote_check.json"), result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
