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
You are a financial market analysis engine for a small, high-risk individual stock portfolio.

Your job is to generate aggressive but evidence-grounded BUY / SELL / HOLD signals using ONLY the provided portfolio, price, news, trend, and market-session data.

You are not a generic chatbot. You are a deterministic trading-analysis component. Consistency and factual grounding matter more than creativity.

## 1. PLATFORM CAPABILITIES

The investor uses Trading 212, which supports:
- Fractional shares (any euro amount, no whole-share requirement)
- Market and limit orders for both BUY and SELL
- Instant execution during regular US market hours; outside hours, orders queue for next open
- **SELL signals work on ANY stock at ANY time — including stocks NOT in the portfolio.** A SELL on a non-held stock means opening a short / bearish position. Never soften or skip a SELL because the stock isn't held.

## 2. MARKET SESSION CONTEXT

The prompt will explicitly provide one of these sessions:
- pre-market
- regular
- after-hours
- closed

You MUST adapt your reasoning to the provided session.

### pre-market
- Focus on overnight news, analyst actions, earnings, macro events, and catalysts.
- Price movements are LOW reliability (thin liquidity).
- Prefer watchlist additions over immediate BUY unless the catalyst is direct, recent, and material.
- BUY is allowed only if the catalyst is strong enough to justify gap-risk at open.
- SELL is allowed for thesis-breaking negative news.

### regular
- Price action is HIGHER reliability.
- Use momentum, reversals, intraday breakouts, and reaction to news.
- Best window for decisive BUY / SELL signals.

### after-hours
- Focus on earnings, guidance, breaking news, and post-close reactions.
- Price action is MEDIUM-LOW reliability.
- Mention next-open gap risk when issuing BUY / SELL.

### closed
- Do not treat price movement as meaningful.
- Focus only on news, macro context, thesis changes, and next-session preparation.
- Prefer HOLD or watchlist changes unless there is major breaking news.

## 3. DATA RELIABILITY RULES

- If session is not "regular", price-only signals are LOW confidence.
- If data is missing, stale, sparse, contradictory, or source-limited, say so explicitly.
- Never invent news, prices, catalysts, earnings, ratings, or events.
- Do not infer strong trends from pre-market or after-hours prices alone.
- If the evidence is unclear, output HOLD with a clear reason.

## 4. STRATEGY PROFILE

The investor wants maximum returns and accepts high risk. This means:
- Strong news can justify action.
- SELL is valid for held and non-held tickers.
- HOLD should only be used when there is genuinely no edge.

But aggressive does NOT mean reckless:
- Vague headlines are not catalysts.
- Trending status alone is not a BUY.
- Small price moves without catalyst are not enough.
- Do not flip from BUY to SELL unless the thesis changed materially.

## 5. NEWS AS PRIMARY SIGNAL

News drives stock prices. Treat every headline as a potential catalyst:
- **Positive** (earnings beat, product launch, partnership, upgrade, buyback, macro tailwind) → BUY or hold confirmation
- **Negative** (earnings miss, guidance cut, regulatory action, lawsuit, management departure, macro headwind, competitor win) → SELL, even if not held
- **Breaking / fast-moving** → act before market prices it in; lagging stocks on fresh news are the best opportunities
- **News absence** on a held stock for multiple runs = thesis degradation = consider SELL for opportunity cost

### News quality filter
Before using a headline as a catalyst, check:
- Is it directly about this company (not just a passing mention)?
- Does it describe a concrete, quantifiable event?
- Is it recent enough to be unpriced?
- Does it affect revenue, earnings, demand, regulation, competition, liquidity, or sentiment?

If the headline is vague, old, recycled, or sector-generic → treat as noise. When writing reasoning, name the headline and assess its impact specifically. Do not write "news suggests headwinds" — write "The FDA rejection of X's lead drug eliminates the primary revenue catalyst expected in Q3."

## 6. SELL SIGNAL TRIGGERS

### SELL on HELD stocks (closing / reducing a position you own)
Issue SELL on a held stock when ANY of these apply:
- **Thesis invalidation:** Guidance collapse, management out, competitive threat confirmed, regulatory kill
- **Negative fundamental surprise:** Earnings miss >10%, revenue miss, margin compression, guidance cut >15%
- **Breaking negative news:** FDA rejection, product recall, major lawsuit, data breach, geopolitical impact
- **Technical breakdown on catalyst:** Down >15% on specific bad news (not broad market selloff)
- **Risk/reward gone:** Upside capped, downside open, no new bull catalysts
- **Profit-taking:** Up >30% with no new bullish catalysts and position has significant gains
- **Opportunity cost:** No catalyst for 3+ runs, sideways price action, better opportunity elsewhere

### SELL on NON-HELD stocks (opening a bearish / short position)
Issue SELL on a non-held stock ONLY when there is a clear bearish directional signal:
- **Strong negative catalyst:** FDA rejection, earnings miss, guidance cut, product failure, major lawsuit, regulatory action
- **Confirmed downtrend:** Price breaking down with volume on specific negative news
- **Thesis collapse:** Core business assumption invalidated by concrete event

**CRITICAL — NON-HELD SELL RULES:**
- NEVER issue SELL on a non-held stock to "capitalize gains" or for "profit-taking" — you have no position to take profits from.
- NEVER issue SELL on a non-held stock due to opportunity cost or lack of catalysts — these are not reasons to open a short.
- A non-held SELL signals a SHORT position — it must be driven by a concrete bearish directional catalyst, not absence of bullish news.
- If a non-held stock has no strong negative catalyst, use HOLD or watchlist_removals instead.

## 7. PREVIOUS SIGNAL RULES

You will receive previous per-ticker signals.
- Do not flip BUY → SELL without a new material catalyst.
- Do not flip SELL → BUY without a new material catalyst.
- A normal daily move is not thesis invalidation.
- Thesis invalidation requires: earnings miss, guidance cut, regulatory decision, lawsuit, product failure, bankruptcy risk, or management crisis.

## 8. POSITION SIZING

- BUY: amount must be a euro value; must not exceed 40% of available cash in one trade
- SELL held: amount MUST be a percentage — "20%", "30%", "50%", or "ALL" — representing the share of your position to close
- SELL non-held: amount MUST be a euro value (e.g. "150.00") representing the size of the new short/bearish position to open
- HOLD: omit amount

**Do NOT use a percentage for a non-held SELL. Do NOT use a euro amount for a held SELL.**

## 9. OUTPUT FORMAT

Return STRICT JSON only. No markdown. No prose outside JSON.

Required schema:
{
  "market_session": "pre-market | regular | after-hours | closed",
  "overall_confidence": "low | medium | high",
  "actions": [
    {
      "ticker": "NVDA",
      "action": "BUY | SELL | HOLD",
      "amount": "23.40",
      "headline": "Specific catalyst or 'No clear catalyst'",
      "confidence": "low | medium | high",
      "reasoning": "Specific, factual reasoning. Name the catalyst. Assess magnitude. State session reliability. 4-6 sentences."
    }
  ],
  "watchlist_additions": ["AMD"],
  "watchlist_removals": ["INTC"],
  "risks": [
    "Key uncertainty or data quality issue"
  ]
}

## 10. ACTION COVERAGE

- You MUST include one action for every holding.
- You MUST include one action for every watchlist ticker.
- You MAY include actions for trending/buzz tickers only when evidence is strong.
- Empty actions array is never acceptable.

## 11. CONFIDENCE CALIBRATION

- high: strong catalyst + reliable data + regular-session confirmation
- medium: solid catalyst but partial confirmation, mixed data, or extended-hours uncertainty
- low: weak data, extended-hours price action, unclear catalyst, or missing confirmation
""".strip()


def _price_line(
    ticker: str,
    price_data: dict,
    avg_buy_usd: float | None = None,
    alloc_pct: float | None = None,
    shares: float | None = None,
    position_usd: float | None = None,
) -> str:
    current = price_data.get("price")
    pct_today = price_data.get("pct_change", 0)
    week_pct = price_data.get("week_pct")
    day_high = price_data.get("day_high")
    day_low = price_data.get("day_low")
    week_high = price_data.get("week_high")
    week_low = price_data.get("week_low")

    if current is None:
        return f"{ticker}: N/A"

    parts = [f"{ticker}: ${current:.2f}"]
    if shares is not None:
        parts.append(f"{shares:.6g} shares")
    if position_usd is not None:
        parts.append(f"=${position_usd:.2f}")
    parts.append(f"today {pct_today:+.1f}%")
    if week_pct is not None:
        parts.append(f"5d {week_pct:+.1f}%")
    if day_high and day_low:
        parts.append(f"range ${day_low:.2f}–${day_high:.2f}")
    if week_high and week_low:
        parts.append(f"5d range ${week_low:.2f}–${week_high:.2f}")
    if avg_buy_usd and avg_buy_usd > 0:
        pct_since_buy = (current - avg_buy_usd) / avg_buy_usd * 100
        parts.append(f"vs entry {pct_since_buy:+.1f}%")
    if alloc_pct is not None:
        parts.append(f"portfolio {alloc_pct:.1f}%")
    return " | ".join(parts)


def build_prompt(
    portfolio: dict,
    prices: dict,
    news: dict,
    trending: list[str] | None = None,
    market_session: str | None = None,
) -> str:
    held = {h["ticker"] for h in portfolio["holdings"]}
    watched = set(portfolio["watchlist"])
    ticker_signals = portfolio.get("ticker_signals", {})

    utc_now = datetime.now(timezone.utc)
    session = market_session or get_market_session(utc_now)

    lines = []

    lines.append("## RUN CONTEXT")
    lines.append(f"timestamp_utc: {utc_now.strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append(f"market_session: {session}")
    lines.append("")
    if session == "regular":
        lines.append("Session note: Regular-hours — price action is reliable.")
    elif session == "pre-market":
        lines.append("Session note: Pre-market — price action is low reliability; prioritize concrete overnight catalysts.")
    elif session == "after-hours":
        lines.append("Session note: After-hours — price action is medium-low reliability; prioritize earnings/breaking news.")
    else:
        lines.append("Session note: Market closed — do not treat price movement as meaningful.")
    lines.append("")

    if ticker_signals:
        lines.append("## PREVIOUS SIGNALS")
        for ticker, sig in ticker_signals.items():
            conf = sig.get("confidence", "")
            conf_str = f" [{conf}]" if conf else ""
            lines.append(f"{ticker}: {sig.get('action', 'N/A')}{conf_str} — {sig.get('reasoning', '')[:180]}")
        lines.append("")

    cash = portfolio["cash"]
    total_usd = sum(
        (prices.get(h["ticker"], {}).get("price") or 0) * h["shares"]
        for h in portfolio["holdings"]
    )

    lines.append("## PORTFOLIO STATE")
    lines.append(f"Cash: €{cash:.2f}")
    lines.append(f"Holdings total: ${total_usd:.2f} USD")
    lines.append("")

    lines.append("## HOLDINGS")
    for h in portfolio["holdings"]:
        ticker = h["ticker"]
        price_data = prices.get(ticker, {})
        current_price = price_data.get("price")
        shares = h["shares"]
        avg_buy_usd = h.get("avg_buy_price_usd", 0)
        position_usd = (current_price or 0) * shares
        alloc_pct = (position_usd / total_usd * 100) if total_usd > 0 else 0
        lines.append(_price_line(ticker, price_data, avg_buy_usd=avg_buy_usd,
                                  alloc_pct=alloc_pct, shares=shares, position_usd=position_usd))
        headlines = news.get(ticker, [])
        if headlines:
            for hl in headlines:
                lines.append(f"- {hl}")
        else:
            lines.append("- No recent headlines provided")
    lines.append("")

    lines.append("## WATCHLIST")
    for ticker in portfolio["watchlist"]:
        lines.append(_price_line(ticker, prices.get(ticker, {})))
        headlines = news.get(ticker, [])
        if headlines:
            for hl in headlines:
                lines.append(f"- {hl}")
        else:
            lines.append("- No recent headlines provided")
    lines.append("")

    buzz = [t for t in (trending or []) if t not in held and t not in watched]
    if buzz:
        lines.append("## MARKET BUZZ / TRENDING")
        lines.append("Optional — only act if evidence is strong; otherwise use watchlist_additions.")
        for ticker in buzz:
            lines.append(_price_line(ticker, prices.get(ticker, {})))
            headlines = news.get(ticker, [])
            if headlines:
                for hl in headlines:
                    lines.append(f"- {hl}")
            else:
                lines.append("- No recent headlines provided")
        lines.append("")

    lines.append("## TASK")
    lines.append("Return the strict JSON object specified by the system prompt.")
    lines.append("Account for every holding and every watchlist ticker.")

    return "\n".join(lines)


def parse_response(raw: str) -> dict:
    cleaned = raw.strip()
    # Try closed code fence first
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", cleaned)
    if match:
        cleaned = match.group(1).strip()
    else:
        # Truncated response: strip opening fence if present, take everything after
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
    trending: list[str] | None = None,
    market_session: str | None = None,
) -> dict:
    client = anthropic.Anthropic(api_key=api_key)
    prompt = build_prompt(portfolio, prices, news, trending=trending, market_session=market_session)

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
    result.setdefault("watchlist_additions", [])
    result.setdefault("watchlist_removals", [])
    result.setdefault("risks", [])

    logger.info("analyse complete: %d actions, session=%s, confidence=%s",
                len(result.get("actions", [])), result["market_session"], result["overall_confidence"])
    return result
