from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")

@dataclass(frozen=True)
class Settings:
    history_min: int = 25
    min_turnover_krw: float = 30_000_000_000
    min_median_turnover_krw: float = 10_000_000_000
    min_watch_score: float = 60
    stale_days: int = 7
    risk_move_limit: float = 0.38  # catch stock split/corporate actions; not an exchange price limit
    max_spread_pct: float = 0.40
    max_venue_spread_pct: float = 0.40
    min_intraday_bars: int = 4
    orb_buffer_pct: float = 0.15
    breakout_failure_buffer_pct: float = 0.20
    min_acceleration: float = 1.20
    min_trend_bars_below_vwap: int = 2
    lot_fee_pct: float = 0.33  # explicit hypothetical round trip cost, NOT a verified contest fee


def parse_asof(value: str | datetime) -> datetime:
    """Require an explicit offset or use Asia/Seoul if local time string is supplied."""
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=KST)
    return dt.astimezone(KST)


def last_allowed_daily_date(asof: datetime):
    """Conservative EOD time gate: no same-day daily close before 15:40 KST."""
    local = parse_asof(asof)
    today = local.date()
    if local.hour * 60 + local.minute < 15 * 60 + 40:
        return today - timedelta(days=1)
    return today
