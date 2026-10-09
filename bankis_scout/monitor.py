"""Read-only intraday re-check. At 08:00 there cannot be an ORB/VWAP confirmation."""
from __future__ import annotations
from datetime import time
import pandas as pd
import numpy as np
from .settings import parse_asof, Settings


def recheck(preopen: dict, intraday: pd.DataFrame, asof, settings: Settings | None = None) -> dict:
    now = parse_asof(asof)
    cfg = settings or Settings()
    watch_asof = preopen.get("asof")
    try:
        base_time = parse_asof(watch_asof)
    except (ValueError, TypeError, AttributeError):
        base_time = None
    base_outdated = (base_time is None or base_time > now or
                     (now - base_time).total_seconds() > 6*86400)
    data = intraday.copy()
    if data.empty:
        data = pd.DataFrame(columns=["bar_end", "code", "venue", "open", "high", "low", "close", "volume", "turnover_krw", "bid", "ask", "source"])
    data["code"] = data["code"].astype(str).str.zfill(6)
    data["bar_end"] = pd.to_datetime(data["bar_end"], utc=True, errors="coerce").dt.tz_convert("Asia/Seoul")
    for fld in ["open", "high", "low", "close", "volume", "turnover_krw", "bid", "ask"]:
        data[fld] = pd.to_numeric(data[fld], errors="coerce")
    out = []
    for row in preopen["records"]:
        r = dict(row)
        r["intraday"] = {}
        if row["status"] != "WATCH":
            r["intraday_status"] = "NOT_ELIGIBLE"
            r["intraday_reasons"] = ["PREOPEN_"+row["status"]]
            out.append(r); continue
        if base_outdated:
            r["intraday_status"] = "DATA_BLOCKED"
            r["intraday_reasons"] = ["PREOPEN_WATCHLIST_MISSING_FUTURE_OR_TOO_OLD"]
            out.append(r); continue
        if now.time() < time(9,20):
            r["intraday_status"] = "WAIT_FOR_0920"
            r["intraday_reasons"] = ["ORB_AND_VWAP_NOT_OBSERVED"]
            out.append(r); continue
        g = data[(data["code"] == row["code"]) &
                 (data["bar_end"].dt.date == now.date()) &
                 (data["bar_end"] <= pd.Timestamp(now))].sort_values("bar_end").copy()
        errors = []
        if len(g) < cfg.min_intraday_bars: errors.append("INSUFFICIENT_INTRADAY_BARS")
        if len(g) and (now - g.iloc[-1]["bar_end"]).total_seconds() > 900:
            errors.append("STALE_INTRADAY_PRICE")
        if len(g) and g["venue"].nunique() != 1: errors.append("MIXED_VENUE_SCOPE")
        if len(g) and (g["venue"].astype(str).str.upper() != "KRX").any():
            errors.append("VENUE_SCOPE_NOT_KRX")
        if len(g) and g["source"].astype(str).str.strip().eq("").any(): errors.append("INTRADAY_SOURCE_UNKNOWN")
        if len(g) and (g["bar_end"].duplicated().any()): errors.append("DUPLICATE_INTRADAY_BARS")
        if len(g) and (g[["open", "high", "low", "close", "volume", "turnover_krw"]].isna().any(axis=1).any()):
            errors.append("MISSING_INTRADAY_FIELDS")
        if len(g) and g["volume"].gt(0).all():
            # Block incompatible quantity/value units and misaligned OHLC data.
            implied_price = g["turnover_krw"] / g["volume"]
            if ((implied_price < g["low"] * 0.7) | (implied_price > g["high"] * 1.3)).any():
                errors.append("TRADED_VALUE_UNITS_OR_PRICE_MISMATCH")
        if len(g) and g.iloc[-1][["bid","ask"]].isna().any():
            errors.append("LATEST_QUOTE_UNAVAILABLE")
        if len(g) and ((g[["open", "high", "low", "close"]] <= 0).any(axis=1) |
                       (g["high"] < g[["open", "close", "low"]].max(axis=1)) |
                       (g["low"] > g[["open", "close", "high"]].min(axis=1)) |
                       (g["volume"] <= 0) | (g["turnover_krw"] <= 0) |
                       (g.iloc[-1]["bid"]<=0) | (g.iloc[-1]["ask"]<=0) | (g.iloc[-1]["bid"]>g.iloc[-1]["ask"])).any():
            errors.append("INVALID_INTRADAY_PRICE_OR_QUOTE")
        if len(g):
            b = g.iloc[-1]
            if b["ask"]>0 and b["bid"]>0:
                spread = 100.0 * (b["ask"]-b["bid"])/((b["ask"]+b["bid"])/2)
                r["intraday"]["spread_pct"] = round(spread,3)
                if spread > cfg.max_spread_pct: errors.append("SPREAD_TOO_WIDE")
        else:
            errors.append("NO_INTRADAY_OBSERVATIONS")
        # Missing bars before 09:15 means opening range cannot be trusted.
        early = g[(g["bar_end"].dt.time >= time(9,5)) & (g["bar_end"].dt.time <= time(9,15))]
        if not {time(9,5), time(9,10), time(9,15)}.issubset(set(early["bar_end"].dt.time)):
            errors.append("OPENING_RANGE_INCOMPLETE")
        if len(g) and len(early) and g["bar_end"].dt.minute.mod(5).ne(0).any():
            errors.append("NOT_5MIN_BAR_ENDS")
        if errors:
            r["intraday_status"] = "DATA_BLOCKED" if "SPREAD_TOO_WIDE" not in errors else "REJECTED"
            r["intraday_reasons"] = sorted(set(errors))
            out.append(r); continue
        # Exact traded money is required for VWAP, no HLC3 masquerading as actual VWAP.
        g["vwap"] = g["turnover_krw"].cumsum()/g["volume"].cumsum()
        price = float(g.iloc[-1]["close"])
        vwap = float(g.iloc[-1]["vwap"])
        orh = float(early["high"].max()); orl = float(early["low"].min())
        after = g[g["bar_end"].dt.time > time(9,15)]
        prior = after.iloc[:-1]
        volbaseline = float(prior.tail(3)["volume"].median()) if len(prior) >= 2 else np.nan
        acceleration = (float(after.iloc[-1]["volume"])/volbaseline) if np.isfinite(volbaseline) and volbaseline>0 else None
        below_two = len(after)>=2 and bool((after.tail(2)["close"] < after.tail(2)["vwap"]).all())
        # Compare only completed post-opening-range bars; don't include the bar being evaluated as prior breakout evidence.
        past_broke = len(prior)>0 and bool((prior["high"] > orh * (1+cfg.orb_buffer_pct/100)).any())
        failed_breakout = (len(after)>=2 and past_broke and bool((after.tail(2)["close"] < orh*(1-cfg.breakout_failure_buffer_pct/100)).all()))
        r["intraday"] = {"latest_bar_end":str(g.iloc[-1]["bar_end"]),"venue":str(g.iloc[-1]["venue"]),
                         "close":round(price,2),"vwap":round(vwap,2),"opening_high":round(orh,2),"opening_low":round(orl,2),
                         "spread_pct":r["intraday"].get("spread_pct"),"volume_acceleration":round(acceleration,2) if acceleration is not None else None}
        if failed_breakout:
            status, causes = "REJECTED", ["FALSE_BREAKOUT_CONFIRMED"]
        elif below_two and price < orl:
            status, causes = "REJECTED", ["OPENING_LOW_AND_VWAP_BROKEN"]
        elif price > orh*(1+cfg.orb_buffer_pct/100) and price > vwap and acceleration is not None and acceleration >= cfg.min_acceleration:
            status, causes = "CONFIRMED_PATTERN", ["ORB_AND_VWAP_AND_VOLUME"]
        elif len(after)>=2 and price>vwap and bool(after.iloc[-2]["low"] <= after.iloc[-2]["vwap"]*1.002) and price > float(after.iloc[-2]["high"]):
            status, causes = "CONFIRMED_PATTERN", ["VWAP_PULLBACK_RECOVERY"]
        elif below_two:
            status, causes = "WARNING", ["TWO_BARS_BELOW_VWAP"]
        else:
            status, causes = "WATCH", ["NO_CONFIRMED_ENTRY_PATTERN"]
        r["intraday_status"] = status
        r["intraday_reasons"] = causes
        out.append(r)
    return {"app":preopen.get("app","BankIS Scout v1"),"mode":"INTRADAY_RECHECK_NOT_ORDER", "asof":now.isoformat(),
            "base_watchlist_asof":preopen.get("asof"),"coverage":{"input_watch":sum(r["status"]=="WATCH" for r in preopen["records"]),
            "confirmed":sum(x["intraday_status"]=="CONFIRMED_PATTERN" for x in out),
            "rejected":sum(x["intraday_status"]=="REJECTED" for x in out),
            "blocked":sum(x["intraday_status"]=="DATA_BLOCKED" for x in out)},"records":out,
            "method":"A confirmed pattern is NOT a proven positive-expectancy trade"}
