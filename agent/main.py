import os
import logging
from dotenv import load_dotenv
from agent.portfolio import load_portfolio, save_portfolio
from agent.fetcher import fetch_prices, fetch_news, fetch_trending_tickers
from agent.session import get_market_session, is_us_trading_day
from agent.analyst import analyse
from agent.notifier import format_alert, format_no_action, send_message

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

def run() -> None:
    load_dotenv()

    anthropic_key = os.environ["ANTHROPIC_API_KEY"]
    telegram_token = os.environ["TELEGRAM_BOT_TOKEN"]
    telegram_chat_id = os.environ["TELEGRAM_CHAT_ID"]
    news_api_key = os.environ["NEWS_API_KEY"]
    finnhub_key = os.environ.get("FINNHUB_API_KEY")

    try:
        market_session = get_market_session()
        logger.info("Market session: %s", market_session)

        if not is_us_trading_day(api_key=finnhub_key):
            logger.info("US market closed today — skipping run")
            return

        logger.info("Loading portfolio state")
        portfolio = load_portfolio()

        all_tickers = (
            [h["ticker"] for h in portfolio["holdings"]] +
            portfolio["watchlist"]
        )

        logger.info("Fetching trending tickers")
        trending = fetch_trending_tickers(limit=10)
        logger.info("Trending: %s", trending)

        buzz_tickers = [t for t in trending if t not in all_tickers]
        tickers_to_fetch = all_tickers + buzz_tickers

        logger.info("Fetching prices and news for: %s", tickers_to_fetch)
        prices = fetch_prices(tickers_to_fetch, api_key=finnhub_key)

        for t in [h["ticker"] for h in portfolio["holdings"]]:
            if t not in prices:
                logger.error("fetch_prices: held ticker %s missing from price data — will be omitted from analyst prompt", t)

        news = fetch_news(tickers_to_fetch, api_key=news_api_key, finnhub_key=finnhub_key)

        logger.info("Calling Claude analyst")
        result = analyse(portfolio, prices, news, api_key=anthropic_key,
                         trending=trending, market_session=market_session)

        # Update watchlist based on Claude's recommendations
        watchlist = list(portfolio["watchlist"])
        held_tickers = {h["ticker"] for h in portfolio["holdings"]}
        for addition in result.get("watchlist_additions", []):
            if addition not in watchlist and addition not in held_tickers:
                watchlist.append(addition)
        for removal in result.get("watchlist_removals", []):
            if removal in watchlist:
                watchlist.remove(removal)
        portfolio = {**portfolio, "watchlist": watchlist}

        # Store per-ticker signals — include confidence, headline, session for richer context
        actions = result.get("actions", [])
        non_hold = [a for a in actions if a.get("action") != "HOLD"]
        ticker_signals = dict(portfolio.get("ticker_signals", {}))
        for action in actions:
            ticker_signals[action["ticker"]] = {
                "action": action.get("action"),
                "confidence": action.get("confidence"),
                "headline": action.get("headline", ""),
                "reasoning": action.get("reasoning", ""),
                "market_session": market_session,
            }

        # Prune stale signals — keep only held, watchlist, and open shorts
        shorted_tickers = {
            t["ticker"] for t in portfolio.get("trade_log", [])
            if t.get("short") and t["ticker"] not in held_tickers
        }
        active_tickers = held_tickers | set(watchlist) | shorted_tickers
        ticker_signals = {t: s for t, s in ticker_signals.items() if t in active_tickers}
        portfolio["ticker_signals"] = ticker_signals

        # Store run metadata for /status and /reason
        portfolio["last_market_session"] = market_session
        portfolio["last_analysis_confidence"] = result.get("overall_confidence", "low")
        portfolio["last_analysis_risks"] = result.get("risks", [])

        # Keep last_alert for /reason
        alert_action = non_hold[-1] if non_hold else (actions[0] if actions else None)
        if alert_action:
            portfolio["last_alert"] = {
                "ticker": alert_action["ticker"],
                "action": alert_action.get("action"),
                "confidence": alert_action.get("confidence"),
                "headline": alert_action.get("headline", ""),
                "reasoning": alert_action.get("reasoning", ""),
                "market_session": market_session,
                "all_actions": actions,
                "risks": result.get("risks", []),
            }

        logger.info("Saving updated portfolio state")
        save_portfolio(portfolio)

        if non_hold:
            for action in non_hold:
                msg = format_alert(action, prices)
                send_message(telegram_token, telegram_chat_id, msg)
            logger.info("Run complete — %d signal(s) sent", len(non_hold))
        else:
            msg = format_no_action(actions, prices)
            send_message(telegram_token, telegram_chat_id, msg)
            logger.info("Run complete — no action signal sent")

    except Exception as exc:
        logger.error("Portfolio agent run failed: %r", exc)
        try:
            send_message(telegram_token, telegram_chat_id, f"⚠️ Portfolio agent error: {exc}")
        except Exception:
            pass
        raise

if __name__ == "__main__":
    run()
