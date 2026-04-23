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

## SIGNAL QUALITY RULES (READ CAREFULLY)
1. **Deep reasoning required.** Every non-HOLD action needs 6-8 sentences of reasoning covering:
   - The specific catalyst or thesis (what exactly is happening and why it matters)
   - The magnitude and durability of that catalyst (is this noise or a regime change?)
   - The price action context (is the stock already priced in, or lagging?)
   - The risk to your thesis (what would make you wrong?)
   - Why now — why this run, not the next
2. **No immediate flip-flopping.** If a position was bought in the IMMEDIATELY PREVIOUS RUN ONLY, do NOT sell it unless something fundamentally changed. "The stock dipped" is not a reason to sell something you bought yesterday. However, if more than one run has passed, evaluate with fresh eyes—do not hold a thesis just because you bought it recently. If you find yourself recommending a BUY and can imagine recommending a SELL in the next few runs, do NOT recommend the BUY.
3. **High conviction bar.** Only recommend BUY or SELL if you have strong, specific evidence. If the news is vague, mixed, or routine, HOLD is appropriate. But if evidence suggests exit, do not stay silent just to be cautious. A wrong signal is worse than no signal, but so is ignoring a deteriorating position.
4. **No speculative pile-ons.** Do not BUY into a stock just because it is trending or had a good day. Trending tickers are for watchlist consideration only, not immediate buys.
5. **Position sizing discipline.** For BUY: never allocate more than 40% of available cash to a single position. For SELL: partial sells (20-30%) are appropriate for profit-taking; ALL is reserved for when the thesis is broken or a major negative catalyst has hit.
6. **Balanced action philosophy.** HOLD is appropriate when there is no strong catalyst and the thesis remains sound. But evaluate actively: if a holding has deteriorated, thesis is weakened, or risk/reward is unfavorable, SELL is justified even without a "perfect" catalyst. Active portfolio management means both entering and exiting with discipline.

## SELL SIGNAL TRIGGERS
Recommend SELL (or partial SELL) when ANY of these apply:
- **Thesis invalidation:** The original reason for holding no longer applies (e.g., company guidance changes, management departure, competitive threat materializes)
- **Negative fundamental surprise:** Earnings miss >10%, guidance cut, revenue decline, margin compression, or loss of market share
- **Technical breakdown:** Stock breaks key support + negative news; stock down >15% in one run without offsetting positive catalyst
- **Risk/reward inversion:** Upside is capped (strong resistance, analyst downgrades, sector rotation) but downside is open (weak support, deteriorating technicals)
- **Profit-taking:** Position up >30% in <2 months with no new bullish catalysts; lock in gains
- **Portfolio rebalancing:** Holding has grown to >40% of portfolio value due to appreciation; trim to rebalance
- **Momentum loss:** No positive catalyst for 2+ runs while market moves sideways or down; better opportunities elsewhere

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
    
    # Calculate total portfolio value and apply overnight interest
    total_value_usd = 0
    for h in portfolio["holdings"]:
        price_data = prices.get(h["ticker"], {})
        current_price = price_data.get("price", 0)
        total_value_usd += current_price * h["shares"]
    
    # Add cash (assuming portfolio["cash"] is in EUR, convert to approximate USD)
    total_value_usd += portfolio["cash"] * 1.09  # rough EUR to USD conversion
    
    # Apply overnight interest: 0.0694% = 0.000694
    interest_charge = total_value_usd * 0.000694
    
    lines = [f"Available cash: €{portfolio['cash']:.2f}\n"]
    lines.append(f"Overnight interest charge: ${interest_charge:.4f}\n")
    lines.append("Current holdings:")
    for h in portfolio["holdings"]:
        price_data = prices.get(h["ticker"], {})
        current_usd = price_data.get("price", 0)
        pct = price_data.get("pct_change", 0)
        headlines = news.get(h["ticker"], [])
        avg_buy_price_usd = h.get("avg_buy_price_usd", 0)
        pct_since_buy = ((current_usd - avg_buy_price_usd) / avg_buy_price_usd * 100) if avg_buy_price_usd > 0 else 0
        lines.append(f"  {h['ticker']}: {h['shares']} shares @ avg ${avg_buy_price_usd:.2f}, now ${current_usd:.2f} ({pct_since_buy:+.1f}%)")
        for hl in headlines:
            lines.append(f"    - {hl}")
    lines.append("\nWatchlist (not held):")
    for ticker in portfolio["watchlist"]:
        price_data = prices.get(ticker, {})
        current = price_data.get("price", "N/A")
        pct = price_data.get("pct_change", 0)
        headlines = news.get(ticker, [])
        lines.append(f"  {ticker}: €{current} ({pct:+.1f}%)")
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
