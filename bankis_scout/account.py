"""Separate GET-only account reader. Raw financial data stays in .secrets/."""
import argparse
import json
import os
import re
import time
from datetime import date, datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

from .kis import KISClient, KISDataError
from .settings import KST
from .runtime import project_root

BALANCE = "/uapi/domestic-stock/v1/trading/inquire-balance"
FILLS = "/uapi/domestic-stock/v1/trading/inquire-daily-ccld"


class KISAccountReader:
    def __init__(self, client, cano, product):
        if not re.fullmatch(r"[0-9]{8}", cano or "") or not re.fullmatch(r"[0-9]{2}", product or ""):
            raise ValueError("ACCOUNT_CONFIGURATION_MISSING")
        self.client, self.cano, self.product = client, cano, product

    def pages(self, path, params, max_pages=100):
        if path not in {BALANCE, FILLS}:
            raise KISDataError("Account reader permits balance and fill GET endpoints only")
        client = self.client
        client.authenticate()
        tr = ({"prod": "TTTC8434R", "vps": "VTTC8434R"} if path == BALANCE else
              {"prod": "TTTC0081R", "vps": "VTTC0081R"})[client.env]
        params = {**params, "CANO": self.cano, "ACNT_PRDT_CD": self.product,
                  "CTX_AREA_FK100": "", "CTX_AREA_NK100": ""}
        seen, result, continuation = set(), [], ""
        for _ in range(max_pages):
            headers = {"authorization": "Bearer " + client.token, "appkey": client.key,
                       "appsecret": client.secret, "tr_id": tr, "tr_cont": continuation,
                       "custtype": "P", "content-type": "application/json; charset=utf-8"}
            payload, response = None, None
            for attempt in range(3):
                time.sleep(max(client.sleep_seconds, 0.65 if client.env == "vps" else 0.12))
                try:
                    response = client.session.get(client.base + path, params=params, headers=headers, timeout=20)
                    response.raise_for_status()
                    payload = response.json()
                    break
                except (requests.RequestException, ValueError):
                    if attempt == 2:
                        raise KISDataError("Account query failed; response and account identifiers suppressed") from None
                    time.sleep(attempt + 1)
            if not isinstance(payload, dict) or str(payload.get("rt_cd")) != "0":
                raise KISDataError("Account API rejected query; account details suppressed")
            if not isinstance(payload.get("output1"), list) or not isinstance(payload.get("output2"), (dict, list)):
                raise KISDataError("Account response schema invalid")
            result.append(payload)
            if response.headers.get("tr_cont") not in {"M", "F"}:
                return result
            cursor = (str(payload.get("ctx_area_fk100", "")).strip(), str(payload.get("ctx_area_nk100", "")).strip())
            if not any(cursor) or cursor in seen:
                raise KISDataError("Account pagination incomplete or repeated")
            seen.add(cursor)
            params["CTX_AREA_FK100"], params["CTX_AREA_NK100"] = cursor
            continuation = "N"
        raise KISDataError("Account pagination limit reached; partial account results rejected")

    def balance(self):
        return self.pages(BALANCE, {"AFHR_FLPR_YN": "N", "OFL_YN": "", "INQR_DVSN": "02",
                                   "UNPR_DVSN": "01", "FUND_STTL_ICLD_YN": "N",
                                   "FNCG_AMT_AUTO_RDPT_YN": "N", "PRCS_DVSN": "00"})

    def fills(self, start, end):
        if start > end or (end - start).days > 90:
            raise ValueError("Fill query supports an ordered range of at most 90 days")
        return self.pages(FILLS, {"INQR_STRT_DT": start.strftime("%Y%m%d"), "INQR_END_DT": end.strftime("%Y%m%d"),
                                 "SLL_BUY_DVSN_CD": "00", "PDNO": "", "CCLD_DVSN": "01",
                                 "INQR_DVSN": "01", "INQR_DVSN_3": "00", "ORD_GNO_BRNO": "",
                                 "ODNO": "", "INQR_DVSN_1": ""})


def main():
    root = project_root()
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default=str(root / ".env"))
    parser.add_argument("--start", default=datetime.now(KST).date().isoformat())
    parser.add_argument("--end", default=datetime.now(KST).date().isoformat())
    args = parser.parse_args()
    load_dotenv(args.env_file, override=False)
    status = {"checked_at": datetime.now(KST).isoformat(), "environment": os.getenv("KIS_ENV"),
              "orders_enabled": False, "status": "NOT_CONNECTED"}
    try:
        reader = KISAccountReader(KISClient(), os.getenv("KIS_CANO", ""), os.getenv("KIS_ACNT_PRDT_CD", ""))
        balance = reader.balance()
        fills = reader.fills(date.fromisoformat(args.start), date.fromisoformat(args.end))
        private = root / ".secrets" / "account"
        private.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(KST).strftime("%Y%m%dT%H%M%S%f")
        for name, rows in (("balance", balance), ("fills", fills)):
            path = private / (name + "_" + stamp + ".json")
            path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
            path.chmod(0o600)
        status.update(status="CONNECTED", balance_pages=len(balance), fill_pages=len(fills))
    except ValueError:
        status["reason"] = "ACCOUNT_CONFIGURATION_MISSING_OR_INVALID"
    except Exception as exc:
        status.update(status="QUERY_FAILED", error_type=type(exc).__name__)
    out = root / "reports" / "account_connection"
    out.mkdir(parents=True, exist_ok=True)
    (out / "status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
    print(json.dumps(status, indent=2))
    return 0 if status["status"] == "CONNECTED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
