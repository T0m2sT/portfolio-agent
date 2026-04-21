import logging
import requests
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

EMOJI = {"SELL": "🔴", "BUY": "🟢", "HOLD": "🟡"}


def format_alert(action: dict, prices: dict) -> str:
    ticker = action["ticker"]
    act = action["action"]
    price_data = prices.get(ticker, {})
    raw_price = price_data.get("price", None)
    price = f"{raw_price:.2f}" if raw_price is not None else "N/A"
    pct = price_data.get("pct_change", 0)
    pct_str = f"+{pct:.1f}%" if pct >= 0 else f"{pct:.1f}%"
    now = datetime.now(timezone.utc).strftime("%a %d %b · %H:%M UTC")
    emoji = EMOJI.get(act, "⚪")

    if act == "SELL":
        amount = action.get("amount", "")
        headline = action.get("headline", "")
        title = f"{emoji} SELL {amount} — {ticker}"
        body = f"💰 Price: €{price} ({pct_str})\n📰 {headline}\nAction: Sell {amount} of your {ticker} position"
    elif act == "BUY":
        amount = action.get("amount", "")
        headline = action.get("headline", "")
        title = f"{emoji} BUY €{amount} — {ticker}"
        body = f"💰 Price: €{price} ({pct_str})\n📰 {headline}\nAction: Buy €{amount} of {ticker}"
    else:
        title = f"{emoji} HOLD — {ticker}"
        body = f"💰 Price: €{price} ({pct_str})\nNo action needed."

    return f"{title}\n{now}\n\n{body}\n\nReply /reason to see full analysis"


def format_no_action(actions: list, prices: dict) -> str:
    now = datetime.now(timezone.utc).strftime("%a %d %b · %H:%M UTC")
    lines = [f"🟡 NO ACTION — {now}", ""]
    lines.append("Agent ran and reviewed all positions. No high-conviction signal found.")
    if actions:
        lines.append("")
        lines.append("Positions reviewed:")
        for a in actions:
            ticker = a["ticker"]
            price_data = prices.get(ticker, {})
            raw_price = price_data.get("price", None)
            price = f"€{raw_price:.2f}" if raw_price is not None else "N/A"
            pct = price_data.get("pct_change", 0)
            pct_str = f"+{pct:.1f}%" if pct >= 0 else f"{pct:.1f}%"
            note = a.get("reasoning", "Holding.")
            lines.append(f"  • {ticker} {price} ({pct_str}) — {note}")
    lines.append("")
    lines.append("Reply /reason to see last active signal")
    return "\n".join(lines)


def format_portfolio(portfolio: dict) -> str:
    lines = ["📊 *Portfolio Summary*\n"]
    lines.append(f"💵 Cash: €{portfolio['cash']:.2f}")
    lines.append("\n*Holdings:*")
    for h in portfolio["holdings"]:
        pnl = (h["last_price"] - h["avg_buy_price"]) * h["shares"]
        pnl_str = f"+€{pnl:.2f}" if pnl >= 0 else f"-€{abs(pnl):.2f}"
        lines.append(f"  {h['ticker']}: {h['shares']} shares @ €{h['avg_buy_price']:.2f} | P&L: {pnl_str}")
    if portfolio.get("watchlist"):
        lines.append(f"\n👀 Watching: {', '.join(portfolio['watchlist'])}")
    if portfolio.get("last_run"):
        lines.append(f"\n🕐 Last run: {portfolio['last_run']}")
    return "\n".join(lines)


def send_message(token: str, chat_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = requests.post(
            url,
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
        resp.raise_for_status()
        payload = resp.json()
        if not payload.get("ok"):
            logger.error("Telegram API error: %s", payload.get("description"))
    except requests.RequestException as exc:
        logger.error("Failed to send Telegram message: %r", exc)
