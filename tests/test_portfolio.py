import json
import pytest
from pathlib import Path
from agent.portfolio import load_portfolio, save_portfolio, compute_pnl, apply_action

SAMPLE = {
    "cash": 50.00,
    "holdings": [
        {"ticker": "NVDA", "shares": 0.25, "avg_buy_price": 110.00, "last_price": 118.40}
    ],
    "watchlist": ["AMD"],
    "last_run": None,
    "last_alert": None
}

def test_load_portfolio(tmp_path):
    p = tmp_path / "portfolio.json"
    p.write_text(json.dumps(SAMPLE))
    result = load_portfolio(str(p))
    assert result["cash"] == 50.00
    assert result["holdings"][0]["ticker"] == "NVDA"

def test_save_portfolio(tmp_path):
    p = tmp_path / "portfolio.json"
    save_portfolio(SAMPLE, str(p))
    loaded = json.loads(p.read_text())
    assert loaded["cash"] == 50.00

def test_compute_pnl():
    holding = {"ticker": "NVDA", "shares": 0.25, "avg_buy_price": 110.00, "last_price": 118.40}
    pnl = compute_pnl(holding)
    assert round(pnl, 2) == 2.10

def test_apply_action_hold():
    portfolio = dict(SAMPLE)
    result = apply_action(portfolio, {"ticker": "NVDA", "action": "HOLD"})
    assert result["holdings"][0]["ticker"] == "NVDA"
    assert result["cash"] == 50.00

def test_apply_action_sell_partial():
    portfolio = {
        "cash": 0.00,
        "holdings": [{"ticker": "NVDA", "shares": 1.0, "avg_buy_price": 100.00, "last_price": 120.00}],
        "watchlist": [], "last_run": None, "last_alert": None
    }
    result = apply_action(portfolio, {"ticker": "NVDA", "action": "SELL", "amount": "50%", "last_price": 120.00})
    assert round(result["cash"], 2) == 60.00
    assert round(result["holdings"][0]["shares"], 4) == 0.5

def test_apply_action_sell_all():
    portfolio = {
        "cash": 0.00,
        "holdings": [{"ticker": "NVDA", "shares": 1.0, "avg_buy_price": 100.00, "last_price": 120.00}],
        "watchlist": [], "last_run": None, "last_alert": None
    }
    result = apply_action(portfolio, {"ticker": "NVDA", "action": "SELL", "amount": "ALL", "last_price": 120.00})
    assert round(result["cash"], 2) == 120.00
    assert len(result["holdings"]) == 0

def test_apply_action_buy():
    portfolio = {
        "cash": 50.00,
        "holdings": [],
        "watchlist": ["TSLA"], "last_run": None, "last_alert": None
    }
    result = apply_action(portfolio, {"ticker": "TSLA", "action": "BUY", "amount": "23.40", "last_price": 234.00})
    assert round(result["cash"], 2) == 26.60
    assert result["holdings"][0]["ticker"] == "TSLA"
    assert round(result["holdings"][0]["shares"], 4) == 0.1
