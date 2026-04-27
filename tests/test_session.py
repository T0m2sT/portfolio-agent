import pytest
from datetime import datetime
from zoneinfo import ZoneInfo
from agent.session import get_market_session, is_us_trading_day

_NY_TZ = ZoneInfo("America/New_York")

def test_get_market_session():
    # Pre-market: 04:00–09:30
    assert get_market_session(datetime(2026, 4, 27, 8, 0, tzinfo=_NY_TZ)) == "pre-market"
    
    # Regular: 09:30–16:00
    assert get_market_session(datetime(2026, 4, 27, 10, 0, tzinfo=_NY_TZ)) == "regular"
    assert get_market_session(datetime(2026, 4, 27, 9, 30, tzinfo=_NY_TZ)) == "regular"
    
    # After-hours: 16:00–20:00
    assert get_market_session(datetime(2026, 4, 27, 18, 0, tzinfo=_NY_TZ)) == "after-hours"
    assert get_market_session(datetime(2026, 4, 27, 16, 0, tzinfo=_NY_TZ)) == "after-hours"
    
    # Closed
    assert get_market_session(datetime(2026, 4, 27, 2, 0, tzinfo=_NY_TZ)) == "closed"
    assert get_market_session(datetime(2026, 4, 27, 21, 0, tzinfo=_NY_TZ)) == "closed"

def test_is_us_trading_day_weekends():
    # Saturday
    assert is_us_trading_day(now=datetime(2026, 5, 2, tzinfo=_NY_TZ)) is False
    # Sunday
    assert is_us_trading_day(now=datetime(2026, 5, 3, tzinfo=_NY_TZ)) is False

def test_is_us_trading_day_weekdays():
    # Monday
    assert is_us_trading_day(now=datetime(2026, 4, 27, tzinfo=_NY_TZ)) is True
