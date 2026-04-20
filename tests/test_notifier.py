import pytest
from agent.notifier import format_alert, format_portfolio

def test_format_alert_sell():
    action = {"ticker": "NVDA", "action": "SELL", "amount": "30%", "headline": "Export controls hit chip stocks", "reasoning": "Risk elevated short-term."}
    prices = {"NVDA": {"price": 118.40, "pct_change": -4.2}}
    msg = format_alert(action, prices)
    assert "SELL 30%" in msg
    assert "NVDA" in msg
    assert "118.40" in msg
    assert "-4.2%" in msg
    assert "Export controls" in msg
    assert "/reason" in msg

def test_format_alert_hold():
    action = {"ticker": "SPY", "action": "HOLD", "reasoning": "Stable trend."}
    prices = {"SPY": {"price": 520.00, "pct_change": 0.3}}
    msg = format_alert(action, prices)
    assert "HOLD" in msg
    assert "SPY" in msg
    assert "/reason" in msg

def test_format_alert_buy():
    action = {"ticker": "TSLA", "action": "BUY", "amount": "23.40", "headline": "Tesla new model launch", "reasoning": "Momentum building."}
    prices = {"TSLA": {"price": 234.00, "pct_change": 2.1}}
    msg = format_alert(action, prices)
    assert "BUY €23.40" in msg
    assert "TSLA" in msg

def test_format_portfolio():
    portfolio = {
        "cash": 23.40,
        "holdings": [{"ticker": "NVDA", "shares": 0.25, "avg_buy_price": 110.00, "last_price": 118.40}],
        "watchlist": ["AMD"],
        "last_run": "2026-04-20T12:00:00+00:00"
    }
    msg = format_portfolio(portfolio)
    assert "NVDA" in msg
    assert "23.40" in msg
    assert "P&L" in msg
