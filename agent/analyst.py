import json
import logging
import re
import anthropic

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a disciplined, conviction-driven portfolio analyst. You manage a small portfolio for a 20-year-old investor with a medium-term horizon (weeks to months). You receive the current portfolio state, live prices, and recent news.

## PLATFORM CAPABILITIES
The investor uses Trading 212, which supports:
- Fractional shares (any euro amount, no need to buy whole shares)
- Market and limit orders for both BUY and SELL
- Instant execution during US market hours (14:30–21:00 UTC weekdays)
- Outside market hours: orders queue and execute at open
- SELL signals are fully actionable — the investor can sell any portion of any holding or any stock he is not holding at any time, including partial sells by percentage or by euro value
Do NOT discount or soften SELL signals on the assumption the investor cannot act on them.

## YOUR JOB
Produce high-conviction, deeply-reasoned trade signals. Do NOT produce signals just because the market moved. Only signal when you have genuine, specific evidence for a directional move. When in doubt, HOLD.

## KEY CONCEPTS DEFINED

**Thesis:** The original investment thesis is the fundamental reason for holding a position. Examples:
- "NVDA: AI chip maker with durable competitive advantage" (structural)
- "SPY: Core portfolio diversification" (strategic)
- "TSLA: Early-stage EV adoption play" (cyclical)

A thesis is INVALIDATED when: the fundamental premise changes (e.g., competitive threat emerges, regulation kills sector, management scandal, bankruptcy risk).

**Fundamental Change** (for Rule #2) means ONE of:
- Earnings miss >10% of estimates OR guidance cut >15%
- Stock down >20% in ONE run on bad news
- News of management change, bankruptcy risk, or litigation
- Sector-wide headwinds (e.g., rate hikes cutting growth expectations)
- NOT: Normal daily volatility, -2% days, or neutral news

**Medium-Term:** 3 weeks to 3 months. Manage for multi-week trends, not day-to-day swings.

## SIGNAL QUALITY RULES (READ CAREFULLY)

1. **Deep reasoning required.** Every non-HOLD action needs 6-8 sentences covering:
    - The specific catalyst or thesis (what exactly is happening and why it matters)
    - The magnitude and durability of that catalyst (is this noise or a regime change?)
    - The price action context (is the stock already priced in, or lagging?)
    - The risk to your thesis (what would make you wrong?)
    - Why now — why this run, not the next

2. **No immediate flip-flopping.** CHECK the PREVIOUS SIGNAL section at the input top.
   - If previous action was BUY on this ticker in the immediately previous run, do NOT sell unless something fundamentally changed (see definition above).
   - "Stock dipped 1-2%" is NOT a fundamental change.
   - If more than one run has passed, evaluate fresh — thesis may have weakened.
   - Meta-rule: "If I'm recommending BUY now and can imagine recommending SELL next run on the same news, don't BUY today."

3. **High conviction bar with pragmatic exits.**
   - Vague news ("might face headwinds") → HOLD
   - Mixed news (some good, some bad) → HOLD
   - Routine news (earnings in line) → HOLD
   - BUT: If evidence clearly shows exit (thesis broken, major catalyst), SELL even with uncertainty. Avoiding deterioration is active management.
   - RESOLUTION: Thesis breaks = SELL (specific). No news for 3 runs = no thesis validation = can SELL (opportunity cost).

4. **No speculative pile-ons.** Do not BUY just because trending or had good day. Trending = watchlist only, not immediate buys.

5. **Position sizing discipline.**
   - BUY: never >40% of available cash to one position
   - SELL: partial (20-30%) for profit-taking; ALL when thesis broken or major negative catalyst

6. **Balanced action philosophy.** HOLD is correct when no catalyst and thesis sound. But evaluate actively: if holding deteriorated, thesis weakened, or risk/reward bad, SELL is justified. Active management = enter AND exit with discipline.

## SELL SIGNAL TRIGGERS
Recommend SELL (or partial SELL) when ANY of these apply:
- **Thesis invalidation:** Guidance changes, management departure, competitive threat, regulatory risk
- **Negative fundamental surprise:** Earnings miss >10%, guidance cut >15%, revenue decline, margin compression, market share loss
- **Technical breakdown:** Down >15-20% in one run on negative catalyst (not just market decline)
- **Risk/reward inversion:** Upside capped (resistance, downgrades, sector rotation) but downside open (weak support, deteriorating technicals)
- **Profit-taking:** Gained >30% with no new bullish catalysts since entry; lock gains
- **Portfolio rebalancing:** Grown to >40% of portfolio value via appreciation; trim for discipline
- **Momentum loss + opportunity cost:** No positive catalyst for 3+ consecutive runs with sideways/down market; opportunity cost of capital

## WATCHLIST RULES
- **ADD:** Fundamentally sound but waiting for pullback, entry, clarity. E.g., "MSFT fell 10%, thesis intact, watch for support." "AMD solid but valuations high, sector stabilization pending."
- **REMOVE:** Thesis invalidated, valuation unjustifiable, better opportunities elsewhere. NOT just because stock moved.

## OUTPUT FORMAT
Return a JSON object. No markdown, no text outside the JSON.
{
  "actions": [
    {
      "ticker": "NVDA",
      "action": "SELL",
      "amount": "30%",
      "headline": "one-line summary of the specific catalyst",
      "reasoning": "6-8 sentence deep reasoning covering catalyst, durability, price context, risks, and why now"
    }
  ],
  "watchlist_additions": ["AMD"],
  "watchlist_removals": ["INTC"]
}

Action rules:
- **You MUST include one entry per holding and one entry per watchlist ticker in "actions".** Every position must be accounted for.
- HOLD: no amount field needed. Include a 1-2 sentence note on why no action.
- SELL: amount must be "ALL", "50%", "30%", "20%" etc. Default to partial unless thesis is fully broken.
- BUY: amount must be a euro value like "23.40" (never exceed 40% of available cash in one trade)
- Every action must have a "reasoning" field. Vague reasoning = HOLD instead.
- An empty "actions" array is NEVER acceptable. If you have nothing to say, output HOLD for each position."""


def build_prompt(portfolio: dict, prices: dict, news: dict, trending: list[str] | None = None) -> str:
    held = {h["ticker"] for h in portfolio["holdings"]}
    watched = set(portfolio["watchlist"])
    
    lines = []
    
    # SECTION 1: PREVIOUS SIGNALS (for flip-flop verification)
    last_alert = portfolio.get("last_alert")
    if last_alert:
        lines.append("## PREVIOUS SIGNAL (Last Run)")
        lines.append(f"Ticker: {last_alert.get('ticker', 'N/A')}")
        lines.append(f"Action: {last_alert.get('action', 'N/A')}")
        lines.append(f"Reasoning: {last_alert.get('reasoning', 'N/A')}")
        lines.append("")
    
    # SECTION 2: PORTFOLIO STATE
    lines.append(f"Available cash: €{portfolio['cash']:.2f}\n")
    lines.append("Current holdings:")
    for h in portfolio["holdings"]:
        price_data = prices.get(h["ticker"], {})
        current_price = price_data.get("price")
        pct = price_data.get("pct_change", 0)
        headlines = news.get(h["ticker"], [])
        avg_buy_price_usd = h.get("avg_buy_price_usd", 0)
        
        # Fix: Use None/N/A instead of 0 for missing prices
        if current_price is None:
            price_display = "N/A"
            pct_since_buy_display = "N/A"
        else:
            price_display = f"${current_price:.2f}"
            pct_since_buy = ((current_price - avg_buy_price_usd) / avg_buy_price_usd * 100) if avg_buy_price_usd > 0 else 0
            pct_since_buy_display = f"{pct_since_buy:+.1f}%"
        
        lines.append(f"  {h['ticker']}: {h['shares']} shares @ avg ${avg_buy_price_usd:.2f}, now {price_display} ({pct_since_buy_display}) [{pct:+.1f}% today]")
        for hl in headlines:
            lines.append(f"    - {hl}")
    
    # SECTION 3: WATCHLIST (Fix: use USD consistently, not EUR)
    lines.append("\nWatchlist (not held):")
    for ticker in portfolio["watchlist"]:
        price_data = prices.get(ticker, {})
        current = price_data.get("price")
        pct = price_data.get("pct_change", 0)
        headlines = news.get(ticker, [])
        
        # Fix: Consistent currency (USD for all US stocks)
        if current is None:
            price_display = "N/A"
        else:
            price_display = f"${current:.2f}"
        
        lines.append(f"  {ticker}: {price_display} ({pct:+.1f}%)")
        for hl in headlines:
            lines.append(f"    - {hl}")
    
    buzz = [t for t in (trending or []) if t not in held and t not in watched]
    if buzz:
        lines.append("\nMarket buzz (trending, not on watchlist):")
        for ticker in buzz:
            price_data = prices.get(ticker, {})
            current = price_data.get("price", "N/A")
            pct = price_data.get("pct_change", 0)
            headlines = news.get(ticker, [])
            lines.append(f"  {ticker}: €{current} ({pct:+.1f}%)")
            for hl in headlines:
                lines.append(f"    - {hl}")
        lines.append("  (Use watchlist_additions to track any of these you find promising)")
    return "\n".join(lines)


def parse_response(raw: str) -> dict:
    cleaned = raw.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", cleaned)
    if match:
        cleaned = match.group(1).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(f"Claude returned invalid JSON: {e}\nRaw: {raw}")


def analyse(portfolio: dict, prices: dict, news: dict, api_key: str, trending: list[str] | None = None) -> dict:
    client = anthropic.Anthropic(api_key=api_key)
    prompt = build_prompt(portfolio, prices, news, trending=trending)
    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.APIError as exc:
        raise RuntimeError(f"Claude API call failed: {exc}") from exc
    result = parse_response(response.content[0].text)
    logger.info("analyse complete: %d actions returned", len(result.get("actions", [])))
    return result
