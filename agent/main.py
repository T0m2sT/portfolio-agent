import os
import logging
from dotenv import load_dotenv
from agent.portfolio import load_portfolio, save_portfolio, apply_action
from agent.fetcher import fetch_prices, fetch_news
from agent.analyst import analyse
from agent.notifier import format_alert, send_message

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

def run():
    anthropic_key = os.environ["ANTHROPIC_API_KEY"]
    telegram_token = os.environ["TELEGRAM_BOT_TOKEN"]
    telegram_chat_id = os.environ["TELEGRAM_CHAT_ID"]
    news_api_key = os.environ["NEWS_API_KEY"]

    logger.info("Loading portfolio state")
    portfolio = load_portfolio()

    all_tickers = (
        [h["ticker"] for h in portfolio["holdings"]] +
        portfolio["watchlist"]
    )

    logger.info("Fetching prices and news for: %s", all_tickers)
    prices = fetch_prices(all_tickers)
    news = fetch_news(all_tickers, api_key=news_api_key)

    logger.info("Calling Claude analyst")
    result = analyse(portfolio, prices, news, api_key=anthropic_key)

    # Update watchlist based on Claude's recommendations
    for addition in result.get("watchlist_additions", []):
        if addition not in portfolio["watchlist"] and addition not in [h["ticker"] for h in portfolio["holdings"]]:
            portfolio["watchlist"].append(addition)
    for removal in result.get("watchlist_removals", []):
        if removal in portfolio["watchlist"]:
            portfolio["watchlist"].remove(removal)

    # Apply actions and update last_price on each holding
    for action in result.get("actions", []):
        ticker = action["ticker"]
        price_data = prices.get(ticker, {})
        last_price = price_data.get("price", 0)
        action_with_price = {**action, "last_price": last_price}
        portfolio = apply_action(portfolio, action_with_price)

    # Store last alert (including all actions and reasoning) for /reason command
    actions = result.get("actions", [])
    if actions:
        portfolio["last_alert"] = {
            "ticker": actions[0]["ticker"],
            "action": actions[0].get("action"),
            "reasoning": actions[0].get("reasoning", ""),
            "all_actions": actions,
        }

    logger.info("Saving updated portfolio state")
    save_portfolio(portfolio)

    # Send Telegram alerts for non-HOLD actions only
    sent = 0
    for action in actions:
        if action["action"] != "HOLD":
            msg = format_alert(action, prices)
            send_message(telegram_token, telegram_chat_id, msg)
            sent += 1

    logger.info("Run complete — %d alert(s) sent", sent)

if __name__ == "__main__":
    run()
