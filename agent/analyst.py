import json
import logging
import re
import anthropic

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a short-term trading analyst managing a small portfolio for a 20-year-old investor.
Your goal is to maximize returns over weeks to months. You receive the current portfolio, prices, and news.
You must return a JSON object with this exact structure:
{
  "actions": [
    {
      "ticker": "NVDA",
      "action": "SELL",
      "amount": "30%",
      "headline": "one-line news summary",
      "reasoning": "2-3 sentence explanation"
    }
  ],
  "watchlist_additions": ["AMD"],
  "watchlist_removals": ["INTC"]
}
Action rules:
- HOLD: no amount field needed
- SELL: amount must be "ALL", "50%", "30%", "20%" etc (percentage of holding)
- BUY: amount must be a euro value like "23.40" (based on available cash — never exceed cash balance)
Only return valid JSON. No markdown, no explanation outside the JSON."""


def build_prompt(portfolio: dict, prices: dict, news: dict) -> str:
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


def analyse(portfolio: dict, prices: dict, news: dict, api_key: str) -> dict:
    client = anthropic.Anthropic(api_key=api_key)
    prompt = build_prompt(portfolio, prices, news)
    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.APIError as exc:
        raise RuntimeError(f"Claude API call failed: {exc}") from exc
    result = parse_response(response.content[0].text)
    logger.info("analyse complete: %d actions returned", len(result.get("actions", [])))
    return result
