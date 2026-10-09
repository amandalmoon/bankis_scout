"""Read-only sandbox smoke check; never persist credentials or tokens."""
import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from .data import prepare_daily, prepare_index
from .kis import KISClient
from .settings import KST, last_allowed_daily_date
from .runtime import project_root


def main():
    root = project_root()
    load_dotenv(root / ".env", override=False)
    now = datetime.now(KST)
    end = last_allowed_daily_date(now)
    start = end - timedelta(days=45)
    out = root / "reports" / "kis_verification"
    out.mkdir(parents=True, exist_ok=True)
    result = {"checked_at": now.isoformat(), "environment": "vps", "checks": [],
              "limitations": ["Sample query only; full universe and profitability unverified.",
                               "Sandbox responses are not independently verified exchange data."]}
    try:
        client = KISClient(sleep_seconds=1.1)
        if client.env != "vps":
            raise ValueError("Sandbox configuration required")
        client.authenticate()
        result["checks"].append({"check": "authentication", "status": "PASS"})
        for code, market in [("005930", "KOSPI"), ("035900", "KOSDAQ")]:
            try:
                rows = client.stock_daily(code, market, code, "", start, end)
                if not rows:
                    raise ValueError("Empty daily response")
                frame, issues = prepare_daily(pd.DataFrame(rows), end)
                if issues or frame.empty or len(frame) != len(rows):
                    raise ValueError("Daily contract failed")
                frame.to_csv(out / f"daily_{code}.csv", index=False, encoding="utf-8-sig")
                result["checks"].append({"check": "stock_daily", "code": code, "status": "PASS",
                                         "rows": len(frame), "latest_date": str(frame.date.max())})
            except Exception as exc:
                result["checks"].append({"check": "stock_daily", "code": code, "status": "FAIL",
                                         "error_type": type(exc).__name__})
        for market in ("KOSPI", "KOSDAQ"):
            try:
                rows = client.index_daily(market, start, end)
                if not rows:
                    raise ValueError("Empty index response")
                frame, issues = prepare_index(pd.DataFrame(rows), end)
                if issues or frame.empty or len(frame) != len(rows):
                    raise ValueError("Index contract failed")
                frame.to_csv(out / f"index_{market}.csv", index=False, encoding="utf-8-sig")
                result["checks"].append({"check": "index_daily", "market": market, "status": "PASS",
                                         "rows": len(frame), "latest_date": str(frame.date.max())})
            except Exception as exc:
                result["checks"].append({"check": "index_daily", "market": market, "status": "FAIL",
                                         "error_type": type(exc).__name__})
    except Exception as exc:
        result["checks"].append({"check": "authentication_or_configuration", "status": "FAIL",
                                 "error_type": type(exc).__name__})
    result["status"] = "PASS" if all(x["status"] == "PASS" for x in result["checks"]) else "FAIL"
    (out / "status.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
