"""Current KIS master snapshots; never pretend current constituents are historical."""
import hashlib
import io
import json
import re
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

from .settings import KST

MASTER_BASE = "https://new.real.download.dws.co.kr/common/master/"
EQUITY_GROUPS = {"ST", "RT", "PF", "IF", "MF", "DR", "FS"}


def parse_master(raw, market):
    # Official parsers retain newline when subtracting the 228/222-character tail.
    tail_size = {"KOSPI": 228, "KOSDAQ": 222}[market]
    rows, excluded = [], Counter()
    for line in raw.decode("cp949").splitlines(keepends=True):
        if len(line) < tail_size + 21:
            raise ValueError("Master schema changed: short record")
        prefix, tail = line[:-tail_size], line[-tail_size:]
        code, isin, name = prefix[:9].strip(), prefix[9:21].strip(), prefix[21:].strip()
        group = tail[:2]
        if not re.fullmatch(r"[0-9A-Z]{6}", code) or group not in EQUITY_GROUPS:
            excluded[group] += 1
            continue
        if len(isin) != 12 or not name or not re.fullmatch(r"[0-9]{4}", tail[3:7]):
            raise ValueError("Master schema changed: identity or sector invalid")
        rows.append({"code": code, "name": name, "market": market,
                     "sector": market + ":" + tail[3:7], "isin": isin, "security_group": group})
    if not rows or len({x["code"] for x in rows}) != len(rows):
        raise ValueError("Empty or duplicate master")
    return rows, dict(excluded)


def download_universe(folder, session=None):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    session = session or requests.Session()
    stamp = datetime.now(KST).isoformat()
    rows, sources = [], []
    for market in ("KOSPI", "KOSDAQ"):
        filename = market.lower() + "_code.mst"
        url = MASTER_BASE + filename + ".zip"
        response = session.get(url, timeout=40)
        response.raise_for_status()
        archive = zipfile.ZipFile(io.BytesIO(response.content))
        raw = archive.read(filename)  # read exact member; no archive extraction
        parsed, excluded = parse_master(raw, market)
        rows.extend(parsed)
        sources.append({"market": market, "url": url, "sha256": hashlib.sha256(raw).hexdigest(),
                        "equities": len(parsed), "excluded_groups": excluded})
        (folder / filename).write_bytes(raw)
    if len({r["code"] for r in rows}) != len(rows):
        raise ValueError("Cross-market duplicate master code")
    frame = pd.DataFrame(rows).sort_values(["market", "code"])
    frame.to_csv(folder / "universe.csv", index=False, encoding="utf-8-sig")
    receipt = {"downloaded_at": stamp, "symbols": len(frame), "sources": sources,
               "scope": "Current KOSPI/KOSDAQ equity groups ST,RT,PF,IF,MF,DR,FS; ETF/ETN, rights, bonds excluded",
               "historical_constituents_verified": False,
               "contest_eligibility_verified": False}
    (folder / "universe_receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    return frame, receipt
