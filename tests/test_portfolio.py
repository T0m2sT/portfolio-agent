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
    assert loaded["last_run"] is not None
    assert "T" in loaded["last_run"]

def test_compute_pnl():
    holding = {"ticker": "NVDA", "shares": 0.25, "avg_buy_price_usd": 110.00, "last_price_usd": 118.40}
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
        "holdings": [{"ticker": "NVDA", "shares": 1.0, "avg_buy_price_usd": 100.00, "total_cost_eur": 100.00}],
        "watchlist": [], "last_run": None, "last_alert": None
    }
    result = apply_action(portfolio, {"ticker": "NVDA", "action": "SELL", "amount": "50%", "price_usd": 120.00, "proceeds_eur": 60.00})
    assert round(result["cash"], 2) == 60.00
    assert round(result["holdings"][0]["shares"], 4) == 0.5

def test_apply_action_sell_all():
    portfolio = {
        "cash": 0.00,
        "holdings": [{"ticker": "NVDA", "shares": 1.0, "avg_buy_price_usd": 100.00, "total_cost_eur": 100.00}],
        "watchlist": [], "last_run": None, "last_alert": None
    }
    result = apply_action(portfolio, {"ticker": "NVDA", "action": "SELL", "amount": "ALL", "price_usd": 120.00, "proceeds_eur": 120.00})
    assert round(result["cash"], 2) == 120.00
    assert len(result["holdings"]) == 0

def test_apply_action_buy():
    portfolio = {
        "cash": 50.00,
        "holdings": [],
        "watchlist": ["TSLA"], "last_run": None, "last_alert": None
    }
    result = apply_action(portfolio, {"ticker": "TSLA", "action": "BUY", "shares": 0.1, "price_usd": 234.00, "cost_eur": 23.40})
    assert round(result["cash"], 2) == 26.60
    assert result["holdings"][0]["ticker"] == "TSLA"
    assert round(result["holdings"][0]["shares"], 4) == 0.1

def test_apply_action_buy_weighted_avg():
    portfolio = {
        "cash": 100.00,
        "holdings": [{"ticker": "TSLA", "shares": 1.0, "avg_buy_price_usd": 200.00, "total_cost_eur": 40.00}],
        "watchlist": [], "last_run": None, "last_alert": None
    }
    # Buy 1 more share at $300 — weighted avg should be (200*1 + 300*1) / 2 = $250
    result = apply_action(portfolio, {"ticker": "TSLA", "action": "BUY", "shares": 1.0, "price_usd": 300.00, "cost_eur": 55.00})
    holding = result["holdings"][0]
    assert holding["avg_buy_price_usd"] == 250.00
    assert round(holding["shares"], 1) == 2.0
    assert round(holding["total_cost_eur"], 2) == 95.00

def test_apply_action_short_sell_not_held():
    portfolio = {
        "cash": 50.00,
        "holdings": [],
        "watchlist": [], "last_run": None, "last_alert": None, "trade_log": []
    }
    result = apply_action(portfolio, {"ticker": "TSLA", "action": "SELL", "amount": "2", "price_usd": 250.00, "proceeds_eur": 46.00})
    assert round(result["cash"], 2) == 96.00
    assert len(result["holdings"]) == 0
    trade = result["trade_log"][-1]
    assert trade["ticker"] == "TSLA"
    assert trade["short"] is True
    assert trade["proceeds_eur"] == 46.00

def test_apply_action_short_sell_logged_in_trade_log():
    portfolio = {
        "cash": 0.00,
        "holdings": [],
        "watchlist": [], "last_run": None, "last_alert": None, "trade_log": []
    }
    result = apply_action(portfolio, {"ticker": "NVDA", "action": "SELL", "amount": "1", "price_usd": 900.00, "proceeds_eur": 83.00})
    assert len(result["trade_log"]) == 1
    assert result["trade_log"][0]["short"] is True
