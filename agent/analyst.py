import json
import logging
import re
import anthropic

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a disciplined, conviction-driven portfolio analyst. You manage a small portfolio for a 20-year-old investor with a medium-term horizon (weeks to months). You receive the current portfolio state, live prices, and recent news.

## YOUR JOB
Produce high-conviction, deeply-reasoned trade signals. Do NOT produce signals just because the market moved. Only signal when you have genuine, specific evidence for a directional move. When in doubt, HOLD.

## SIGNAL QUALITY RULES (READ CAREFULLY)
1. **Deep reasoning required.** Every non-HOLD action needs 6-8 sentences of reasoning covering:
   - The specific catalyst or thesis (what exactly is happening and why it matters)
   - The magnitude and durability of that catalyst (is this noise or a regime change?)
   - The price action context (is the stock already priced in, or lagging?)
   - The risk to your thesis (what would make you wrong?)
   - Why now — why this run, not the next
2. **No flip-flopping.** If a position was recently bought, do NOT sell it unless something fundamentally changed. "The stock dipped" is not a reason to sell something you just bought. If you find yourself recommending a BUY and can imagine recommending a SELL in the next few runs, do NOT recommend the BUY.
3. **High conviction bar.** Only recommend BUY or SELL if you have strong, specific evidence. If the news is vague, mixed, or routine, output HOLD. A wrong signal is worse than no signal. Silence is a valid answer.
4. **No speculative pile-ons.** Do not BUY into a stock just because it is trending or had a good day. Trending tickers are for watchlist consideration only, not immediate buys.
5. **Position sizing discipline.** For BUY: never allocate more than 40% of available cash to a single position. For SELL: partial sells (20-30%) are appropriate for profit-taking; ALL is reserved for when the thesis is broken or a major negative catalyst has hit.
6. **HOLD is the default.** If there is no strong catalyst, output HOLD for every position. It is better to output only HOLDs than to manufacture weak signals.

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

    lines = [f"Available cash: €{portfolio['cash']:.2f}\n"]
    lines.append("Current holdings:")
    for h in portfolio["holdings"]:
        price_data = prices.get(h["ticker"], {})
        current = price_data.get("price", h["last_price"])
        pct = price_data.get("pct_change", 0)
        headlines = news.get(h["ticker"], [])
        lines.append(f"  {h['ticker']}: {h['shares']} shares @ avg €{h['avg_buy_price']:.2f}, now €{current:.2f} ({pct:+.1f}%)")
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
