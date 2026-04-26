import logging
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

EMOJI = {"SELL": "🔴", "BUY": "🟢", "HOLD": "🟡"}


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
        amount = action.get("amount", "")
        headline = action.get("headline", "")
        reasoning = action.get("reasoning", "")
        confidence = action.get("confidence", "")
        conf_str = f"  ·  confidence: {confidence}" if confidence else ""
        lines = [
            f"{emoji} *SELL {amount} · {ticker}*{conf_str}",
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
        amount = action.get("amount", "")
        headline = action.get("headline", "")
        reasoning = action.get("reasoning", "")
        confidence = action.get("confidence", "")
        conf_str = f"  ·  confidence: {confidence}" if confidence else ""
        lines = [
            f"{emoji} *BUY €{amount} · {ticker}*{conf_str}",
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
            f"{emoji} *HOLD · {ticker}*",
            now,
            "",
            f"💰 {pl}",
            "No action needed.",
        ]

    return "\n".join(lines)


def format_no_action(actions: list, prices: dict) -> str:
    now = datetime.now(ZoneInfo("Europe/Lisbon")).strftime("%a %d %b · %H:%M %Z")
    lines = [
        f"🟡 *NO ACTION*",
        now,
        "",
        "No high-conviction signal found. All positions reviewed:",
        "─────────────────────",
    ]
    for a in actions:
        ticker = a["ticker"]
        pl = _price_line(ticker, prices)
        note = a.get("reasoning", "Holding.")
        lines.append(f"*{ticker}*  {pl}")
        lines.append(note)
        lines.append("")
    lines.append("─────────────────────")
    lines.append("Reply /reason to see last active signal")
    return "\n".join(lines)


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
