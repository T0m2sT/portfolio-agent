import json
from datetime import datetime, timezone

def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

PORTFOLIO_PATH = "portfolio.json"


def load_portfolio(path: str = PORTFOLIO_PATH) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"Portfolio file not found: {path}")
    except json.JSONDecodeError as e:
        raise ValueError(f"Corrupted portfolio.json: {e}")


def save_portfolio(portfolio: dict, path: str = PORTFOLIO_PATH) -> None:
    updated = {**portfolio, "last_run": datetime.now(timezone.utc).isoformat()}
    with open(path, "w") as f:
        json.dump(updated, f, indent=2)


def compute_pnl(holding: dict) -> float:
    return (holding["last_price"] - holding["avg_buy_price"]) * holding["shares"]


def apply_action(portfolio: dict, action: dict) -> dict:
    holdings = [dict(h) for h in portfolio["holdings"]]
    cash = portfolio["cash"]
    ticker = action["ticker"]

    if action["action"] == "HOLD":
        return {**portfolio, "holdings": holdings, "cash": cash}

    if action["action"] == "SELL":
        holding = next((h for h in holdings if h["ticker"] == ticker), None)
        if not holding:
            return {**portfolio, "holdings": holdings, "cash": cash}
        price = action.get("last_price", holding["last_price"])
        amount = action["amount"].upper()
        if amount == "ALL":
            sell_shares = holding["shares"]
        else:
            pct = float(amount.replace("%", "")) / 100
            sell_shares = holding["shares"] * pct
        sell_shares = min(sell_shares, holding["shares"])
        cash += sell_shares * price
        pnl = round((price - holding["avg_buy_price"]) * sell_shares, 2)
        trade = {
            "ticker": ticker,
            "shares": round(sell_shares, 8),
            "avg_buy_price": holding["avg_buy_price"],
            "sell_price": price,
            "pnl": pnl,
            "closed_at": _now_utc(),
        }
        holding["shares"] = round(holding["shares"] - sell_shares, 8)
        holdings = [h for h in holdings if h["shares"] > 0.00001]
        trade_log = list(portfolio.get("trade_log", []))
        trade_log.append(trade)
        return {**portfolio, "holdings": holdings, "cash": round(cash, 2), "trade_log": trade_log}

    if action["action"] == "BUY":
        price = action.get("last_price", 1.0)
        buy_amount = float(action["amount"])
        shares = buy_amount / price
        cash -= buy_amount
        existing = next((h for h in holdings if h["ticker"] == ticker), None)
        if existing:
            total_shares = existing["shares"] + shares
            new_avg = (existing["avg_buy_price"] * existing["shares"] + price * shares) / total_shares
            holdings = [
                {**h, "avg_buy_price": round(new_avg, 6), "shares": round(total_shares, 8), "last_price": price}
                if h["ticker"] == ticker else h
                for h in holdings
            ]
        else:
            holdings.append({
                "ticker": ticker,
                "shares": round(shares, 8),
                "avg_buy_price": price,
                "last_price": price,
            })
        watchlist = [t for t in portfolio["watchlist"] if t != ticker]
        return {**portfolio, "holdings": holdings, "cash": round(cash, 2), "watchlist": watchlist}

    return {**portfolio, "holdings": holdings, "cash": cash}
