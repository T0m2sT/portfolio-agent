import pytest
from unittest.mock import patch, MagicMock
from agent.fetcher import fetch_prices, fetch_news

def test_fetch_prices_returns_dict():
    mock_ticker = MagicMock()
    mock_ticker.fast_info.last_price = 118.40
    mock_ticker.fast_info.previous_close = 123.58
    with patch("agent.fetcher.yf.Ticker", return_value=mock_ticker):
        result = fetch_prices(["NVDA"])
    assert "NVDA" in result
    assert result["NVDA"]["price"] == 118.40
    assert round(result["NVDA"]["pct_change"], 2) == -4.2

def test_fetch_prices_handles_missing_ticker():
    mock_ticker = MagicMock()
    mock_ticker.fast_info.last_price = None
    with patch("agent.fetcher.yf.Ticker", return_value=mock_ticker):
        result = fetch_prices(["FAKE"])
    assert result == {}

def test_fetch_news_returns_headlines(requests_mock):
    requests_mock.get(
        "https://newsapi.org/v2/everything",
        json={
            "articles": [
                {"title": "NVDA soars on AI demand", "publishedAt": "2026-04-20T10:00:00Z"},
                {"title": "Export restrictions hit chip stocks", "publishedAt": "2026-04-20T09:00:00Z"},
                {"title": "Analysts raise NVDA target", "publishedAt": "2026-04-20T08:00:00Z"},
            ]
        }
    )
    result = fetch_news(["NVDA"], api_key="test-key")
    assert "NVDA" in result
    assert len(result["NVDA"]) == 3
    assert result["NVDA"][0] == "NVDA soars on AI demand"

def test_fetch_news_returns_empty_on_error(requests_mock):
    requests_mock.get("https://newsapi.org/v2/everything", status_code=429)
    result = fetch_news(["NVDA"], api_key="test-key")
    assert result == {"NVDA": []}

def test_fetch_prices_handles_exception():
    with patch("agent.fetcher.yf.Ticker", side_effect=Exception("network error")):
        result = fetch_prices(["NVDA"])
    assert result == {}

def test_fetch_news_handles_exception(requests_mock):
    requests_mock.get(
        "https://newsapi.org/v2/everything",
        exc=Exception("connection error")
    )
    result = fetch_news(["NVDA"], api_key="test-key")
    assert result == {"NVDA": []}
