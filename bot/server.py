import os
import json
import base64
import logging
import anthropic
import requests
from flask import Flask, request
from agent.portfolio import apply_action

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ANTHROPIC_KEY = os.environ["ANTHROPIC_API_KEY"]
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
    resp = requests.get(PORTFOLIO_URL, timeout=10)
    resp.raise_for_status()
    return resp.json()


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
    data = request.json
    message = data.get("message", {})
    chat_id = str(message.get("chat", {}).get("id", ""))
    text = message.get("text", "").strip()

    if not chat_id or not text:
        return "ok", 200

    try:
        if text == "/reason":
            portfolio = get_portfolio()
            alert = portfolio.get("last_alert")
            if not alert:
                send(chat_id, "No recent alert to explain.")
            else:
                reasoning = alert.get("reasoning", "No reasoning available.")
                ticker = alert.get("ticker", "")
                action = alert.get("action", "")
                send(chat_id, f"🧠 *Analysis — {action} {ticker}*\n\n{reasoning}")

        elif text.startswith("/ask "):
            question = text[5:].strip()
            portfolio = get_portfolio()
            alert = portfolio.get("last_alert", {})
            context = f"Last alert: {json.dumps(alert, indent=2)}\nPortfolio cash: €{portfolio.get('cash', 0):.2f}"
            client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
            resp_ai = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=512,
                system="You are a concise trading analyst. Answer the user's question about their portfolio in 2-4 sentences.",
                messages=[{"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}"}],
            )
            send(chat_id, resp_ai.content[0].text)

        elif text == "/portfolio":
            portfolio = get_portfolio()
            lines = [f"📊 *Portfolio*\n💵 Cash: €{portfolio['cash']:.2f}\n\n*Holdings:*"]
            for h in portfolio.get("holdings", []):
                pnl = (h["last_price"] - h["avg_buy_price"]) * h["shares"]
                pnl_str = f"+€{pnl:.2f}" if pnl >= 0 else f"-€{abs(pnl):.2f}"
                lines.append(f"  {h['ticker']}: {h['shares']} shares | P&L: {pnl_str}")
            if portfolio.get("watchlist"):
                lines.append(f"\n👀 Watching: {', '.join(portfolio['watchlist'])}")
            send(chat_id, "\n".join(lines))

        elif text == "/status":
            portfolio = get_portfolio()
            last_run = portfolio.get("last_run", "Never")
            send(chat_id, f"🕐 Last run: {last_run}\n⏱ Next run: within 4 hours")

        elif text.startswith("/buy"):
            parts = text.split()
            if len(parts) != 4:
                send(chat_id, "Usage: `/buy TICKER SHARES PRICE`\nExample: `/buy NVDA 2 118.40`")
            else:
                _, ticker, shares_str, price_str = parts
                ticker = ticker.upper()
                try:
                    shares = float(shares_str)
                    price = float(price_str)
                    if shares <= 0 or price <= 0:
                        raise ValueError
                except ValueError:
                    send(chat_id, "⚠️ Shares and price must be positive numbers.")
                else:
                    portfolio = get_portfolio()
                    cost = round(shares * price, 2)
                    if cost > portfolio["cash"]:
                        send(chat_id, f"⚠️ Not enough cash. You have €{portfolio['cash']:.2f}, this costs €{cost:.2f}.")
                    else:
                        action = {"action": "BUY", "ticker": ticker, "amount": str(cost), "last_price": price}
                        updated = apply_action(portfolio, action)
                        save_portfolio_github(updated)
                        send(chat_id, f"✅ *BUY recorded*\n{shares} shares of {ticker} @ €{price:.2f}\nCost: €{cost:.2f} | Cash left: €{updated['cash']:.2f}")

        elif text.startswith("/sell"):
            parts = text.split()
            if len(parts) != 3:
                send(chat_id, "Usage: `/sell TICKER AMOUNT`\nExamples:\n`/sell NVDA 50%`\n`/sell NVDA ALL`")
            else:
                _, ticker, amount = parts
                ticker = ticker.upper()
                amount_up = amount.upper()
                if amount_up != "ALL" and not (amount_up.endswith("%") and amount_up[:-1].replace(".", "").isdigit()):
                    send(chat_id, "⚠️ Amount must be a percentage like `50%` or `ALL`.\nExample: `/sell NVDA 50%`")
                else:
                    portfolio = get_portfolio()
                    holding = next((h for h in portfolio["holdings"] if h["ticker"] == ticker), None)
                    if not holding:
                        send(chat_id, f"⚠️ You don't hold {ticker}.")
                    else:
                        price = holding["last_price"]
                        action = {"action": "SELL", "ticker": ticker, "amount": amount_up, "last_price": price}
                        updated = apply_action(portfolio, action)
                        save_portfolio_github(updated)
                        send(chat_id, f"✅ *SELL recorded*\n{ticker} {amount_up} @ €{price:.2f} | Cash now: €{updated['cash']:.2f}")

    except Exception as exc:
        logger.error("Webhook handler error: %r", exc)
        send(chat_id, "⚠️ An error occurred. Please try again later.")

    return "ok", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
