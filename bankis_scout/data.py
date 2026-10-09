"""Input contracts, temporal eligibility, and safe CSV readers."""
from __future__ import annotations
import math
from pathlib import Path
import pandas as pd

DAILY_FIELDS = ["date", "code", "name", "market", "sector", "open", "high", "low", "close", "volume", "turnover_krw", "source"]
INDEX_FIELDS = ["date", "market", "close", "source"]
ELIGIBILITY_FIELDS = ["code", "eligible", "risk_level", "checked_at", "source_url"]
EVENT_FIELDS = ["code", "published_at", "event_type", "title", "source_url", "verified", "materiality"]
INTRADAY_FIELDS = ["bar_end", "code", "venue", "open", "high", "low", "close", "volume", "turnover_krw", "bid", "ask", "source"]

class DataContractError(ValueError):
    pass


def csv_read(path: str | Path, required: list[str]) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        raise DataContractError(f"required file not found: {p} (empty and missing must not be treated as zero)")
    df = pd.read_csv(p, dtype={"code": "string"}, keep_default_na=False)
    missing = [x for x in required if x not in df]
    if missing:
        raise DataContractError(f"{p.name} missing columns: {missing}")
    return df


def load_bundle(folder: str | Path) -> dict[str, pd.DataFrame]:
    p = Path(folder)
    out = {"daily": csv_read(p / "daily.csv", DAILY_FIELDS),
           "index": csv_read(p / "index_daily.csv", INDEX_FIELDS),
           "eligibility": csv_read(p / "eligibility.csv", ELIGIBILITY_FIELDS)}
    for key, fname, fields in [("events", "events.csv", EVENT_FIELDS), ("intraday", "intraday.csv", INTRADAY_FIELDS)]:
        out[key] = csv_read(p / fname, fields) if (p / fname).exists() else pd.DataFrame(columns=fields)
    return out


def is_true(x) -> bool:
    return str(x).strip().lower() in {"1", "yes", "true", "t", "y"}


def prepare_daily(df: pd.DataFrame, allowed_date) -> tuple[pd.DataFrame, dict[str, list[str]]]:
    """Reject entire symbol history on conflicting duplicates or invalid OHLC, prevent lookahead."""
    df = df.copy()
    df["code"] = df["code"].astype(str).str.zfill(6)
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    for c in ["open", "high", "low", "close", "volume", "turnover_krw"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    # Point-in-time cut must precede all validation: future rows must not contaminate flags.
    df = df[df["date"].notna() & (df["date"] <= allowed_date)].copy()
    issues: dict[str, list[str]] = {}
    def flag(symbol: str, cause: str) -> None:
        issues.setdefault(symbol, [])
        if cause not in issues[symbol]:
            issues[symbol].append(cause)
    for code, g in df.groupby("code", sort=False):
        bad = (g["date"].isna() | g["source"].astype(str).str.strip().eq("") |
               g[["open", "high", "low", "close", "volume", "turnover_krw"]].isna().any(axis=1) |
               (g[["open", "high", "low", "close"]] <= 0).any(axis=1) |
               (g["volume"] < 0) | (g["turnover_krw"] < 0) |
               (g["high"] < g[["open", "low", "close"]].max(axis=1)) |
               (g["low"] > g[["open", "high", "close"]].min(axis=1)))
        if bad.any(): flag(code, "INVALID_OHLC_OR_SOURCE")
        if g.duplicated(subset=["date"], keep=False).any():
            du = g[g.duplicated(subset=["date"], keep=False)]
            # Exact repeats harmless; data discrepancies invalidate ticker.
            for _, group in du.groupby("date"):
                if group.drop(columns=["date"]).drop_duplicates().shape[0] > 1:
                    flag(code, "CONFLICTING_DUPLICATE")
    df = df.drop_duplicates(subset=["code", "date"]).sort_values(["code", "date"])
    return df, issues


def prepare_index(df: pd.DataFrame, allowed_date) -> tuple[pd.DataFrame, dict[str, str]]:
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df[df["date"].notna() & (df["date"] <= allowed_date)].copy()
    out_issues: dict[str, str] = {}
    for market, g in df.groupby("market"):
        if (g["close"].isna() | (g["close"] <= 0) | g["date"].isna()).any():
            out_issues[market] = "INVALID_BENCHMARK"
        elif g.duplicated(subset="date", keep=False).any():
            du = g[g.duplicated(subset="date", keep=False)]
            if any(chunk["close"].nunique() > 1 for _, chunk in du.groupby("date")):
                out_issues[market] = "CONFLICTING_INDEX_DUPLICATE"
    df = df.drop_duplicates(["date", "market"]).sort_values(["market", "date"])
    return df, out_issues
