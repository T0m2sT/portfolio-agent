import logging
import requests
import yfinance as yf
from datetime import date, timedelta

logger = logging.getLogger(__name__)

_FINNHUB_URL = "https://finnhub.io/api/v1"

# Broad market tickers to always fetch news for — covers major indices, sectors, macro
_MARKET_PULSE_TICKERS = [
    "SPY", "QQQ", "IWM",       # broad market
    "GLD", "SLV", "USO",       # commodities
    "BTC-USD", "ETH-USD",      # crypto
    "TLT", "HYG",              # bonds
]

# General market search terms for NewsAPI
_GENERAL_QUERIES = ["stock market", "S&P 500", "Fed interest rates", "earnings", "AI stocks"]


def fetch_prices(tickers: list[str], api_key: str = None) -> dict[str, dict]:
    """Fetch real-time prices for a list of tickers.

    Returns ticker -> {price, pct_change, week_pct, day_high, day_low, week_high, week_low}.
    Uses Finnhub if api_key provided, falls back to yfinance.
    Never raises.
    """
    prices = {}

    if api_key:
        for ticker in tickers:
            try:
                resp = requests.get(
                    f"{_FINNHUB_URL}/quote",
                    params={"symbol": ticker, "token": api_key},
                    timeout=10,
                )
                if resp.status_code != 200:
                    logger.warning("fetch_prices (Finnhub): HTTP %d for %s", resp.status_code, ticker)
                    continue

                data = resp.json()
                if "c" not in data or data["c"] == 0:
                    continue

                current = float(data["c"])
                open_price = float(data.get("o", 0))
                prev_close = float(data.get("pc", 0))
                day_high = float(data.get("h", 0))
                day_low = float(data.get("l", 0))

                ref = open_price if open_price else prev_close
                pct = ((current - ref) / ref * 100) if ref else 0

                entry: dict = {
                    "price": round(current, 2),
                    "pct_change": round(pct, 1),
                    "day_high": round(day_high, 2),
                    "day_low": round(day_low, 2),
                }

                try:
                    t = yf.Ticker(ticker)
                    hist = t.history(period="5d")
                    if not hist.empty and len(hist) >= 2:
                        entry["week_high"] = round(float(hist["High"].max()), 2)
                        entry["week_low"] = round(float(hist["Low"].min()), 2)
                        week_ago = float(hist["Close"].iloc[0])
                        entry["week_pct"] = round((current - week_ago) / week_ago * 100, 1) if week_ago else 0
                except Exception as exc:
                    logger.warning("fetch_prices: yfinance 5d enrichment failed for %s: %r", ticker, exc)

                prices[ticker] = entry
            except Exception as exc:
                logger.warning("fetch_prices (Finnhub) failed for %s: %r", ticker, exc)

        if prices:
            return prices

    logger.info("Falling back to yfinance for price data")
    for ticker in tickers:
        try:
            t = yf.Ticker(ticker)
            hist = t.history(period="5d")
            if hist.empty or len(hist) < 2:
                continue

            prev_close = float(hist["Close"].iloc[-2])
            week_ago = float(hist["Close"].iloc[0])

            try:
                intraday = t.history(period="1d", interval="1m")
                last = float(intraday["Close"].iloc[-1]) if not intraday.empty else float(hist["Close"].iloc[-1])
            except Exception:
                last = float(hist["Close"].iloc[-1])

            if prev_close == 0:
                continue

            pct = (last - prev_close) / prev_close * 100
            prices[ticker] = {
                "price": round(last, 2),
                "pct_change": round(pct, 1),
                "week_pct": round((last - week_ago) / week_ago * 100, 1) if week_ago else 0,
                "week_high": round(float(hist["High"].max()), 2),
                "week_low": round(float(hist["Low"].min()), 2),
                "day_high": round(float(hist["High"].iloc[-1]), 2),
                "day_low": round(float(hist["Low"].iloc[-1]), 2),
            }
        except Exception as exc:
            logger.warning("fetch_prices failed for %s: %r", ticker, exc)

    return prices


def fetch_news(
    held_tickers: list[str],
    news_api_key: str,
    finnhub_key: str = None,
) -> dict[str, list[str]]:
    """Fetch broad market news plus per-ticker news for held positions.

    Returns:
      "__general__": up to 20 broad market headlines
      <ticker>: up to 8 headlines per held ticker
      <market_pulse_ticker>: up to 5 headlines for SPY/QQQ/BTC etc.

    Never raises.
    """
    today = date.today().isoformat()
    week_ago = (date.today() - timedelta(days=7)).isoformat()

    news: dict[str, list[str]] = {}

    # --- General market headlines via NewsAPI ---
    general: list[str] = []
    if news_api_key:
        for query in _GENERAL_QUERIES:
            try:
                resp = requests.get(
                    "https://newsapi.org/v2/everything",
                    params={
                        "q": query,
                        "pageSize": 5,
                        "sortBy": "publishedAt",
                        "language": "en",
                        "apiKey": news_api_key,
                    },
                    timeout=10,
                )
                if resp.status_code == 200:
                    articles = resp.json().get("articles", [])
                    for a in articles[:5]:
                        title = a.get("title", "")
                        if title and title not in general:
                            general.append(title)
            except Exception as exc:
                logger.warning("fetch_news general query '%s' failed: %r", query, exc)
    news["__general__"] = general[:20]

    # --- Per-ticker: held positions (8 headlines each) ---
    all_tickers = list(dict.fromkeys(held_tickers + _MARKET_PULSE_TICKERS))
    limit_map = {t: 8 for t in held_tickers}
    for t in _MARKET_PULSE_TICKERS:
        limit_map.setdefault(t, 5)

    for ticker in all_tickers:
        limit = limit_map.get(ticker, 5)
        headlines: list[str] = []

        if finnhub_key:
            try:
                resp = requests.get(
                    f"{_FINNHUB_URL}/company-news",
                    params={"symbol": ticker, "from": week_ago, "to": today, "token": finnhub_key},
                    timeout=10,
                )
                if resp.status_code == 200:
                    articles = resp.json()
                    headlines = [a["headline"] for a in articles[:limit] if a.get("headline")]
            except Exception as exc:
                logger.warning("fetch_news (Finnhub) failed for %s: %r", ticker, exc)

        if not headlines and news_api_key:
            try:
                resp = requests.get(
                    "https://newsapi.org/v2/everything",
                    params={
                        "q": ticker,
                        "pageSize": limit,
                        "sortBy": "publishedAt",
                        "language": "en",
                        "apiKey": news_api_key,
                    },
                    timeout=10,
                )
                if resp.status_code == 200:
                    articles = resp.json().get("articles", [])
                    headlines = [a["title"] for a in articles[:limit] if a.get("title")]
            except Exception as exc:
                logger.warning("fetch_news (NewsAPI) failed for %s: %r", ticker, exc)

        if headlines:
            news[ticker] = headlines

    return news


from agent.session import is_us_trading_day  # re-exported for backward compat
