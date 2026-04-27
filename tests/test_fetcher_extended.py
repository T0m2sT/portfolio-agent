import pytest
import pandas as pd
from unittest.mock import patch, MagicMock
from agent.fetcher import fetch_prices, fetch_news, is_us_trading_day
from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

FULL_HIST = pd.DataFrame({
    "Close": [100.00, 102.00, 101.00, 103.00, 105.00],
    "High":  [101.00, 103.00, 102.00, 104.00, 106.00],
    "Low":   [99.00,  101.00, 100.00, 102.00, 104.00],
})


# --- is_us_trading_day ---

def test_is_us_trading_day_weekday_no_holiday(requests_mock):
    requests_mock.get("https://finnhub.io/api/v1/stock/market-holiday", json={"data": []})
    assert is_us_trading_day(api_key="test", now=datetime(2026, 4, 28, 10, 0, tzinfo=ET)) is True

def test_is_us_trading_day_holiday(requests_mock):
    requests_mock.get(
        "https://finnhub.io/api/v1/stock/market-holiday",
        json={"data": [{"atDate": "2026-07-03"}]},
    )
    assert is_us_trading_day(api_key="test", now=datetime(2026, 7, 3, 10, 0, tzinfo=ET)) is False

def test_is_us_trading_day_weekend_no_api():
    assert is_us_trading_day(api_key=None, now=datetime(2026, 4, 26, 10, 0, tzinfo=ET)) is False

def test_is_us_trading_day_weekday_no_api():
    assert is_us_trading_day(api_key=None, now=datetime(2026, 4, 28, 10, 0, tzinfo=ET)) is True

def test_is_us_trading_day_finnhub_failure_assumes_open(requests_mock):
    requests_mock.get("https://finnhub.io/api/v1/stock/market-holiday", exc=Exception("timeout"))
    assert is_us_trading_day(api_key="test", now=datetime(2026, 4, 28, 10, 0, tzinfo=ET)) is True


# --- fetch_prices via Finnhub ---

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
    assert round(result["AAPL"]["pct_change"], 1) == round((100 - 95) / 95 * 100, 1)

def test_fetch_prices_finnhub_skips_zero_price(requests_mock):
    requests_mock.get(
        "https://finnhub.io/api/v1/quote",
        json={"c": 0, "o": 0, "h": 0, "l": 0, "pc": 0},
    )
    result = fetch_prices(["FAKE"], api_key="test")
    assert result == {}

def test_fetch_prices_finnhub_5d_enrichment_failure_still_returns(requests_mock):
    requests_mock.get(
        "https://finnhub.io/api/v1/quote",
        json={"c": 880.00, "o": 870.00, "h": 885.00, "l": 865.00, "pc": 860.00},
    )
    mock_ticker = MagicMock()
    mock_ticker.history.side_effect = Exception("yfinance down")
    with patch("agent.fetcher.yf.Ticker", return_value=mock_ticker):
        result = fetch_prices(["NVDA"], api_key="test")
    assert "NVDA" in result
    assert result["NVDA"]["price"] == 880.00
    assert "week_pct" not in result["NVDA"]

def test_fetch_prices_yfinance_week_fields():
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = FULL_HIST
    with patch("agent.fetcher.yf.Ticker", return_value=mock_ticker):
        result = fetch_prices(["TSLA"])
    assert "TSLA" in result
    assert result["TSLA"]["week_high"] == 106.00
    assert result["TSLA"]["week_low"] == 99.00


# --- fetch_news ---

def test_fetch_news_uses_finnhub_primary(requests_mock):
    requests_mock.get(
        "https://finnhub.io/api/v1/company-news",
        json=[
            {"headline": "NVDA beats earnings", "datetime": 1700000000},
            {"headline": "NVDA raises guidance", "datetime": 1699990000},
        ],
    )
    result = fetch_news(["NVDA"], news_api_key="newsapi-key", finnhub_key="finnhub-key")
    assert "NVDA" in result
    assert result["NVDA"][0] == "NVDA beats earnings"

def test_fetch_news_falls_back_to_newsapi_when_finnhub_empty(requests_mock):
    requests_mock.get("https://finnhub.io/api/v1/company-news", json=[])
    requests_mock.get(
        "https://newsapi.org/v2/everything",
        json={"articles": [{"title": "NVDA headline from newsapi"}]},
    )
    result = fetch_news(["NVDA"], news_api_key="newsapi-key", finnhub_key="finnhub-key")
    assert result.get("NVDA", [""])[0] == "NVDA headline from newsapi"

def test_fetch_news_falls_back_to_newsapi_when_finnhub_fails(requests_mock):
    requests_mock.get("https://finnhub.io/api/v1/company-news", exc=Exception("timeout"))
    requests_mock.get(
        "https://newsapi.org/v2/everything",
        json={"articles": [{"title": "fallback headline"}]},
    )
    result = fetch_news(["NVDA"], news_api_key="newsapi-key", finnhub_key="finnhub-key")
    assert result.get("NVDA", [""])[0] == "fallback headline"

def test_fetch_news_general_key_always_present(requests_mock):
    requests_mock.get("https://newsapi.org/v2/everything", json={"articles": []})
    result = fetch_news([], news_api_key="newsapi-key")
    assert "__general__" in result

def test_fetch_news_no_finnhub_key_uses_newsapi_only(requests_mock):
    requests_mock.get(
        "https://newsapi.org/v2/everything",
        json={"articles": [{"title": "newsapi only"}]},
    )
    result = fetch_news(["AAPL"], news_api_key="newsapi-key", finnhub_key=None)
    assert result.get("AAPL", [""])[0] == "newsapi only"
