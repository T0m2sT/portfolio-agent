import logging

import yfinance as yf
import requests

logger = logging.getLogger(__name__)


def fetch_prices(tickers: list[str]) -> dict[str, dict]:
    """Fetch live prices from Yahoo Finance.

    Returns a mapping of ticker -> {"price": float, "pct_change": float}.
    Tickers with missing data are silently skipped.
    Never raises — returns an empty dict on complete failure.
    """
    prices = {}
    for ticker in tickers:
        try:
            t = yf.Ticker(ticker)
            last = t.fast_info.last_price
            prev = t.fast_info.previous_close
            if last is None or prev is None or prev == 0:
                continue
            pct = ((last - prev) / prev) * 100
            prices[ticker] = {"price": round(last, 2), "pct_change": round(pct, 1)}
        except Exception as exc:
            logger.warning("fetch_prices failed for %s: %r", ticker, exc)
            continue
    return prices


def fetch_news(tickers: list[str], api_key: str) -> dict[str, list[str]]:
    """Fetch the latest headlines for each ticker from NewsAPI.

    Returns a mapping of ticker -> [headline, ...] (up to 3 per ticker).
    On any error (network, non-200 status, parse failure) the ticker
    maps to an empty list.  Never raises.

    Args:
        tickers: List of ticker symbols to search for.
        api_key: NewsAPI key supplied by the caller (must come from an
                 environment variable — never hardcode).
    """
    news: dict[str, list[str]] = {}
    for ticker in tickers:
        try:
            resp = requests.get(
                "https://newsapi.org/v2/everything",
                params={
                    "q": ticker,
                    "pageSize": 3,
                    "sortBy": "publishedAt",
                    "apiKey": api_key,
                },
                timeout=10,
            )
            if resp.status_code != 200:
                news[ticker] = []
                continue
            articles = resp.json().get("articles", [])
            news[ticker] = [a["title"] for a in articles[:3]]
        except Exception as exc:
            logger.warning("fetch_news failed for %s: %r", ticker, exc)
            news[ticker] = []
    return news
