"""Serve only curated artifacts behind an opaque read token. No directory access."""
import argparse
import hmac
import json
import os
import re
import secrets
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

from .settings import KST
from .runtime import project_root
from .feed import read_verified_artifact

ALLOWED = {"briefing.md": "text/plain; charset=utf-8", "status.json": "application/json; charset=utf-8",
           "intelligence.html": "text/html; charset=utf-8", "preopen.html": "text/html; charset=utf-8",
           "manifest.json": "application/json; charset=utf-8",
           "market_daily.csv": "text/csv; charset=utf-8", "index_daily.csv": "text/csv; charset=utf-8"}


def handler_class(folder, token):
    folder = Path(folder)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # URL includes a read secret; never log it.

        def reply(self, status, body, mime="application/json; charset=utf-8"):
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Robots-Tag", "noindex, nofollow")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            parts = urlsplit(self.path).path.strip("/").split("/")
            if len(parts) not in (2, 3) or not re.fullmatch(r"[a-zA-Z0-9_-]+", parts[0]) or not hmac.compare_digest(parts[0], token) or parts[-1] not in ALLOWED:
                self.reply(404, b'{"status":"NOT_FOUND"}')
                return
            try:
                # Pin subsequent reads to the manifest's snapshot even if CURRENT changes.
                name = parts[1] if len(parts) == 3 else (folder / "CURRENT").read_text(encoding="utf-8").strip()
                if not re.fullmatch(r"[0-9]{8}T[0-9]{12}", name):
                    raise ValueError("Invalid export pointer")
                export = folder / name
                status = json.loads(read_verified_artifact(export, "status.json"))
                generated = datetime.fromisoformat(status["generated_at"]).astimezone(KST)
                if generated.date() != datetime.now(KST).date() or generated > datetime.now(KST):
                    self.reply(503, b'{"status":"STALE_OR_FUTURE_REPORT"}')
                    return
                self.reply(200, read_verified_artifact(export, parts[-1]), ALLOWED[parts[-1]])
            except (OSError, ValueError, KeyError):
                self.reply(503, b'{"status":"REPORT_UNAVAILABLE"}')

    return Handler


def main():
    root = project_root()
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--init-token", action="store_true")
    args = parser.parse_args()
    path = root / ".env"
    load_dotenv(path, override=False)
    if args.init_token:
        if not os.getenv("BRIEFING_READ_TOKEN"):
            with path.open("a", encoding="utf-8") as file:
                file.write("\nBRIEFING_READ_TOKEN=" + secrets.token_urlsafe(32) + "\n")
        print("Read token configured in local .env; value not displayed")
        return 0
    token = os.getenv("BRIEFING_READ_TOKEN", "")
    if not re.fullmatch(r"[a-zA-Z0-9_-]{32,}", token):
        print("BRIEFING_READ_TOKEN missing/invalid; run --init-token")
        return 2
    server = ThreadingHTTPServer((args.host, args.port), handler_class(root / "reports" / "published", token))
    print("Curated report server started; HTTPS reverse proxy required for remote use", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    raise SystemExit(main())
