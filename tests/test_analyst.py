import pytest
from unittest.mock import MagicMock
from agent.analyst import build_prompt, parse_response, analyse

PORTFOLIO = {
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
}
PRICES = {"NVDA": {"price": 118.40, "pct_change": -4.2, "week_pct": 2.1}}
NEWS = {
    "__general__": ["Fed holds rates steady", "S&P 500 rallies"],
    "NVDA": ["Export controls hit Nvidia", "Analysts cut target"],
}


def test_build_prompt_includes_holding_ticker():
    prompt = build_prompt(PORTFOLIO, PRICES, NEWS)
    assert "NVDA" in prompt

def test_build_prompt_includes_price():
    prompt = build_prompt(PORTFOLIO, PRICES, NEWS)
    assert "118.40" in prompt

def test_build_prompt_includes_cash():
    prompt = build_prompt(PORTFOLIO, PRICES, NEWS)
    assert "4000" in prompt

def test_build_prompt_includes_general_news():
    prompt = build_prompt(PORTFOLIO, PRICES, NEWS)
    assert "Fed holds rates steady" in prompt

def test_build_prompt_includes_holding_news():
    prompt = build_prompt(PORTFOLIO, PRICES, NEWS)
    assert "Export controls hit Nvidia" in prompt

def test_build_prompt_includes_avg_buy():
    prompt = build_prompt(PORTFOLIO, PRICES, NEWS)
    assert "avg buy $110.00" in prompt

def test_build_prompt_includes_bought_pct():
    prompt = build_prompt(PORTFOLIO, PRICES, NEWS)
    assert "20%" in prompt or "bought at 20" in prompt

def test_build_prompt_no_watchlist_section():
    prompt = build_prompt(PORTFOLIO, PRICES, NEWS)
    assert "WATCHLIST" not in prompt

def test_build_prompt_no_previous_signals_section():
    prompt = build_prompt(PORTFOLIO, PRICES, NEWS)
    assert "PREVIOUS SIGNALS" not in prompt

def test_build_prompt_empty_holdings_shows_cash_only():
    portfolio = {"cash": 5000.00, "holdings": []}
    prompt = build_prompt(portfolio, {}, {"__general__": []})
    assert "5000" in prompt

def test_build_prompt_opportunity_ticker_appears():
    news_with_opp = {**NEWS, "TSLA": ["Tesla beats delivery estimates"]}
    prices_with_opp = {**PRICES, "TSLA": {"price": 250.00, "pct_change": 3.5}}
    prompt = build_prompt(PORTFOLIO, prices_with_opp, news_with_opp)
    assert "TSLA" in prompt
    assert "OPPORTUNITIES" in prompt

def test_build_prompt_no_opp_section_when_none():
    prompt = build_prompt(PORTFOLIO, PRICES, NEWS)
    assert "None beyond current holdings" in prompt or "OPPORTUNITIES" in prompt

def test_parse_response_valid():
    raw = '{"actions": [{"ticker": "NVDA", "action": "SELL", "amount": "30%", "headline": "Export controls", "reasoning": "Risk elevated"}], "risks": []}'
    result = parse_response(raw)
    assert result["actions"][0]["ticker"] == "NVDA"
    assert result["actions"][0]["action"] == "SELL"
    assert result["actions"][0]["amount"] == "30%"

def test_parse_response_strips_markdown():
    raw = '```json\n{"actions": [], "risks": []}\n```'
    result = parse_response(raw)
    assert result["actions"] == []

def test_parse_response_invalid_raises():
    with pytest.raises(ValueError):
        parse_response("not json at all")

def test_analyse_calls_claude(mocker):
    mock_client = MagicMock()
    mock_client.messages.create.return_value.content = [
        MagicMock(text='{"actions": [{"ticker": "NVDA", "action": "HOLD", "reasoning": "Stable"}], "risks": []}')
    ]
    mock_client.messages.create.return_value.stop_reason = "end_turn"
    mocker.patch("agent.analyst.anthropic.Anthropic", return_value=mock_client)
    result = analyse(PORTFOLIO, PRICES, NEWS, api_key="test")
    assert result["actions"][0]["action"] == "HOLD"
