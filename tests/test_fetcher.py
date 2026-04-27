import pytest
import pandas as pd
from unittest.mock import patch, MagicMock
from agent.fetcher import fetch_prices, fetch_news

FULL_HIST = pd.DataFrame({
    "Close": [100.00, 102.00, 101.00, 103.00, 105.00],
    "High":  [101.00, 103.00, 102.00, 104.00, 106.00],
    "Low":   [99.00,  101.00, 100.00, 102.00, 104.00],
})


def test_fetch_prices_returns_dict():
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = FULL_HIST
    with patch("agent.fetcher.yf.Ticker", return_value=mock_ticker):
        result = fetch_prices(["NVDA"])
    assert "NVDA" in result
    assert result["NVDA"]["price"] == 105.00
    assert "week_high" in result["NVDA"]
    assert "week_low" in result["NVDA"]

def test_fetch_prices_handles_missing_ticker():
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = pd.DataFrame({"Close": []})
    with patch("agent.fetcher.yf.Ticker", return_value=mock_ticker):
        result = fetch_prices(["FAKE"])
    assert result == {}

def test_fetch_prices_handles_exception():
    with patch("agent.fetcher.yf.Ticker", side_effect=Exception("network error")):
        result = fetch_prices(["NVDA"])
    assert result == {}

def test_fetch_news_returns_general_key(requests_mock):
    requests_mock.get("https://newsapi.org/v2/everything", json={"articles": [{"title": "Market rallies"}]})
    result = fetch_news([], news_api_key="test-key")
    assert "__general__" in result

def test_fetch_news_returns_headlines_for_ticker(requests_mock):
    requests_mock.get(
        "https://newsapi.org/v2/everything",
        json={"articles": [
            {"title": "NVDA soars on AI demand"},
            {"title": "Export restrictions hit chip stocks"},
            {"title": "Analysts raise NVDA target"},
        ]}
    )
    result = fetch_news(["NVDA"], news_api_key="test-key")
    assert "NVDA" in result
    assert any("NVDA" in h or "chip" in h or "Analysts" in h for h in result["NVDA"])

def test_fetch_news_empty_on_http_error(requests_mock):
    requests_mock.get("https://newsapi.org/v2/everything", status_code=429)
    result = fetch_news(["NVDA"], news_api_key="test-key")
    assert result.get("NVDA", []) == []

def test_fetch_news_handles_exception(requests_mock):
    requests_mock.get("https://newsapi.org/v2/everything", exc=Exception("connection error"))
    result = fetch_news(["NVDA"], news_api_key="test-key")
    assert result.get("NVDA", []) == []
