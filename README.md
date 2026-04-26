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

The agent fetches three types of data for every ticker in your holdings, watchlist, and trending stocks:

- **Live prices** (Finnhub API, with yfinance fallback) — current price, today's % change, day high/low, 5-day high/low, week-over-week % change
- **News headlines** (Finnhub company news primary, NewsAPI fallback) — up to 3 recent headlines per ticker; explicitly marked "No recent headlines provided" when empty
- **Trending tickers** (Yahoo Finance) — top 10 trending US stocks added as market buzz

---

### 5. Claude analysis

All data is sent to Claude (`claude-sonnet-4-6`, `temperature=0`) with a structured prompt. Claude returns:

- **`actions`** — one entry per holding and watchlist ticker: `BUY`, `SELL`, or `HOLD` with amount, headline, per-action `confidence`, and reasoning
- **`watchlist_additions` / `watchlist_removals`**
- **`overall_confidence`** — `low / medium / high` for the full run
- **`risks`** — data quality issues or key uncertainties flagged by Claude

The prompt includes:

- **Market session** — Claude adapts signal aggressiveness to the session (pre-market signals favour watchlist additions over immediate buys)
- **Per-ticker previous signals** — action, confidence, headline, and session from the last run, to prevent flip-flopping
- **Portfolio allocation %** — each holding's share of total USD value
- **5-day price context** — weekly range and trend, not just today's move
- **News quality filter** — Claude discards vague, recycled, or tangentially related headlines and says so explicitly

Claude's strategy:
- News is the primary signal — a strong, direct headline is enough to act
- SELL signals can be issued for **any stock**, including ones not in the portfolio (short positions)
- HOLD only when there is genuinely no edge
- Every non-HOLD action names the specific catalyst and assesses its magnitude

---

### 6. Signals and output

**If there are non-HOLD signals:** each one is sent as an individual Telegram alert with the headline, price, confidence level, and reasoning.

**If everything is HOLD:** a single summary message lists all positions and current prices.

---

### 7. Portfolio state update

After each run, `portfolio.json` is committed back to the repo with:
- Updated watchlist
- Per-ticker signals (action, confidence, headline, session) for flip-flop prevention
- `last_market_session`, `last_analysis_confidence`, `last_analysis_risks`
- Last alert (for `/reason`)
- Timestamp of last run

---

## Telegram bot commands

The bot server runs on Railway and listens for commands 24/7.

| Command | Description |
|---------|-------------|
| `/portfolio` | Current holdings, cash balance, and avg buy prices |
| `/log` | Closed trade history with P&L per trade and total |
| `/status` | Last agent run time and next scheduled run (Lisbon time) |
| `/reason` | Full reasoning behind the last BUY/SELL alert, with confidence and risks |
| `/buy TICKER SHARES PRICE_USD COST_EUR` | Record a buy (e.g. `/buy NVDA 2 880.00 40.00`) |
| `/sell TICKER SHARES\|%\|ALL PRICE_USD PROCEEDS_EUR` | Record a sell or short (e.g. `/sell NVDA ALL 900.00 82.00`) |
| `/watchlist add TICKER` | Add a ticker to the watchlist |
| `/watchlist remove TICKER` | Remove a ticker from the watchlist |
| `/reset` | Wipe portfolio back to €100 clean state |
| `/help` | Show all available commands |

---

## Project structure

```
agent/
  main.py          # Orchestrates the full run cycle
  session.py       # Market session detection and trading day check
  analyst.py       # Claude prompt engineering and response parsing
  fetcher.py       # Price, news, and trending data fetching
  portfolio.py     # Portfolio state management (load, save, apply actions)
  notifier.py      # Telegram message formatting and sending

bot/
  server.py        # Flask webhook server for Telegram bot commands

tests/             # Full test suite (107 tests)

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
| `NEWS_API_KEY` | NewsAPI key (fallback news source) |
| `FINNHUB_API_KEY` | Finnhub API key (real-time prices, news, holiday calendar) |
| `GITHUB_TOKEN` | GitHub token (bot server writes portfolio.json via API) |
| `GITHUB_REPO` | Repo in `owner/name` format |
| `PORTFOLIO_RAW_URL` | Raw URL to `portfolio.json` in the repo |
| `CLAUDE_MODEL` | Optional — override Claude model (default: `claude-sonnet-4-6`) |
| `TELEGRAM_WEBHOOK_SECRET` | Optional — validates incoming Telegram webhook requests |

GitHub Actions secrets: `ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `NEWS_API_KEY`, `FINNHUB_API_KEY`.

Railway env vars: all of the above plus `GITHUB_TOKEN`, `GITHUB_REPO`, `PORTFOLIO_RAW_URL`.
