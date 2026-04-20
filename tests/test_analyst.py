import pytest
from unittest.mock import patch, MagicMock
from agent.analyst import build_prompt, parse_response, analyse

SAMPLE_PORTFOLIO = {
    "cash": 23.40,
    "holdings": [{"ticker": "NVDA", "shares": 0.25, "avg_buy_price": 110.00, "last_price": 118.40}],
    "watchlist": ["AMD"],
    "last_run": None,
    "last_alert": None
}

SAMPLE_PRICES = {"NVDA": {"price": 118.40, "pct_change": -4.2}, "AMD": {"price": 95.00, "pct_change": 1.1}}
SAMPLE_NEWS = {"NVDA": ["Export controls hit Nvidia", "Analysts cut target"], "AMD": ["AMD gains market share"]}

def test_build_prompt_contains_ticker():
    prompt = build_prompt(SAMPLE_PORTFOLIO, SAMPLE_PRICES, SAMPLE_NEWS)
    assert "NVDA" in prompt
    assert "118.40" in prompt
    assert "Export controls hit Nvidia" in prompt
    assert "23.40" in prompt

def test_parse_response_valid():
    raw = '{"actions": [{"ticker": "NVDA", "action": "SELL", "amount": "30%", "headline": "Export controls", "reasoning": "Risk elevated"}], "watchlist_additions": [], "watchlist_removals": []}'
    result = parse_response(raw)
    assert result["actions"][0]["ticker"] == "NVDA"
    assert result["actions"][0]["action"] == "SELL"
    assert result["actions"][0]["amount"] == "30%"

def test_parse_response_strips_markdown():
    raw = '```json\n{"actions": [], "watchlist_additions": [], "watchlist_removals": []}\n```'
    result = parse_response(raw)
    assert result["actions"] == []

def test_parse_response_invalid_raises():
    with pytest.raises(ValueError):
        parse_response("not json at all")

def test_parse_response_strips_preamble_and_markdown():
    raw = 'Here is the JSON:\n```json\n{"actions": [], "watchlist_additions": [], "watchlist_removals": []}\n```'
    result = parse_response(raw)
    assert result["actions"] == []

def test_analyse_calls_claude(mocker):
    mock_client = MagicMock()
    mock_client.messages.create.return_value.content = [
        MagicMock(text='{"actions": [{"ticker": "NVDA", "action": "HOLD", "reasoning": "Stable"}], "watchlist_additions": [], "watchlist_removals": []}')
    ]
    mocker.patch("agent.analyst.anthropic.Anthropic", return_value=mock_client)
    result = analyse(SAMPLE_PORTFOLIO, SAMPLE_PRICES, SAMPLE_NEWS, api_key="test")
    assert result["actions"][0]["action"] == "HOLD"
