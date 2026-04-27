import json
import pytest
from agent.portfolio import load_portfolio, save_portfolio, apply_action

SAMPLE = {
    "cash": 4000.00,
    "holdings": [
        {
            "ticker": "NVDA",
            "shares": 0.25,
            "avg_buy_price_usd": 110.00,
            "total_cost_eur": 200.00,
            "bought_pct": 20,
        }
    ],
    "last_run": None,
    "last_alert": None,
    "trade_log": [],
}


def test_load_portfolio(tmp_path):
    p = tmp_path / "portfolio.json"
    p.write_text(json.dumps(SAMPLE))
    result = load_portfolio(str(p))
    assert result["cash"] == 4000.00
    assert result["holdings"][0]["ticker"] == "NVDA"

def test_save_portfolio_sets_last_run(tmp_path):
    p = tmp_path / "portfolio.json"
    save_portfolio(SAMPLE, str(p))
    loaded = json.loads(p.read_text())
    assert loaded["last_run"] is not None
    assert "T" in loaded["last_run"]

def test_apply_action_hold():
    result = apply_action(SAMPLE, {"ticker": "NVDA", "action": "HOLD"})
    assert result["holdings"][0]["ticker"] == "NVDA"
    assert result["cash"] == 4000.00

def test_apply_action_sell_partial():
    portfolio = {
        **SAMPLE,
        "cash": 0.00,
        "holdings": [{"ticker": "NVDA", "shares": 1.0, "avg_buy_price_usd": 100.00, "total_cost_eur": 100.00, "bought_pct": 50}],
    }
    result = apply_action(portfolio, {
        "ticker": "NVDA", "action": "SELL", "amount": "50%",
        "price_usd": 120.00, "proceeds_eur": 60.00,
    })
    assert round(result["cash"], 2) == 60.00
    assert round(result["holdings"][0]["shares"], 4) == 0.5

def test_apply_action_sell_all_removes_holding():
    portfolio = {
        **SAMPLE,
        "cash": 0.00,
        "holdings": [{"ticker": "NVDA", "shares": 1.0, "avg_buy_price_usd": 100.00, "total_cost_eur": 100.00, "bought_pct": 50}],
    }
    result = apply_action(portfolio, {
        "ticker": "NVDA", "action": "SELL", "amount": "ALL",
        "price_usd": 120.00, "proceeds_eur": 120.00,
    })
    assert round(result["cash"], 2) == 120.00
    assert len(result["holdings"]) == 0

def test_apply_action_buy_new_position():
    portfolio = {**SAMPLE, "cash": 500.00, "holdings": []}
    result = apply_action(portfolio, {
        "action": "BUY", "ticker": "TSLA", "shares": 0.5,
        "price_usd": 250.00, "cost_eur": 120.00, "bought_pct": 10,
    })
    assert round(result["cash"], 2) == 380.00
    assert result["holdings"][0]["ticker"] == "TSLA"
    assert result["holdings"][0]["bought_pct"] == 10

def test_apply_action_buy_weighted_avg():
    portfolio = {
        **SAMPLE,
        "cash": 1000.00,
        "holdings": [{"ticker": "TSLA", "shares": 1.0, "avg_buy_price_usd": 200.00, "total_cost_eur": 190.00, "bought_pct": 10}],
    }
    result = apply_action(portfolio, {
        "action": "BUY", "ticker": "TSLA", "shares": 1.0,
        "price_usd": 300.00, "cost_eur": 280.00, "bought_pct": 15,
    })
    holding = result["holdings"][0]
    assert holding["avg_buy_price_usd"] == 250.00
    assert round(holding["shares"], 1) == 2.0

def test_apply_action_buy_deducts_cash():
    portfolio = {**SAMPLE, "cash": 1000.00, "holdings": []}
    result = apply_action(portfolio, {
        "action": "BUY", "ticker": "AMD", "shares": 2.0,
        "price_usd": 120.00, "cost_eur": 225.00, "bought_pct": 5,
    })
    assert round(result["cash"], 2) == 775.00

def test_apply_action_short_sell_not_held():
    portfolio = {**SAMPLE, "cash": 500.00, "holdings": [], "trade_log": []}
    result = apply_action(portfolio, {
        "ticker": "TSLA", "action": "SELL", "amount": "2",
        "price_usd": 250.00, "proceeds_eur": 46.00,
    })
    assert round(result["cash"], 2) == 546.00
    assert len(result["holdings"]) == 0
    trade = result["trade_log"][-1]
    assert trade["short"] is True
    assert trade["proceeds_eur"] == 46.00

def test_apply_action_sell_logs_trade():
    portfolio = {
        **SAMPLE,
        "cash": 0.00,
        "holdings": [{"ticker": "NVDA", "shares": 1.0, "avg_buy_price_usd": 100.00, "total_cost_eur": 90.00, "bought_pct": 20}],
        "trade_log": [],
    }
    result = apply_action(portfolio, {
        "ticker": "NVDA", "action": "SELL", "amount": "ALL",
        "price_usd": 130.00, "proceeds_eur": 120.00,
    })
    assert len(result["trade_log"]) == 1
    trade = result["trade_log"][0]
    assert trade["ticker"] == "NVDA"
    assert trade["pnl"] == 30.00
    assert trade["short"] is False
