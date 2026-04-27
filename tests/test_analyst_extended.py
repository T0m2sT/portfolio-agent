import pytest
from datetime import datetime
from zoneinfo import ZoneInfo
from agent.analyst import build_prompt
from agent.session import get_market_session

ET = ZoneInfo("America/New_York")

PORTFOLIO = {
    "cash": 3500.00,
    "holdings": [
        {
            "ticker": "MSFT",
            "shares": 0.5,
            "avg_buy_price_usd": 400.00,
            "total_cost_eur": 200.00,
            "bought_pct": 10,
        },
        {
            "ticker": "AAPL",
            "shares": 1.0,
            "avg_buy_price_usd": 170.00,
            "total_cost_eur": 160.00,
            "bought_pct": 8,
        },
    ],
}
PRICES = {
    "MSFT": {"price": 420.00, "pct_change": 1.5, "week_pct": 3.2, "day_high": 422.00, "day_low": 415.00},
    "AAPL": {"price": 185.00, "pct_change": -0.5, "week_pct": 1.1},
    "NVDA": {"price": 880.00, "pct_change": 5.2},
}
NEWS = {
    "__general__": ["Tech sector rallies on AI optimism", "Inflation data beats estimates"],
    "MSFT": ["Microsoft announces $10B AI investment"],
    "AAPL": ["Apple services revenue hits record"],
    "NVDA": ["Nvidia GPU demand surges on data center orders"],
}


# --- market session ---

def test_market_session_premarket():
    assert get_market_session(datetime(2026, 4, 26, 6, 0, tzinfo=ET)) == "pre-market"

def test_market_session_regular():
    assert get_market_session(datetime(2026, 4, 26, 11, 0, tzinfo=ET)) == "regular"

def test_market_session_after_hours():
    assert get_market_session(datetime(2026, 4, 26, 17, 0, tzinfo=ET)) == "after-hours"

def test_market_session_closed():
    assert get_market_session(datetime(2026, 4, 26, 22, 0, tzinfo=ET)) == "closed"

def test_market_session_closed_early_morning():
    assert get_market_session(datetime(2026, 4, 26, 2, 0, tzinfo=ET)) == "closed"


# --- prompt structure ---

def test_prompt_has_all_holdings():
    prompt = build_prompt(PORTFOLIO, PRICES, NEWS)
    assert "MSFT" in prompt
    assert "AAPL" in prompt

def test_prompt_shows_pnl_for_holdings():
    prompt = build_prompt(PORTFOLIO, PRICES, NEWS)
    assert "P&L" in prompt

def test_prompt_shows_week_change():
    prompt = build_prompt(PORTFOLIO, PRICES, NEWS)
    assert "5d" in prompt

def test_prompt_shows_general_news():
    prompt = build_prompt(PORTFOLIO, PRICES, NEWS)
    assert "Tech sector rallies on AI optimism" in prompt
    assert "Inflation data beats estimates" in prompt

def test_prompt_shows_holding_specific_news():
    prompt = build_prompt(PORTFOLIO, PRICES, NEWS)
    assert "Microsoft announces $10B AI investment" in prompt
    assert "Apple services revenue hits record" in prompt

def test_prompt_shows_opportunity_ticker():
    prompt = build_prompt(PORTFOLIO, PRICES, NEWS)
    assert "NVDA" in prompt

def test_prompt_no_headlines_placeholder():
    news = {**NEWS, "MSFT": []}
    prompt = build_prompt(PORTFOLIO, PRICES, news)
    assert "No recent headlines" in prompt

def test_prompt_cash_percentage_shown():
    prompt = build_prompt(PORTFOLIO, PRICES, NEWS)
    assert "%" in prompt

def test_prompt_bought_pct_shown():
    prompt = build_prompt(PORTFOLIO, PRICES, NEWS)
    assert "10%" in prompt or "bought at 10" in prompt

def test_prompt_session_regular_note():
    prompt = build_prompt(PORTFOLIO, PRICES, NEWS, market_session="regular")
    assert "regular" in prompt

def test_prompt_session_premarket_note():
    prompt = build_prompt(PORTFOLIO, PRICES, NEWS, market_session="pre-market")
    assert "pre-market" in prompt

def test_prompt_session_closed_note():
    prompt = build_prompt(PORTFOLIO, PRICES, NEWS, market_session="closed")
    assert "closed" in prompt.lower()

def test_prompt_no_watchlist():
    prompt = build_prompt(PORTFOLIO, PRICES, NEWS)
    assert "WATCHLIST" not in prompt

def test_prompt_task_section_present():
    prompt = build_prompt(PORTFOLIO, PRICES, NEWS)
    assert "TASK" in prompt
