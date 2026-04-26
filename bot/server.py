import os
import json
import base64
import logging
import requests
from flask import Flask, request
from agent.portfolio import apply_action

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
PORTFOLIO_URL = os.environ["PORTFOLIO_RAW_URL"]
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
GITHUB_REPO = os.environ["GITHUB_REPO"]  # e.g. "T0m2sT/portfolio-agent"

_GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}/contents/portfolio.json"
_GITHUB_HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
}


def send(chat_id: str, text: str) -> None:
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
        resp.raise_for_status()
        if not resp.json().get("ok"):
            logger.error("Telegram error: %s", resp.json().get("description"))
    except requests.RequestException as exc:
        logger.error("Failed to send message: %r", exc)



def get_portfolio() -> dict:
    resp = requests.get(_GITHUB_API, headers=_GITHUB_HEADERS, timeout=10)
    resp.raise_for_status()
    content = base64.b64decode(resp.json()["content"]).decode()
    return json.loads(content)


def save_portfolio_github(portfolio: dict) -> None:
    meta = requests.get(_GITHUB_API, headers=_GITHUB_HEADERS, timeout=10)
    logger.info("GitHub GET status: %d", meta.status_code)
    meta.raise_for_status()
    sha = meta.json()["sha"]
    content = base64.b64encode(json.dumps(portfolio, indent=2).encode()).decode()
    resp = requests.put(
        _GITHUB_API,
        headers=_GITHUB_HEADERS,
        json={"message": "chore: manual portfolio update via bot [skip ci]", "content": content, "sha": sha},
        timeout=10,
    )
    logger.info("GitHub PUT status: %d body: %s", resp.status_code, resp.text[:200])
    resp.raise_for_status()

@app.route(f"/webhook/{TELEGRAM_TOKEN}", methods=["POST"])
def webhook():
    if TELEGRAM_WEBHOOK_SECRET:
        incoming = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if incoming != TELEGRAM_WEBHOOK_SECRET:
            logger.warning("Webhook received with invalid secret token")
            return "unauthorized", 401

    data = request.json
    message = data.get("message", {})
    chat_id = str(message.get("chat", {}).get("id", ""))
    text = message.get("text", "").strip()

    if not chat_id or not text:
        return "ok", 200

    try:
        if text == "/help":
            send(chat_id, (
                "📖 *Commands*\n\n"
                "/portfolio — current holdings, cash, and P&L\n"
                "/log — closed trade history with total P&L\n"
                "/status — last agent run time\n"
                "/reason — reasoning behind last BUY/SELL alert\n"
                "/buy TICKER SHARES PRICE\\_USD COST\\_EUR\n"
                "  _e.g. /buy NVDA 2 118.40 221.35_\n\n"
                "/sell TICKER SHARES|%|ALL PRICE\\_USD PROCEEDS\\_EUR\n"
                "  _e.g. /sell NVDA 2 191.20 358.40_\n"
                "  _e.g. /sell NVDA 50% 191.20 358.40_\n"
                "  _e.g. /sell NVDA ALL 191.20 716.80_\n\n"
                "/watchlist add TICKER — add to watchlist\n"
                "/watchlist remove TICKER — remove from watchlist\n\n"
                "/reset — wipe portfolio back to €100 clean state"
            ))

        elif text == "/reason":
            portfolio = get_portfolio()
            alert = portfolio.get("last_alert")
            if not alert:
                send(chat_id, "No recent alert to explain.")
            else:
                ticker = alert.get("ticker", "")
                action = alert.get("action", "")
                reasoning = alert.get("reasoning", "No reasoning available.")
                confidence = alert.get("confidence", "")
                session = alert.get("market_session", "")
                risks = alert.get("risks", [])
                header = f"🧠 *Analysis — {action} {ticker}*"
                if confidence:
                    header += f"  ·  {confidence} confidence"
                if session:
                    header += f"  ·  {session}"
                body = f"{header}\n\n{reasoning}"
                if risks:
                    body += "\n\n⚠️ *Risks:*\n" + "\n".join(f"- {r}" for r in risks)
                send(chat_id, body)

        elif text == "/portfolio":
            portfolio = get_portfolio()
            lines = [f"📊 *Portfolio*\n💵 Cash: €{portfolio['cash']:.2f}\n\n*Holdings:*"]
            for h in portfolio.get("holdings", []):
                avg_price = h.get("avg_buy_price_usd", 0)
                lines.append(f"  {h['ticker']}: {h['shares']} shares | Avg: ${avg_price:.2f} | Cost: €{h['total_cost_eur']:.2f}")
            if portfolio.get("watchlist"):
                lines.append(f"\n👀 Watching: {', '.join(portfolio['watchlist'])}")
            send(chat_id, "\n".join(lines))

        elif text == "/log":
            portfolio = get_portfolio()
            trades = portfolio.get("trade_log", [])
            if not trades:
                send(chat_id, "📋 No closed trades yet.")
            else:
                total_pnl = sum(t["pnl"] for t in trades)
                lines = ["📋 *Trade Log*\n"]
                for t in trades:
                    emoji = "🟢" if t["pnl"] >= 0 else "🔴"
                    pnl_str = f"+€{t['pnl']:.2f}" if t["pnl"] >= 0 else f"-€{abs(t['pnl']):.2f}"
                    lines.append(f"{emoji} {t['ticker']} — {t['shares']} shares @ ${t['price_usd']:.2f}\n   Cost €{t['cost_eur']:.2f} → Proceeds €{t['proceeds_eur']:.2f} | {pnl_str}\n   {t['closed_at']}")
                total_str = f"+€{total_pnl:.2f}" if total_pnl >= 0 else f"-€{abs(total_pnl):.2f}"
                lines.append(f"\n*Total P&L: {total_str}*")
                send(chat_id, "\n".join(lines))

        elif text == "/reset":
            clean = {
                "cash": 100.0,
                "holdings": [],
                "watchlist": ["NVDA", "TSLA", "MSFT", "META", "AMZN"],
                "last_run": None,
                "last_alert": None,
                "ticker_signals": {},
                "trade_log": [],
            }
            save_portfolio_github(clean)
            send(chat_id, "🔄 Portfolio reset to €100.00 cash, no holdings.")

        elif text == "/status":
            from datetime import datetime, timedelta
            from zoneinfo import ZoneInfo
            portfolio = get_portfolio()
            last_run = portfolio.get("last_run", "Never")

            lisbon_tz = ZoneInfo("Europe/Lisbon")
            now = datetime.now(lisbon_tz)

            # Matches GitHub Actions cron in Lisbon summer (UTC+1)
            # UTC: 8, 10, 13, 14:30, 16, 17, 18, 19, 20:30, 22 → Lisbon: 9, 11, 14, 15:30, 17, 18, 19, 20, 21:30, 23
            schedule = [(9, 0), (11, 0), (14, 0), (15, 30), (17, 0), (18, 0), (19, 0), (20, 0), (21, 30), (23, 0)]
            today = now.replace(hour=0, minute=0, second=0, microsecond=0)

            next_run = None
            for hour, minute in schedule:
                candidate = today.replace(hour=hour, minute=minute)
                if candidate > now:
                    next_run = candidate
                    break

            if not next_run:
                next_run = (today + timedelta(days=1)).replace(hour=schedule[0][0], minute=schedule[0][1])

            mins_away = int((next_run - now).total_seconds() / 60)
            send(chat_id, f"🕐 Last run: {last_run}\n⏭ Next run: {next_run.strftime('%H:%M Lisbon')} (in {mins_away}m)")

        elif text.startswith("/watchlist"):
            parts = text.split()
            if len(parts) != 3 or parts[1].lower() not in ("add", "remove"):
                send(chat_id, (
                    "Usage:\n"
                    "`/watchlist add TICKER`\n"
                    "`/watchlist remove TICKER`"
                ))
            else:
                _, cmd, ticker = parts
                ticker = ticker.upper()
                portfolio = get_portfolio()
                watchlist = list(portfolio.get("watchlist", []))
                held = [h["ticker"] for h in portfolio.get("holdings", [])]
                if cmd.lower() == "add":
                    if ticker in watchlist:
                        send(chat_id, f"👀 {ticker} is already on the watchlist.")
                    elif ticker in held:
                        send(chat_id, f"⚠️ {ticker} is already held — no need to watch it.")
                    else:
                        watchlist.append(ticker)
                        save_portfolio_github({**portfolio, "watchlist": watchlist})
                        send(chat_id, f"✅ Added *{ticker}* to watchlist.\n👀 Watching: {', '.join(watchlist)}")
                else:
                    if ticker not in watchlist:
                        send(chat_id, f"⚠️ {ticker} is not on the watchlist.")
                    else:
                        watchlist.remove(ticker)
                        save_portfolio_github({**portfolio, "watchlist": watchlist})
                        send(chat_id, f"✅ Removed *{ticker}* from watchlist.\n👀 Watching: {', '.join(watchlist) or 'nothing'}")

        elif text.startswith("/buy"):
            parts = text.split()
            if len(parts) != 5:
                send(chat_id, (
                    "Usage: `/buy TICKER SHARES PRICE_USD COST_EUR`\n"
                    "Example: `/buy NVDA 2 118.40 221.35`\n"
                    "_COST\\_EUR is the exact amount debited in T212._"
                ))
            else:
                _, ticker, shares_str, price_str, cost_str = parts
                ticker = ticker.upper()
                try:
                    shares = float(shares_str)
                    price_usd = float(price_str)
                    cost_eur = float(cost_str)
                    if shares <= 0 or price_usd <= 0 or cost_eur <= 0:
                        raise ValueError
                except ValueError:
                    send(chat_id, "⚠️ Shares, price and cost must be positive numbers.")
                else:
                    portfolio = get_portfolio()
                    if cost_eur > portfolio["cash"]:
                        send(chat_id, f"⚠️ Not enough cash. You have €{portfolio['cash']:.2f}, this costs €{cost_eur:.2f}.")
                    else:
                        action = {"action": "BUY", "ticker": ticker, "shares": shares, "price_usd": price_usd, "cost_eur": cost_eur}
                        updated = apply_action(portfolio, action)
                        save_portfolio_github(updated)
                        send(chat_id, f"✅ *BUY recorded*\n{shares} shares of {ticker} @ ${price_usd:.2f}\nCost: €{cost_eur:.2f} | Cash left: €{updated['cash']:.2f}")

        elif text.startswith("/sell"):
            parts = text.split()
            if len(parts) != 5:
                send(chat_id, (
                    "Usage: `/sell TICKER SHARES|%|ALL PRICE_USD PROCEEDS_EUR`\n"
                    "Examples:\n"
                    "`/sell NVDA 2 191.20 358.40`\n"
                    "`/sell NVDA 50% 191.20 358.40`\n"
                    "`/sell NVDA ALL 191.20 716.80`\n"
                    "`/sell TSLA 1 250.00 23.00` _(short — not held)_\n"
                    "_PROCEEDS\\_EUR is the exact amount credited in T212 (net of fees)._"
                ))
            else:
                _, ticker, amount, price_str, proceeds_str = parts
                ticker = ticker.upper()
                amount_up = amount.upper()
                valid_amount = (
                    amount_up == "ALL"
                    or (amount_up.endswith("%") and amount_up[:-1].replace(".", "").isdigit())
                    or amount_up.replace(".", "").isdigit()
                )
                if not valid_amount:
                    send(chat_id, "⚠️ Shares must be a number, a percentage like `50%`, or `ALL`.")
                else:
                    try:
                        price_usd = float(price_str)
                        proceeds_eur = float(proceeds_str)
                        if price_usd <= 0 or proceeds_eur <= 0:
                            raise ValueError
                    except ValueError:
                        send(chat_id, "⚠️ Price and proceeds must be positive numbers.")
                    else:
                        portfolio = get_portfolio()
                        holding = next((h for h in portfolio["holdings"] if h["ticker"] == ticker), None)
                        is_short = holding is None
                        if is_short and amount_up in ("ALL", ) or (amount_up.endswith("%") and is_short):
                            send(chat_id, f"⚠️ {ticker} is not held — use a share count for short sells (e.g. `1` or `2.5`).")
                        else:
                            action = {"action": "SELL", "ticker": ticker, "amount": amount_up, "price_usd": price_usd, "proceeds_eur": proceeds_eur}
                            updated = apply_action(portfolio, action)
                            last_trade = updated.get("trade_log", [{}])[-1]
                            pnl = last_trade.get("pnl", 0)
                            pnl_str = f"+€{pnl:.2f}" if pnl >= 0 else f"-€{abs(pnl):.2f}"
                            save_portfolio_github(updated)
                            label = "SHORT recorded" if is_short else "SELL recorded"
                            send(chat_id, f"✅ *{label}*\n{ticker} {amount_up} @ ${price_usd:.2f}\nProceeds: €{proceeds_eur:.2f} | P&L: {pnl_str} | Cash now: €{updated['cash']:.2f}")

    except Exception as exc:
        logger.error("Webhook handler error: %r", exc)
        send(chat_id, "⚠️ An error occurred. Please try again later.")

    return "ok", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
