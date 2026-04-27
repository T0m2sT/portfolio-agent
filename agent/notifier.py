import logging
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

EMOJI = {"SELL": "🔴", "BUY": "🟢", "HOLD": "🟡"}

COMPANY_NAMES = {
    "AAPL": "Apple", "MSFT": "Microsoft", "NVDA": "NVIDIA", "TSLA": "Tesla",
    "GOOGL": "Alphabet", "GOOG": "Alphabet", "AMZN": "Amazon", "META": "Meta",
    "NFLX": "Netflix", "AMD": "AMD", "INTC": "Intel", "ORCL": "Oracle",
    "CRM": "Salesforce", "ADBE": "Adobe", "QCOM": "Qualcomm", "AVGO": "Broadcom",
    "TSM": "TSMC", "ASML": "ASML", "SAP": "SAP", "SHOP": "Shopify",
    "SPY": "S&P 500 ETF", "QQQ": "Nasdaq ETF", "BTC": "Bitcoin", "ETH": "Ethereum",
    "GLD": "Gold ETF", "SLV": "Silver ETF", "OIL": "Oil ETF",
}


def _company(ticker: str, action: dict = None) -> str:
    if action and action.get("company_name"):
        return action["company_name"]
    return COMPANY_NAMES.get(ticker.upper(), ticker)


def _price_line(ticker: str, prices: dict) -> str:
    price_data = prices.get(ticker, {})
    raw_price = price_data.get("price", None)
    price = f"${raw_price:.2f}" if raw_price is not None else "N/A"
    pct = price_data.get("pct_change", 0)
    pct_str = f"+{pct:.1f}%" if pct >= 0 else f"{pct:.1f}%"
    return f"{price}  {pct_str}"


def format_alert(action: dict, prices: dict) -> str:
    ticker = action["ticker"]
    act = action["action"]
    now = datetime.now(ZoneInfo("Europe/Lisbon")).strftime("%a %d %b · %H:%M %Z")
    emoji = EMOJI.get(act, "⚪")
    pl = _price_line(ticker, prices)

    if act == "SELL":
        amount_pct = action.get("amount_pct", "")
        amount_eur = action.get("amount_eur", 0)
        headline = action.get("headline", "")
        reasoning = action.get("reasoning", "")
        confidence = action.get("confidence", "")
        conf_str = f"  ·  confidence: {confidence}" if confidence else ""
        lines = [
            f"{emoji} *SELL {amount_pct} (€{amount_eur}) · {ticker} ({_company(ticker, action)})*{conf_str}",
            now,
            "",
            f"💰 {pl}",
            f"📰 _{headline}_",
            "",
            reasoning,
            "",
            "Reply /reason to see full analysis",
        ]
    elif act == "BUY":
        amount_pct = action.get("amount_pct", "")
        amount_eur = action.get("amount_eur", 0)
        headline = action.get("headline", "")
        reasoning = action.get("reasoning", "")
        confidence = action.get("confidence", "")
        conf_str = f"  ·  confidence: {confidence}" if confidence else ""
        lines = [
            f"{emoji} *BUY €{amount_eur} ({amount_pct}) · {ticker} ({_company(ticker, action)})*{conf_str}",
            now,
            "",
            f"💰 {pl}",
            f"📰 _{headline}_",
            "",
            reasoning,
            "",
            "Reply /reason to see full analysis",
        ]
    else:
        lines = [
            f"{emoji} *HOLD · {ticker} ({_company(ticker, action)})*",
            now,
            "",
            f"💰 {pl}",
            "No action needed.",
        ]

    return "\n".join(lines)


def format_alert_brief(action: dict, prices: dict) -> str:
    ticker = action["ticker"]
    act = action["action"]
    emoji = EMOJI.get(act, "⚪")
    pl = _price_line(ticker, prices)
    company = _company(ticker, action)
    confidence = action.get("confidence", "")
    headline = action.get("headline", "")
    return f"{emoji} *{act} · {ticker} ({company})* · {confidence} confidence\n💰 {pl}\n📰 _{headline}_"


def format_no_action() -> str:
    now = datetime.now(ZoneInfo("Europe/Lisbon")).strftime("%a %d %b · %H:%M %Z")
    return f"🟡 *NO ACTION* · {now}\n\nNo high-confidence signal found. Holding all positions."


def format_portfolio(portfolio: dict) -> str:
    lines = ["📊 *Portfolio Summary*\n"]
    lines.append(f"💵 Cash: €{portfolio['cash']:.2f}")
    lines.append("\n*Holdings:*")
    for h in portfolio["holdings"]:
        avg_price = h.get("avg_buy_price_usd", 0)
        cost = h.get("total_cost_eur", 0)
        lines.append(f"  {h['ticker']}: {h['shares']} shares | Avg: ${avg_price:.2f} | Cost: €{cost:.2f}")
    if portfolio.get("watchlist"):
        lines.append(f"\n👀 Watching: {', '.join(portfolio['watchlist'])}")
    if portfolio.get("last_run"):
        lines.append(f"\n🕐 Last run: {portfolio['last_run']}")
    return "\n".join(lines)


def send_message(token: str, chat_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    logger.info("Sending Telegram message to chat_id=%s (len=%d)", chat_id, len(text))
    try:
        resp = requests.post(
            url,
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
        payload = resp.json()
        logger.info("Telegram response: status=%s ok=%s description=%s", resp.status_code, payload.get("ok"), payload.get("description"))
        if not payload.get("ok"):
            logger.error("Telegram API rejected message: %s", payload.get("description"))
    except requests.RequestException as exc:
        logger.error("Failed to send Telegram message: %r", exc)
