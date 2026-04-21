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
        price_usd = action["price_usd"]
        proceeds_eur = action["proceeds_eur"]
        amount = action["amount"].upper()
        total_shares = holding["shares"]
        if amount == "ALL":
            sell_shares = total_shares
        elif amount.endswith("%"):
            pct = float(amount[:-1]) / 100
            sell_shares = total_shares * pct
        else:
            sell_shares = float(amount)
        sell_shares = min(round(sell_shares, 8), total_shares)
        sell_fraction = sell_shares / total_shares
        cost_basis = round(holding["total_cost_eur"] * sell_fraction, 4)
        pnl = round(proceeds_eur - cost_basis, 2)
        cash += proceeds_eur
        trade = {
            "ticker": ticker,
            "shares": sell_shares,
            "cost_eur": cost_basis,
            "proceeds_eur": proceeds_eur,
            "price_usd": price_usd,
            "pnl": pnl,
            "closed_at": _now_utc(),
        }
        remaining_shares = round(total_shares - sell_shares, 8)
        remaining_cost = round(holding["total_cost_eur"] - cost_basis, 4)
        holdings = [
            {**h, "shares": remaining_shares, "total_cost_eur": remaining_cost, "last_price_usd": price_usd}
            if h["ticker"] == ticker else h
            for h in holdings
        ]
        holdings = [h for h in holdings if h["shares"] > 0.00001]
        trade_log = list(portfolio.get("trade_log", []))
        trade_log.append(trade)
        return {**portfolio, "holdings": holdings, "cash": round(cash, 2), "trade_log": trade_log}

    if action["action"] == "BUY":
        shares = action["shares"]
        price_usd = action["price_usd"]
        cost_eur = action["cost_eur"]
        cash -= cost_eur
        existing = next((h for h in holdings if h["ticker"] == ticker), None)
        if existing:
            total_shares = existing["shares"] + shares
            total_cost = existing["total_cost_eur"] + cost_eur
            holdings = [
                {**h, "shares": round(total_shares, 8), "total_cost_eur": round(total_cost, 4), "last_price_usd": price_usd}
                if h["ticker"] == ticker else h
                for h in holdings
            ]
        else:
            holdings.append({
                "ticker": ticker,
                "shares": round(shares, 8),
                "total_cost_eur": round(cost_eur, 4),
                "last_price_usd": price_usd,
            })
        watchlist = [t for t in portfolio["watchlist"] if t != ticker]
        return {**portfolio, "holdings": holdings, "cash": round(cash, 2), "watchlist": watchlist}

    return {**portfolio, "holdings": holdings, "cash": cash}
