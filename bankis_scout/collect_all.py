"""Sequential, resumable full-equity collection with explicit coverage."""
import argparse
import json
import math
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

from .data import DAILY_FIELDS, INDEX_FIELDS, ELIGIBILITY_FIELDS, prepare_daily, prepare_index
from .kis import KISClient
from .settings import KST, last_allowed_daily_date
from .universe import download_universe
from .runtime import project_root


def atomic_json(path, value):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def validate_stock(rows, end):
    if not rows:
        raise ValueError("Empty response")
    frame, issues = prepare_daily(pd.DataFrame(rows), end)
    if issues or frame.empty or len(frame) != len(rows):
        raise ValueError("Invalid daily contract")
    if not all(math.isfinite(float(v)) for col in ("open", "high", "low", "close", "volume", "turnover_krw") for v in frame[col]):
        raise ValueError("Non-finite data")
    return frame


class RequestGate:
    """One shared start-rate limit, even while several HTTP responses are pending."""
    def __init__(self, interval):
        self.interval, self.lock, self.last = interval, threading.Lock(), 0.0

    def wait(self):
        with self.lock:
            delay = self.interval - (time.monotonic() - self.last)
            if delay > 0:
                time.sleep(delay)
            self.last = time.monotonic()


class GatedSession(requests.Session):
    def __init__(self, gate):
        super().__init__()
        self.gate = gate

    def get(self, *args, **kwargs):
        self.gate.wait()
        return super().get(*args, **kwargs)


def _collect_all(client, folder, asof=None, lookback_days=130, refresh_master=True):
    now = datetime.now(KST) if asof is None else datetime.fromisoformat(asof).astimezone(KST)
    out = Path(folder)
    out.mkdir(parents=True, exist_ok=True)
    if refresh_master or not (out / "universe.csv").exists():
        universe, master = download_universe(out)
    else:
        universe = pd.read_csv(out / "universe.csv", dtype={"code": str}, keep_default_na=False)
        master = json.loads((out / "universe_receipt.json").read_text(encoding="utf-8"))
    end = last_allowed_daily_date(now)
    start = end - timedelta(days=lookback_days)
    run_key = f"{client.env}_{start}_{end}"
    cache = out / "snapshots" / run_key
    cache.mkdir(parents=True, exist_ok=True)
    receipt = {"status": "RUNNING", "environment": client.env, "started_at": now.isoformat(),
               "query_start_date": str(start), "query_end_date": str(end), "master": master,
               "expected_symbols": len(universe), "attempted": 0, "ok": 0, "adequate_history": 0,
               "failed": [], "symbols": [], "indices": [], "contest_eligibility_verified": False}
    indices = []
    for market in ("KOSPI", "KOSDAQ"):
        try:
            path = cache / f"INDEX_{market}.json"
            if path.exists():
                item = json.loads(path.read_text(encoding="utf-8"))
            else:
                rows = client.index_daily(market, start, end)
                item = {"rows": rows, "received_at": datetime.now(KST).isoformat()}
            if not item["rows"]:
                raise ValueError("Empty index")
            frame, issues = prepare_index(pd.DataFrame(item["rows"]), end)
            if issues or frame.empty or len(frame) != len(item["rows"]):
                raise ValueError("Invalid index")
            atomic_json(path, item)
            indices.extend(item["rows"])
            receipt["indices"].append({"market": market, "status": "OK", "latest_date": str(frame.date.max())})
        except Exception as exc:
            receipt["indices"].append({"market": market, "status": "FAILED", "error_type": type(exc).__name__})
    latest_index = {x["market"]: x.get("latest_date") for x in receipt["indices"]}
    client.authenticate()
    gate = RequestGate(0.65 if client.env == "vps" else 0.12)
    local = threading.local()

    def fetch_one(row):
        if not hasattr(local, "client"):
            local.client = KISClient(key=client.key, secret=client.secret, env=client.env,
                                     session=GatedSession(gate), sleep_seconds=0)
            local.client.token, local.client.token_expiry = client.token, client.token_expiry
        path = cache / f"{row['code']}.json"
        if path.exists():
            item = json.loads(path.read_text(encoding="utf-8"))
        else:
            rows = local.client.stock_daily(row['code'], row['market'], row['name'], row['sector'], start, end)
            item = {"rows": rows, "received_at": datetime.now(KST).isoformat()}
        frame = validate_stock(item["rows"], end)
        if set(frame.code.astype(str)) != {row['code']}:
            raise ValueError("Cached ticker mismatch")
        atomic_json(path, item)
        return item, frame

    all_rows = []
    atomic_json(out / "collection_status.json", receipt)
    pool = ThreadPoolExecutor(max_workers=4)
    futures = {pool.submit(fetch_one, row): row for row in universe.to_dict("records")}
    for future in as_completed(futures):
        row = futures[future]
        code = row["code"]
        receipt["attempted"] += 1
        try:
            item, frame = future.result()
            all_rows.extend(item["rows"])
            latest = str(frame.date.max())
            adequate = len(frame) >= 25 and latest == latest_index.get(row["market"])
            receipt["ok"] += 1
            receipt["adequate_history"] += int(adequate)
            receipt["symbols"].append({"code": code, "rows": len(frame), "latest_date": latest,
                                        "received_at": item["received_at"], "adequate_history": adequate})
        except Exception as exc:
            receipt["failed"].append({"code": code, "error_type": type(exc).__name__})
        if receipt["attempted"] % 50 == 0:
            atomic_json(out / "collection_status.json", receipt)
            print(json.dumps({k: receipt[k] for k in ("attempted", "expected_symbols", "ok", "adequate_history")}), flush=True)
    pool.shutdown(wait=True)
    pd.DataFrame(all_rows, columns=DAILY_FIELDS).to_csv(out / "daily.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(indices, columns=INDEX_FIELDS).to_csv(out / "index_daily.csv", index=False, encoding="utf-8-sig")
    # Unknown contest permissions must remain unknown, never auto-approve constituents.
    if not (out / "eligibility.csv").exists():
        pd.DataFrame(columns=ELIGIBILITY_FIELDS).to_csv(out / "eligibility.csv", index=False)
    receipt["finished_at"] = datetime.now(KST).isoformat()
    receipt["status"] = "COMPLETE" if not receipt["failed"] and all(x["status"] == "OK" for x in receipt["indices"]) else "PARTIAL"
    receipt["rows"] = len(all_rows)
    atomic_json(out / "collection_status.json", receipt)
    return receipt


def collect_all(client, folder, asof=None, lookback_days=130, refresh_master=True):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    lock = folder / "collection.lock"
    try:
        with lock.open("x") as file:
            file.write(str(os.getpid()))
    except FileExistsError:
        raise ValueError("COLLECTION_LOCK_EXISTS") from None
    try:
        return _collect_all(client, folder, asof, lookback_days, refresh_master)
    finally:
        lock.unlink()


def main():
    root = project_root()
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(root / "data" / "kis_all"))
    parser.add_argument("--env-file", default=str(root / ".env"))
    parser.add_argument("--reuse-master", action="store_true")
    args = parser.parse_args()
    load_dotenv(args.env_file, override=False)
    try:
        client = KISClient(sleep_seconds=0.6 if os.getenv("KIS_ENV") == "vps" else 0.12)
        result = collect_all(client, args.output, refresh_master=not args.reuse_master)
        print(json.dumps({k: result[k] for k in ("status", "expected_symbols", "ok", "adequate_history", "rows")}), flush=True)
        return 0 if result["status"] == "COMPLETE" else 2
    except Exception as exc:
        print(json.dumps({"status": "FAILED", "error_type": type(exc).__name__}), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
