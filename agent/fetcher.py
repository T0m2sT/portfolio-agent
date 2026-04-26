import logging
import requests
import yfinance as yf

logger = logging.getLogger(__name__)

_TRENDING_URL = "https://query1.finance.yahoo.com/v1/finance/trending/US"
_FINNHUB_URL = "https://finnhub.io/api/v1"


def fetch_trending_tickers(limit: int = 10) -> list[str]:
    """Fetch trending tickers from Yahoo Finance's US trending endpoint.

    Returns up to `limit` ticker symbols currently trending on Yahoo Finance.
    Never raises — returns an empty list on any failure.
    """
    try:
        resp = requests.get(
            _TRENDING_URL,
            params={"count": limit, "lang": "en-US"},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        if resp.status_code != 200:
            logger.warning("fetch_trending_tickers: HTTP %d", resp.status_code)
            return []
        quotes = resp.json()["finance"]["result"][0]["quotes"]
        return [q["symbol"] for q in quotes[:limit] if "symbol" in q]
    except Exception as exc:
        logger.warning("fetch_trending_tickers failed: %r", exc)
        return []


from agent.session import is_us_trading_day  # re-exported for backward compat


def fetch_prices(tickers: list[str], api_key: str = None) -> dict[str, dict]:
    """Fetch real-time prices using Finnhub API with 5-day range and week-over-week change.

    Returns a mapping of ticker -> {
        "price": float (USD),
        "pct_change": float (vs today's open),
        "week_pct": float (vs 5 trading days ago close),
        "day_high": float,
        "day_low": float,
        "week_high": float,
        "week_low": float,
    }.
    Falls back to yfinance if Finnhub fails.
    Tickers with missing data are silently skipped.
    Never raises — returns an empty dict on complete failure.
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
                if "c" not in data or "o" not in data:
                    logger.warning("fetch_prices (Finnhub): missing price data for %s", ticker)
                    continue

                current_price = float(data["c"])
                open_price = float(data["o"])
                prev_close = float(data.get("pc", 0))
                day_high = float(data.get("h", 0))
                day_low = float(data.get("l", 0))

                if open_price == 0:
                    if prev_close == 0:
                        continue
                    pct = ((current_price - prev_close) / prev_close) * 100
                else:
                    pct = ((current_price - open_price) / open_price) * 100

                entry: dict = {
                    "price": round(current_price, 2),
                    "pct_change": round(pct, 1),
                    "day_high": round(day_high, 2),
                    "day_low": round(day_low, 2),
                }

                # Enrich with 5-day range via yfinance
                try:
                    t = yf.Ticker(ticker)
                    hist = t.history(period="5d")
                    if not hist.empty and len(hist) >= 2:
                        week_low = float(hist["Low"].min())
                        week_high = float(hist["High"].max())
                        week_ago_close = float(hist["Close"].iloc[0])
                        week_pct = ((current_price - week_ago_close) / week_ago_close) * 100 if week_ago_close else 0
                        entry["week_high"] = round(week_high, 2)
                        entry["week_low"] = round(week_low, 2)
                        entry["week_pct"] = round(week_pct, 1)
                except Exception as exc:
                    logger.warning("fetch_prices: yfinance 5d enrichment failed for %s: %r", ticker, exc)

                prices[ticker] = entry
            except Exception as exc:
                logger.warning("fetch_prices (Finnhub) failed for %s: %r", ticker, exc)
                continue

        if prices:
            return prices

    # Fallback to yfinance
    logger.info("Falling back to yfinance for price data")
    for ticker in tickers:
        try:
            t = yf.Ticker(ticker)
            hist_daily = t.history(period="5d")
            if hist_daily.empty or len(hist_daily) < 2:
                logger.warning("fetch_prices: no history data for %s", ticker)
                continue

            prev_close = float(hist_daily["Close"].iloc[-2])
            week_ago_close = float(hist_daily["Close"].iloc[0])

            try:
                hist_minute = t.history(period="1d", interval="1m")
                last_price = float(hist_minute["Close"].iloc[-1]) if not hist_minute.empty else float(hist_daily["Close"].iloc[-1])
            except Exception:
                last_price = float(hist_daily["Close"].iloc[-1])

            if prev_close == 0:
                continue

            pct = ((last_price - prev_close) / prev_close) * 100
            week_pct = ((last_price - week_ago_close) / week_ago_close) * 100 if week_ago_close else 0
            prices[ticker] = {
                "price": round(last_price, 2),
                "pct_change": round(pct, 1),
                "week_pct": round(week_pct, 1),
                "week_high": round(float(hist_daily["High"].max()), 2),
                "week_low": round(float(hist_daily["Low"].min()), 2),
                "day_high": round(float(hist_daily["High"].iloc[-1]), 2),
                "day_low": round(float(hist_daily["Low"].iloc[-1]), 2),
            }
        except Exception as exc:
            logger.warning("fetch_prices failed for %s: %r", ticker, exc)
            continue

    return prices


def fetch_news(tickers: list[str], api_key: str, finnhub_key: str = None) -> dict[str, list[str]]:
    """Fetch the latest headlines for each ticker.

    Primary: Finnhub company news (real-time, no delay).
    Fallback: NewsAPI (up to 12h delay on free tier).

    Returns a mapping of ticker -> [headline, ...] (up to 3 per ticker).
    Never raises.
    """
    from datetime import date, timedelta
    today = date.today().isoformat()
    week_ago = (date.today() - timedelta(days=7)).isoformat()

    news: dict[str, list[str]] = {}
    for ticker in tickers:
        headlines = []

        # Primary: Finnhub real-time company news
        if finnhub_key:
            try:
                resp = requests.get(
                    f"{_FINNHUB_URL}/company-news",
                    params={"symbol": ticker, "from": week_ago, "to": today, "token": finnhub_key},
                    timeout=10,
                )
                if resp.status_code == 200:
                    articles = resp.json()
                    headlines = [a["headline"] for a in articles[:3] if a.get("headline")]
            except Exception as exc:
                logger.warning("fetch_news (Finnhub) failed for %s: %r", ticker, exc)

        # Fallback: NewsAPI
        if not headlines and api_key:
            try:
                resp = requests.get(
                    "https://newsapi.org/v2/everything",
                    params={"q": ticker, "pageSize": 3, "sortBy": "publishedAt", "apiKey": api_key},
                    timeout=10,
                )
                if resp.status_code == 200:
                    articles = resp.json().get("articles", [])
                    headlines = [a["title"] for a in articles[:3]]
            except Exception as exc:
                logger.warning("fetch_news (NewsAPI) failed for %s: %r", ticker, exc)

        news[ticker] = headlines
    return news
