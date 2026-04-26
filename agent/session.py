from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

logger = logging.getLogger(__name__)

_NY_TZ = ZoneInfo("America/New_York")
_FINNHUB_URL = "https://finnhub.io/api/v1"


def get_market_session(now: datetime | None = None) -> str:
    """Return the current US market session based on ET time.

    Returns one of: pre-market, regular, after-hours, closed
      pre-market:   04:00–09:30 ET
      regular:      09:30–16:00 ET
      after-hours:  16:00–20:00 ET
      closed:       otherwise
    """
    ny_now = (now or datetime.now(_NY_TZ)).astimezone(_NY_TZ)
    minutes = ny_now.hour * 60 + ny_now.minute

    if 4 * 60 <= minutes < 9 * 60 + 30:
        return "pre-market"
    if 9 * 60 + 30 <= minutes < 16 * 60:
        return "regular"
    if 16 * 60 <= minutes < 20 * 60:
        return "after-hours"
    return "closed"


def is_us_trading_day(api_key: str | None = None, now: datetime | None = None) -> bool:
    """Return True if today is a US trading day (not weekend or public holiday).

    Uses the NY date. Checks Finnhub holiday calendar when an API key is
    provided. Falls back to weekday-only check on any failure.
    Never raises.
    """
    ny_now = (now or datetime.now(_NY_TZ)).astimezone(_NY_TZ)
    today = ny_now.date()

    if today.weekday() >= 5:
        return False

    if not api_key:
        return True

    try:
        resp = requests.get(
            f"{_FINNHUB_URL}/stock/market-holiday",
            params={"exchange": "US", "token": api_key},
            timeout=10,
        )
        resp.raise_for_status()
        holidays = resp.json().get("data", [])
        holiday_dates = {h.get("atDate") for h in holidays}
        return today.isoformat() not in holiday_dates
    except Exception as exc:
        logger.warning("Could not verify Finnhub holidays; assuming trading day: %r", exc)
        return True
