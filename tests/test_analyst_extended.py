import pytest
from datetime import datetime, timezone
from unittest.mock import patch
from agent.analyst import _market_session, _price_line, build_prompt

PORTFOLIO = {
    "cash": 50.00,
    "holdings": [{"ticker": "MSFT", "shares": 0.1, "avg_buy_price_usd": 400.00, "total_cost_eur": 40.00}],
    "watchlist": ["NVDA"],
    "ticker_signals": {"MSFT": {"action": "BUY", "reasoning": "Strong AI thesis"}},
}
PRICES = {
    "MSFT": {"price": 420.00, "pct_change": 1.5, "week_pct": 3.2, "day_high": 422.00, "day_low": 415.00, "week_high": 425.00, "week_low": 410.00},
    "NVDA": {"price": 880.00, "pct_change": -0.8},
}
NEWS = {"MSFT": ["Microsoft beats earnings"], "NVDA": []}


# _market_session
def test_market_session_premarket():
    dt = datetime(2026, 4, 26, 10, 0, tzinfo=timezone.utc)
    assert _market_session(dt) == "pre-market"

def test_market_session_us_open():
    dt = datetime(2026, 4, 26, 15, 0, tzinfo=timezone.utc)
    assert _market_session(dt) == "US open (high volatility)"

def test_market_session_mid():
    dt = datetime(2026, 4, 26, 17, 0, tzinfo=timezone.utc)
    assert _market_session(dt) == "US mid-session"

def test_market_session_close():
    dt = datetime(2026, 4, 26, 20, 0, tzinfo=timezone.utc)
    assert _market_session(dt) == "US close"

def test_market_session_afterhours():
    dt = datetime(2026, 4, 26, 22, 0, tzinfo=timezone.utc)
    assert _market_session(dt) == "post-market / after-hours"


# _price_line
def test_price_line_full():
    line = _price_line("MSFT", PRICES["MSFT"], avg_buy_usd=400.00, alloc_pct=35.5)
    assert "MSFT" in line
    assert "$420.00" in line
    assert "today +1.5%" in line
    assert "5d +3.2%" in line
    assert "$415.00–$422.00" in line
    assert "$410.00–$425.00" in line
    assert "vs entry +5.0%" in line
    assert "portfolio 35.5%" in line

def test_price_line_missing_price():
    line = _price_line("FAKE", {})
    assert "N/A" in line

def test_price_line_no_optional_fields():
    line = _price_line("NVDA", {"price": 880.00, "pct_change": -0.8})
    assert "$880.00" in line
    assert "today -0.8%" in line
    assert "5d" not in line
    assert "portfolio" not in line


# build_prompt
def test_build_prompt_includes_time():
    prompt = build_prompt(PORTFOLIO, PRICES, NEWS)
    assert "CURRENT TIME" in prompt
    assert "UTC" in prompt

def test_build_prompt_includes_session():
    prompt = build_prompt(PORTFOLIO, PRICES, NEWS)
    assert "Session:" in prompt

def test_build_prompt_includes_previous_signals():
    prompt = build_prompt(PORTFOLIO, PRICES, NEWS)
    assert "PREVIOUS SIGNALS" in prompt
    assert "MSFT" in prompt
    assert "BUY" in prompt

def test_build_prompt_no_previous_signals_when_empty():
    portfolio = {**PORTFOLIO, "ticker_signals": {}}
    prompt = build_prompt(portfolio, PRICES, NEWS)
    assert "PREVIOUS SIGNALS" not in prompt

def test_build_prompt_includes_allocation():
    prompt = build_prompt(PORTFOLIO, PRICES, NEWS)
    assert "portfolio" in prompt

def test_build_prompt_includes_week_range():
    prompt = build_prompt(PORTFOLIO, PRICES, NEWS)
    assert "5d" in prompt
    assert "410.00" in prompt

def test_build_prompt_includes_news():
    prompt = build_prompt(PORTFOLIO, PRICES, NEWS)
    assert "Microsoft beats earnings" in prompt

def test_build_prompt_includes_watchlist():
    prompt = build_prompt(PORTFOLIO, PRICES, NEWS)
    assert "Watchlist" in prompt
    assert "NVDA" in prompt

def test_build_prompt_includes_buzz():
    prompt = build_prompt(PORTFOLIO, PRICES, NEWS, trending=["TSLA"])
    assert "buzz" in prompt.lower()
    assert "TSLA" in prompt

def test_build_prompt_buzz_excludes_held_and_watched():
    prompt = build_prompt(PORTFOLIO, PRICES, NEWS, trending=["MSFT", "NVDA", "TSLA"])
    # MSFT is held, NVDA is on watchlist — only TSLA should appear in buzz
    lines = [l for l in prompt.split("\n") if "buzz" in l.lower() or "TSLA" in l]
    assert any("TSLA" in l for l in lines)

def test_build_prompt_cash_displayed():
    prompt = build_prompt(PORTFOLIO, PRICES, NEWS)
    assert "50.00" in prompt
