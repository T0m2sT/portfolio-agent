# Portfolio Agent

An AI-powered stock trading bot that monitors individual stocks up to 10 times per day, generates aggressive BUY/SELL/HOLD signals using Claude, and delivers them via Telegram. Runs entirely on GitHub Actions (agent) and Railway (Telegram bot server).

---

## How it works

### 1. Scheduled runs (GitHub Actions)

The agent runs automatically on this UTC schedule, clustered around US market hours:

| UTC | Lisbon (summer) | Purpose |
|-----|-----------------|---------|
| 08:00 | 09:00 | Your market open |
| 10:00 | 11:00 | Mid-morning |
| 13:00 | 14:00 | Pre-US open |
| 14:30 | 15:30 | US market open |
| 16:00 | 17:00 | US open momentum |
| 17:00 | 18:00 | US mid-session |
| 18:00 | 19:00 | US mid-session |
| 19:00 | 20:00 | Pre-US close |
| 20:30 | 21:30 | US market close |
| 22:00 | 23:00 | After-hours wrap |

You can also trigger a run manually via **Actions → Run workflow**.

---

### 2. Market calendar check

Before doing anything, the agent checks if today is a US trading day via the Finnhub holiday calendar. If it's a weekend or public holiday, the run exits silently — no prices fetched, no Claude call, no Telegram message. This check is date-based (not real-time market status), so pre-market and after-hours runs are never skipped.

---

### 3. Market session detection

The agent determines the current US market session using Eastern Time:

| Session | ET window | Behaviour |
|---------|-----------|-----------|
| `pre-market` | 04:00–09:30 | Low price reliability; prioritise overnight catalysts |
| `regular` | 09:30–16:00 | Full signal confidence; best window for action |
| `after-hours` | 16:00–20:00 | Medium-low reliability; focus on earnings/breaking news |
| `closed` | otherwise | Price movement ignored; watchlist changes only |

The session is passed through every stage of the run — fetcher, analyst prompt, and stored in portfolio state — so Claude always knows what reliability to assign to the price data.

---

### 4. Data fetching

The agent fetches data for every ticker in your holdings plus a set of market-pulse instruments (SPY, QQQ, IWM, GLD, SLV, USO, BTC-USD, ETH-USD, TLT, HYG):

- **Live prices** (Finnhub API, with yfinance fallback) — current price, today's % change, day high/low, 5-day high/low, week-over-week % change
- **News headlines** (Finnhub company news primary, NewsAPI fallback) — up to 8 headlines per held ticker, up to 5 per market-pulse ticker, up to 20 general market headlines; explicitly marked "No recent headlines" when empty
- **Opportunity tickers** — any ticker that appears in news but is not currently held is fetched for prices and surfaced as a potential new position

---

### 5. Claude analysis

All data is sent to Claude (`claude-sonnet-4-6`, `temperature=0`) with a structured prompt. Claude returns:

- **`actions`** — one entry per holding and any new opportunity tickers: `BUY`, `SELL`, or `HOLD` with amount (% and EUR), `company_name`, per-action `confidence`, and reasoning
- **`overall_confidence`** — `low / medium / high` for the full run
- **`risks`** — data quality issues or key uncertainties flagged by Claude

The prompt includes:

- **Market session** — Claude adapts signal aggressiveness to the session (pre-market signals favour watchlist additions over immediate buys)
- **Portfolio allocation %** — each holding's share of total EUR value at cost basis
- **5-day price context** — weekly range and trend, not just today's move
- **News quality filter** — Claude discards vague, recycled, or tangentially related headlines

Claude's strategy:
- News is the primary signal — a strong, direct headline is enough to act
- SELL signals can be issued for **any stock**, including ones not in the portfolio (short positions)
- Only suggest tickers available on **Trading 212** (no OTC/pink sheets)
- HOLD only when there is genuinely no edge
- Every non-HOLD action names the specific catalyst, assesses its magnitude, and includes the company name

---

### 6. Signals and output

**High-confidence non-HOLD signals:** each one is sent as an individual Telegram alert with the company name, headline, price, confidence level, and reasoning.

**If no high-confidence signal exists:** a single "NO ACTION" message is sent with the timestamp.

---

### 7. Portfolio state update

After each run, `portfolio.json` is committed back to the repo with:
- Updated holdings and cash
- `last_market_session`, `last_analysis_confidence`, `last_analysis_risks`
- Last alert (for `/reason`)
- Timestamp of last run

---

## Telegram bot commands

The bot server runs on Railway and listens for commands 24/7.

| Command | Description |
|---------|-------------|
| `/portfolio` | Current holdings, cash balance, cost basis, and % of portfolio |
| `/log` | Closed trade history with P&L per trade and total |
| `/status` | Last agent run time and next scheduled run (Lisbon time) |
| `/reason` | Full reasoning behind the last BUY/SELL alert, with confidence and risks |
| `/buy TICKER SHARES PRICE_USD COST_EUR` | Record a buy (e.g. `/buy NVDA 2 118.40 221.35`) |
| `/buy TICKER BUY_PCT% PROCEEDS_EUR` | Close a partial short position (e.g. `/buy NVDA 50% 120.00`) |
| `/sell TICKER SELL_PCT% PROCEEDS_EUR` | Sell a % of a held position (e.g. `/sell NVDA 50% 358.40`) |
| `/sell TICKER SHARES PRICE_USD COST_EUR` | Record a short sell (e.g. `/sell TSLA 1 250.00 23.00`) |
| `/reset` | Wipe portfolio back to €5000 clean state |
| `/help` | Show all available commands |

---

## Project structure

```
agent/
  main.py          # Orchestrates the full run cycle
  session.py       # Market session detection and trading day check
  analyst.py       # Claude prompt engineering and response parsing
  fetcher.py       # Price, news, and market-pulse data fetching
  portfolio.py     # Portfolio state management (load, save, apply actions)
  notifier.py      # Telegram message formatting and sending

bot/
  server.py        # Flask webhook server for Telegram bot commands

tests/             # Full test suite (108 tests)

.github/workflows/
  portfolio-agent.yml   # Scheduled GitHub Actions workflow

portfolio.json     # Live portfolio state (auto-committed after each run)
```

---

## Environment variables

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Claude API key |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token |
| `TELEGRAM_CHAT_ID` | Your Telegram chat ID |
| `NEWS_API_KEY` | NewsAPI key (fallback news source and general market headlines) |
| `FINNHUB_API_KEY` | Finnhub API key (real-time prices, news, holiday calendar) |
| `GITHUB_TOKEN` | GitHub token (bot server writes portfolio.json via API) |
| `GITHUB_REPO` | Repo in `owner/name` format |
| `PORTFOLIO_RAW_URL` | Raw URL to `portfolio.json` in the repo |
| `CLAUDE_MODEL` | Optional — override Claude model (default: `claude-sonnet-4-6`) |
| `TELEGRAM_WEBHOOK_SECRET` | Optional — validates incoming Telegram webhook requests |

GitHub Actions secrets: `ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `NEWS_API_KEY`, `FINNHUB_API_KEY`.

Railway env vars: all of the above plus `GITHUB_TOKEN`, `GITHUB_REPO`, `PORTFOLIO_RAW_URL`.
