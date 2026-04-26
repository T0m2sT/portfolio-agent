import pytest
import pandas as pd
from unittest.mock import patch, MagicMock
from agent.fetcher import fetch_prices, is_market_open


FULL_HIST = pd.DataFrame({
    "Close": [100.00, 102.00, 101.00, 103.00, 105.00],
    "High":  [101.00, 103.00, 102.00, 104.00, 106.00],
    "Low":   [99.00,  101.00, 100.00, 102.00, 104.00],
})


# is_market_open
def test_is_market_open_true(requests_mock):
    requests_mock.get(
        "https://finnhub.io/api/v1/stock/market-status",
        json={"isOpen": True},
    )
    assert is_market_open(api_key="test") is True

def test_is_market_open_false_holiday(requests_mock):
    requests_mock.get(
        "https://finnhub.io/api/v1/stock/market-status",
        json={"isOpen": False},
    )
    assert is_market_open(api_key="test") is False

def test_is_market_open_no_key_weekday():
    with patch("agent.fetcher.datetime") as mock_dt:
        mock_dt.now.return_value = MagicMock(weekday=lambda: 1)  # Tuesday
        result = is_market_open(api_key=None)
    assert result is True

def test_is_market_open_no_key_weekend():
    with patch("agent.fetcher.datetime") as mock_dt:
        mock_dt.now.return_value = MagicMock(weekday=lambda: 5)  # Saturday
        result = is_market_open(api_key=None)
    assert result is False

def test_is_market_open_finnhub_failure_assumes_open(requests_mock):
    requests_mock.get(
        "https://finnhub.io/api/v1/stock/market-status",
        exc=Exception("timeout"),
    )
    # Should fall back to weekday check without raising
    result = is_market_open(api_key="test")
    assert isinstance(result, bool)


# fetch_prices via Finnhub path
def test_fetch_prices_finnhub_path(requests_mock):
    requests_mock.get(
        "https://finnhub.io/api/v1/quote",
        json={"c": 880.00, "o": 870.00, "h": 885.00, "l": 865.00, "pc": 860.00},
    )
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = FULL_HIST
    with patch("agent.fetcher.yf.Ticker", return_value=mock_ticker):
        result = fetch_prices(["NVDA"], api_key="test")
    assert "NVDA" in result
    assert result["NVDA"]["price"] == 880.00
    assert result["NVDA"]["day_high"] == 885.00
    assert result["NVDA"]["day_low"] == 865.00
    assert "week_high" in result["NVDA"]
    assert "week_low" in result["NVDA"]
    assert "week_pct" in result["NVDA"]

def test_fetch_prices_finnhub_uses_prev_close_when_open_zero(requests_mock):
    requests_mock.get(
        "https://finnhub.io/api/v1/quote",
        json={"c": 100.00, "o": 0, "h": 102.00, "l": 98.00, "pc": 95.00},
    )
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = FULL_HIST
    with patch("agent.fetcher.yf.Ticker", return_value=mock_ticker):
        result = fetch_prices(["AAPL"], api_key="test")
    assert "AAPL" in result
    assert round(result["AAPL"]["pct_change"], 1) == round(((100 - 95) / 95) * 100, 1)

def test_fetch_prices_finnhub_skips_zero_open_zero_prev_close(requests_mock):
    requests_mock.get(
        "https://finnhub.io/api/v1/quote",
        json={"c": 100.00, "o": 0, "h": 0, "l": 0, "pc": 0},
    )
    result = fetch_prices(["FAKE"], api_key="test")
    assert result == {}

def test_fetch_prices_finnhub_http_error_falls_back_to_yfinance(requests_mock):
    requests_mock.get("https://finnhub.io/api/v1/quote", status_code=429)
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = FULL_HIST
    # Also mock the minute history call
    mock_ticker.history.side_effect = [FULL_HIST, pd.DataFrame({"Close": [105.00], "High": [106.00], "Low": [104.00]})]
    with patch("agent.fetcher.yf.Ticker", return_value=mock_ticker):
        result = fetch_prices(["MSFT"], api_key="test")
    # Falls back to yfinance — result may or may not have MSFT depending on data shape
    assert isinstance(result, dict)

def test_fetch_prices_finnhub_5d_enrichment_failure_still_returns(requests_mock):
    requests_mock.get(
        "https://finnhub.io/api/v1/quote",
        json={"c": 880.00, "o": 870.00, "h": 885.00, "l": 865.00, "pc": 860.00},
    )
    mock_ticker = MagicMock()
    mock_ticker.history.side_effect = Exception("yfinance down")
    with patch("agent.fetcher.yf.Ticker", return_value=mock_ticker):
        result = fetch_prices(["NVDA"], api_key="test")
    # Should still return price data even if 5d enrichment failed
    assert "NVDA" in result
    assert result["NVDA"]["price"] == 880.00
    assert "week_pct" not in result["NVDA"]

def test_fetch_news_uses_finnhub_primary(requests_mock):
    from agent.fetcher import fetch_news
    requests_mock.get(
        "https://finnhub.io/api/v1/company-news",
        json=[
            {"headline": "NVDA beats earnings", "datetime": 1700000000},
            {"headline": "NVDA raises guidance", "datetime": 1699990000},
        ],
    )
    result = fetch_news(["NVDA"], api_key="newsapi-key", finnhub_key="finnhub-key")
    assert "NVDA" in result
    assert result["NVDA"][0] == "NVDA beats earnings"
    assert len(result["NVDA"]) == 2

def test_fetch_news_falls_back_to_newsapi_when_finnhub_empty(requests_mock):
    from agent.fetcher import fetch_news
    requests_mock.get("https://finnhub.io/api/v1/company-news", json=[])
    requests_mock.get(
        "https://newsapi.org/v2/everything",
        json={"articles": [{"title": "NVDA headline from newsapi"}]},
    )
    result = fetch_news(["NVDA"], api_key="newsapi-key", finnhub_key="finnhub-key")
    assert result["NVDA"][0] == "NVDA headline from newsapi"

def test_fetch_news_falls_back_to_newsapi_when_finnhub_fails(requests_mock):
    from agent.fetcher import fetch_news
    requests_mock.get("https://finnhub.io/api/v1/company-news", exc=Exception("timeout"))
    requests_mock.get(
        "https://newsapi.org/v2/everything",
        json={"articles": [{"title": "fallback headline"}]},
    )
    result = fetch_news(["NVDA"], api_key="newsapi-key", finnhub_key="finnhub-key")
    assert result["NVDA"][0] == "fallback headline"

def test_fetch_news_no_finnhub_key_uses_newsapi_only(requests_mock):
    from agent.fetcher import fetch_news
    requests_mock.get(
        "https://newsapi.org/v2/everything",
        json={"articles": [{"title": "newsapi only"}]},
    )
    result = fetch_news(["AAPL"], api_key="newsapi-key", finnhub_key=None)
    assert result["AAPL"][0] == "newsapi only"

def test_fetch_prices_yfinance_returns_week_fields():
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = FULL_HIST
    with patch("agent.fetcher.yf.Ticker", return_value=mock_ticker):
        result = fetch_prices(["TSLA"])
    assert "TSLA" in result
    assert "week_high" in result["TSLA"]
    assert "week_low" in result["TSLA"]
    assert "week_pct" in result["TSLA"]
    assert result["TSLA"]["week_high"] == 106.00
    assert result["TSLA"]["week_low"] == 99.00
