"""Check supplied-series continuity; not independent certification of exchange history."""
from .data import prepare_daily, prepare_index
from .settings import last_allowed_daily_date, parse_asof


def audit_recent_sessions(bundle, asof, minimum=25):
    cutoff = last_allowed_daily_date(parse_asof(asof))
    daily, price_issues = prepare_daily(bundle["daily"], cutoff)
    index, index_issues = prepare_index(bundle["index"], cutoff)
    calendars = {str(market): sorted(set(group.date))[-minimum:] for market, group in index.groupby("market")}
    failures, ok = [], 0
    for code, frame in daily.groupby("code"):
        market = str(frame.iloc[-1]["market"])
        expected = calendars.get(market, [])
        missing = sorted(set(expected) - set(frame.date))
        if code in price_issues or market in index_issues or len(expected) < minimum:
            failures.append({"code": str(code), "reason": "INVALID_PRICE_OR_BENCHMARK_HISTORY"})
        elif missing:
            failures.append({"code": str(code), "reason": "MISSING_RECENT_SESSION_BARS", "missing_dates": [str(x) for x in missing]})
        else:
            ok += 1
    return {"recent_window": minimum, "symbols_examined": daily.code.nunique(), "recent_window_complete": ok,
            "failed": failures, "independent_exchange_calendar_verified": False,
            "limits": "Calendar inferred from supplied benchmark records; new listings and suspended stocks may lack the window."}
