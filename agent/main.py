import os
import logging
from dotenv import load_dotenv
from agent.portfolio import load_portfolio, save_portfolio
from agent.fetcher import fetch_prices, fetch_news, fetch_trending_tickers
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

    try:
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
        logger.info("Fetching prices and news for: %s", all_tickers + buzz_tickers)
        prices = fetch_prices(all_tickers + buzz_tickers)
        news = fetch_news(all_tickers + buzz_tickers, api_key=news_api_key)

        logger.info("Calling Claude analyst")
        result = analyse(portfolio, prices, news, api_key=anthropic_key, trending=trending)

        # Update watchlist based on Claude's recommendations
        watchlist = list(portfolio["watchlist"])
        for addition in result.get("watchlist_additions", []):
            if addition not in watchlist and addition not in [h["ticker"] for h in portfolio["holdings"]]:
                watchlist.append(addition)
        for removal in result.get("watchlist_removals", []):
            if removal in watchlist:
                watchlist.remove(removal)
        portfolio = {**portfolio, "watchlist": watchlist}

        # Store last alert — use last non-HOLD action for reasoning
        actions = result.get("actions", [])
        non_hold = [a for a in actions if a.get("action") != "HOLD"]
        alert_action = non_hold[-1] if non_hold else (actions[0] if actions else None)
        if alert_action:
            portfolio["last_alert"] = {
                "ticker": alert_action["ticker"],
                "action": alert_action.get("action"),
                "reasoning": alert_action.get("reasoning", ""),
                "all_actions": actions,
            }

        logger.info("Saving updated portfolio state")
        save_portfolio(portfolio)

        # Send Telegram alerts — non-HOLD actions individually, all-HOLD as a single summary
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
