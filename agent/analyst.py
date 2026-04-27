import json
import logging
import os
import re
from datetime import datetime, timezone

import anthropic

from agent.session import get_market_session

logger = logging.getLogger(__name__)

_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")

SYSTEM_PROMPT = """
You are an autonomous portfolio manager running an aggressive, high-conviction trading strategy.

Your goal is maximum short-to-medium term gains (days to weeks). You trade stocks, ETFs, crypto, and commodities.
You have full autonomy over what to buy and sell — no asset class is off limits.

## PORTFOLIO

You will receive:
- Current cash available (in EUR)
- Current holdings: each with ticker, shares, avg buy price (USD), cost (EUR), and % of portfolio at time of purchase
- Total portfolio value (EUR) at current prices
- Current market session

## YOUR JOB

1. Read the news provided. Identify the strongest actionable opportunities — both long (BUY) and short (SELL).
2. Decide what to do with current holdings first (SELL if thesis is broken or better opportunity exists, HOLD otherwise).
3. Identify the best new positions to open based on news catalysts.
4. Output a list of actions. All position sizes are expressed as **% of total portfolio value**.

## POSITION SIZING RULES

- All `amount` values are a percentage of total portfolio value (e.g. "15%" means 15% of total portfolio EUR value).
- A single action must not exceed 40% of total portfolio value.
- All concurrent BUY actions combined must not exceed available cash as a % of total portfolio.
- For SELL on a held position: amount is "ALL", "50%", "30%", etc. — % of that holding to close.
- Never size a position so large it would require more cash than available.

## DECISION RULES

- News is your primary signal. Name the specific headline and assess its direct impact.
- For holdings: check each one — is the thesis still valid? Any negative catalyst? Opportunity cost?
- For new positions: only act on strong, specific, recent catalysts (earnings, product launch, regulatory decision, major partnership, macro shift).
- Vague sector sentiment or recycled old news is NOT a catalyst.
- If no strong opportunity exists, output HOLD for everything. Do not force trades.

## MARKET SESSION

- regular: price action reliable, best for decisive action
- pre-market / after-hours: act only on direct, material catalysts; note gap risk
- closed: only act on major breaking news; prefer HOLD

## OUTPUT FORMAT

Return STRICT JSON only. No markdown, no prose.

{
  "market_session": "regular",
  "total_portfolio_eur": 4820.50,
  "available_cash_eur": 1200.00,
  "overall_confidence": "high | medium | low",
  "actions": [
    {
      "ticker": "NVDA",
      "action": "BUY | SELL | HOLD",
      "amount": "20%",
      "headline": "Specific catalyst headline or 'No clear catalyst'",
      "confidence": "high | medium | low",
      "reasoning": "Specific reasoning. Name the catalyst, assess magnitude, state session reliability. 3-5 sentences."
    }
  ],
  "risks": ["Key uncertainty or data quality issue"]
}

Rules for the actions array:
- MUST include one entry for every current holding.
- MAY include new tickers not currently held (BUY or SELL short).
- HOLD entries omit `amount`.
- Empty actions array is never acceptable.
""".strip()


def _holding_line(h: dict, prices: dict, total_eur: float) -> str:
    ticker = h["ticker"]
    price_data = prices.get(ticker, {})
    current_price = price_data.get("price")
    shares = h["shares"]
    avg_buy = h.get("avg_buy_price_usd", 0)
    cost_eur = h.get("total_cost_eur", 0)
    bought_pct = h.get("bought_pct", 0)

    position_usd = (current_price or 0) * shares
    parts = [f"{ticker}"]
    if current_price:
        parts.append(f"${current_price:.2f}")
    if shares:
        parts.append(f"{shares:.6g} shares")
    if avg_buy:
        parts.append(f"avg buy ${avg_buy:.2f}")
    if cost_eur:
        parts.append(f"cost €{cost_eur:.2f}")
    if bought_pct:
        parts.append(f"bought at {bought_pct:.0f}% of portfolio")
    if current_price and avg_buy:
        pnl_pct = (current_price - avg_buy) / avg_buy * 100
        parts.append(f"P&L {pnl_pct:+.1f}%")
    pct_today = price_data.get("pct_change", 0)
    parts.append(f"today {pct_today:+.1f}%")
    week_pct = price_data.get("week_pct")
    if week_pct is not None:
        parts.append(f"5d {week_pct:+.1f}%")
    return " | ".join(parts)


def build_prompt(
    portfolio: dict,
    prices: dict,
    news: dict,
    market_session: str | None = None,
) -> str:
    utc_now = datetime.now(timezone.utc)
    session = market_session or get_market_session(utc_now)

    cash = portfolio["cash"]
    holdings = portfolio.get("holdings", [])

    total_eur = cash + sum(
        (prices.get(h["ticker"], {}).get("price") or 0) * h["shares"] * prices.get(h["ticker"], {}).get("eur_rate", 1)
        for h in holdings
    )
    # Simpler: use cost basis as proxy if no FX rate available
    total_eur_approx = cash + sum(h.get("total_cost_eur", 0) for h in holdings)

    lines = []

    lines.append("## CONTEXT")
    lines.append(f"timestamp_utc: {utc_now.strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append(f"market_session: {session}")
    lines.append(f"total_portfolio_eur (approx): €{total_eur_approx:.2f}")
    lines.append(f"cash_available: €{cash:.2f}  ({cash / total_eur_approx * 100:.1f}% of portfolio)")
    lines.append("")

    lines.append("## CURRENT HOLDINGS")
    if holdings:
        for h in holdings:
            lines.append(_holding_line(h, prices, total_eur_approx))
            ticker = h["ticker"]
            headlines = news.get(ticker, [])
            for hl in headlines:
                lines.append(f"  - {hl}")
            if not headlines:
                lines.append("  - No recent headlines")
    else:
        lines.append("None — portfolio is all cash.")
    lines.append("")

    lines.append("## MARKET NEWS")
    general = news.get("__general__", [])
    if general:
        for hl in general:
            lines.append(f"- {hl}")
    else:
        lines.append("- No general market headlines available")
    lines.append("")

    lines.append("## OPPORTUNITIES (news-driven)")
    lines.append("Review the following tickers with notable news this session:")
    opportunity_tickers = [t for t in news if t != "__general__" and t not in {h["ticker"] for h in holdings}]
    if opportunity_tickers:
        for ticker in opportunity_tickers:
            price_data = prices.get(ticker, {})
            price_str = f"${price_data['price']:.2f}" if price_data.get("price") else "N/A"
            pct = price_data.get("pct_change", 0)
            lines.append(f"{ticker}: {price_str}  {pct:+.1f}%")
            for hl in news[ticker]:
                lines.append(f"  - {hl}")
    else:
        lines.append("None beyond current holdings.")
    lines.append("")

    lines.append("## TASK")
    lines.append("Return the strict JSON object specified by the system prompt.")
    lines.append("Cover every current holding. Add any new positions you identify as high-conviction opportunities.")

    return "\n".join(lines)


def parse_response(raw: str) -> dict:
    cleaned = raw.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", cleaned)
    if match:
        cleaned = match.group(1).strip()
    else:
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(f"Claude returned invalid JSON: {e}\nRaw: {raw}") from e


def analyse(
    portfolio: dict,
    prices: dict,
    news: dict,
    api_key: str,
    market_session: str | None = None,
) -> dict:
    client = anthropic.Anthropic(api_key=api_key)
    prompt = build_prompt(portfolio, prices, news, market_session=market_session)

    try:
        response = client.messages.create(
            model=_MODEL,
            max_tokens=8192,
            temperature=0,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.APIError as exc:
        raise RuntimeError(f"Claude API call failed: {exc}") from exc

    if response.stop_reason == "max_tokens":
        logger.warning("Claude response truncated; JSON may be incomplete")

    result = parse_response(response.content[0].text)

    result.setdefault("market_session", market_session or get_market_session())
    result.setdefault("overall_confidence", "low")
    result.setdefault("risks", [])

    logger.info(
        "analyse complete: %d actions, session=%s, confidence=%s",
        len(result.get("actions", [])),
        result["market_session"],
        result["overall_confidence"],
    )
    return result
