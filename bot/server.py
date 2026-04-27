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
GITHUB_REPO = os.environ["GITHUB_REPO"]

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
    meta.raise_for_status()
    sha = meta.json()["sha"]
    content = base64.b64encode(json.dumps(portfolio, indent=2).encode()).decode()
    resp = requests.put(
        _GITHUB_API,
        headers=_GITHUB_HEADERS,
        json={"message": "chore: manual portfolio update via bot [skip ci]", "content": content, "sha": sha},
        timeout=10,
    )
    logger.info("GitHub PUT status: %d", resp.status_code)
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
                "/status — last agent run time and next scheduled run\n"
                "/reason — reasoning behind last BUY/SELL alert\n\n"
                "/buy TICKER SHARES PRICE\\_USD COST\\_EUR BOUGHT\\_PCT\n"
                "  _e.g. /buy NVDA 2 118.40 221.35 10_\n"
                "  _(BOUGHT\\_PCT = % of portfolio this represents)_\n\n"
                "/sell TICKER SELL\\_PCT PROCEEDS\\_EUR\n"
                "  _e.g. /sell NVDA 50% 358.40_\n\n"
                "/reset — wipe portfolio back to €5000 clean state"
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
            cash = portfolio["cash"]
            holdings = portfolio.get("holdings", [])
            total_cost = sum(h.get("total_cost_eur", 0) for h in holdings)
            total_approx = cash + total_cost
            lines = [
                f"📊 *Portfolio*",
                f"💵 Cash: €{cash:.2f}",
                f"📈 Holdings cost basis: €{total_cost:.2f}",
                f"💼 Total (approx): €{total_approx:.2f}",
                "",
                "*Holdings:*",
            ]
            for h in holdings:
                avg = h.get("avg_buy_price_usd", 0)
                cost = h.get("total_cost_eur", 0)
                pct = (cost / total_approx * 100) if total_approx > 0 else 0
                lines.append(
                    f"  {h['ticker']}: {h['shares']} shares | Avg: ${avg:.2f} | Cost: €{cost:.2f} | Bought at {pct:.0f}% of portfolio"
                )
            if not holdings:
                lines.append("  None — all cash")
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
                    short_label = " *(short)*" if t.get("short") else ""
                    lines.append(
                        f"{emoji} {t['ticker']}{short_label} — {t['shares']} shares @ ${t['price_usd']:.2f}\n"
                        f"   Cost €{t['cost_eur']:.2f} → Proceeds €{t['proceeds_eur']:.2f} | {pnl_str}\n"
                        f"   {t['closed_at']}"
                    )
                total_str = f"+€{total_pnl:.2f}" if total_pnl >= 0 else f"-€{abs(total_pnl):.2f}"
                lines.append(f"\n*Total P&L: {total_str}*")
                send(chat_id, "\n".join(lines))

        elif text == "/reset":
            clean = {
                "cash": 5000.0,
                "holdings": [],
                "last_run": None,
                "last_alert": None,
                "trade_log": [],
            }
            save_portfolio_github(clean)
            send(chat_id, "🔄 Portfolio reset to €5000.00 cash, no holdings.")

        elif text == "/status":
            from datetime import datetime, timedelta
            from zoneinfo import ZoneInfo
            portfolio = get_portfolio()
            last_run = portfolio.get("last_run", "Never")

            lisbon_tz = ZoneInfo("Europe/Lisbon")
            now = datetime.now(lisbon_tz)

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

        elif text.startswith("/buy"):
            parts = text.split()
            if len(parts) != 3:
                send(chat_id, "Usage: `/buy TICKER COST_EUR`\nExample: `/buy NVDA 221.35`")
            else:
                ticker = parts[1].upper()
                try:
                    cost_eur = float(parts[2])
                    if cost_eur <= 0:
                        raise ValueError
                except ValueError:
                    send(chat_id, "⚠️ Cost must be a positive number.")
                    return "ok", 200
                
                portfolio = get_portfolio()
                if cost_eur > portfolio["cash"]:
                    send(chat_id, f"⚠️ Not enough cash. You have €{portfolio['cash']:.2f}, this costs €{cost_eur:.2f}.")
                    return "ok", 200
                
                # Simple buy action
                action = {
                    "action": "BUY", "ticker": ticker, "shares": 0.0,
                    "price_usd": 0.0, "cost_eur": cost_eur,
                }
                updated = apply_action(portfolio, action)
                save_portfolio_github(updated)
                send(chat_id, (
                    f"✅ *BUY recorded*\n"
                    f"{ticker} | Cost: €{cost_eur:.2f} | Cash left: €{updated['cash']:.2f}"
                ))

        elif text.startswith("/sell"):
            parts = text.split()
            # Usage: /sell TICKER SELL_PCT PROCEEDS_EUR (holding) OR /sell TICKER COST_EUR PROCEEDS_EUR (short)
            if len(parts) != 4:
                send(chat_id, (
                    "Usage:\n"
                    "1. Sell holding: `/sell TICKER SELL_PCT PROCEEDS_EUR`\n"
                    "2. Short sell: `/sell TICKER COST_EUR PROCEEDS_EUR`"
                ))
            else:
                ticker = parts[1].upper()
                portfolio = get_portfolio()
                holding = next((h for h in portfolio["holdings"] if h["ticker"] == ticker), None)

                if parts[2].endswith("%"):
                    # Selling a portion of a holding
                    sell_pct_str = parts[2]
                    try:
                        sell_pct = float(sell_pct_str[:-1]) / 100
                        proceeds_eur = float(parts[3])
                        if sell_pct <= 0 or sell_pct > 1 or proceeds_eur <= 0:
                            raise ValueError
                    except ValueError:
                        send(chat_id, "⚠️ Invalid values.")
                        return "ok", 200
                    
                    if not holding:
                        send(chat_id, f"⚠️ {ticker} is not held. Use `/sell TICKER COST_EUR PROCEEDS_EUR` to short.")
                        return "ok", 200

                    cost_basis_at_pct = holding["total_cost_eur"] * sell_pct
                    pnl = proceeds_eur - cost_basis_at_pct
                    action = {"action": "SELL", "ticker": ticker, "amount": sell_pct_str, "price_usd": 0.0, "proceeds_eur": proceeds_eur}
                else:
                    # Shorting
                    try:
                        cost_eur = float(parts[2])
                        proceeds_eur = float(parts[3])
                        if cost_eur <= 0 or proceeds_eur <= 0:
                            raise ValueError
                    except ValueError:
                        send(chat_id, "⚠️ Cost and proceeds must be positive numbers.")
                        return "ok", 200
                    
                    action = {"action": "SELL", "ticker": ticker, "amount": str(cost_eur), "price_usd": 0.0, "proceeds_eur": proceeds_eur}
                    pnl = proceeds_eur - cost_eur
                
                updated = apply_action(portfolio, action)
                save_portfolio_github(updated)
                
                pnl_str = f"+€{pnl:.2f}" if pnl >= 0 else f"-€{abs(pnl):.2f}"
                send(chat_id, (
                    f"✅ *SELL recorded*\n"
                    f"{ticker} | Proceeds: €{proceeds_eur:.2f} | P&L: {pnl_str} | Cash now: €{updated['cash']:.2f}"
                ))

    except Exception as exc:
        logger.error("Webhook handler error: %r", exc)
        send(chat_id, "⚠️ An error occurred. Please try again later.")

    return "ok", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
