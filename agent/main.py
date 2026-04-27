import os
import logging
from dotenv import load_dotenv
from agent.portfolio import load_portfolio, save_portfolio
from agent.fetcher import fetch_prices, fetch_news
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

        portfolio = load_portfolio()
        held_tickers = [h["ticker"] for h in portfolio.get("holdings", [])]

        logger.info("Fetching prices for held tickers: %s", held_tickers)
        prices = fetch_prices(held_tickers, api_key=finnhub_key)

        for t in held_tickers:
            if t not in prices:
                logger.error("fetch_prices: held ticker %s missing from price data", t)

        logger.info("Fetching broad news")
        news = fetch_news(held_tickers, news_api_key=news_api_key, finnhub_key=finnhub_key)

        # Fetch prices for any opportunity tickers that appeared in news
        opportunity_tickers = [t for t in news if t not in ("__general__",) and t not in held_tickers]
        if opportunity_tickers:
            logger.info("Fetching prices for opportunity tickers: %s", opportunity_tickers)
            opp_prices = fetch_prices(opportunity_tickers, api_key=finnhub_key)
            prices.update(opp_prices)

        logger.info("Calling Claude analyst")
        result = analyse(portfolio, prices, news, api_key=anthropic_key, market_session=market_session)

        actions = result.get("actions", [])
        non_hold = [a for a in actions if a.get("action") != "HOLD"]

        # Store last alert and run metadata
        portfolio["last_market_session"] = market_session
        portfolio["last_analysis_confidence"] = result.get("overall_confidence", "low")
        portfolio["last_analysis_risks"] = result.get("risks", [])

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
