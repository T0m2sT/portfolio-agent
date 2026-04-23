# 🚨 Critical Audit: Claude Portfolio Analyst Prompt

## FUNDAMENTAL ISSUES THAT CAN CAUSE HALLUCINATIONS & WRONG SIGNALS

---

## �� **CRITICAL ISSUE #1: No Historical Context**
**Risk Level:** CRITICAL

### The Problem
Claude receives **ONLY current prices and news**. Zero historical context about:
- When positions were opened
- At what price they were bought
- How long they've been held
- Previous signals on this ticker
- Whether this is the "immediately previous run" mentioned in rule #2

### What This Breaks
**Rule #2 violation:** "If a position was bought in the IMMEDIATELY PREVIOUS RUN ONLY, do NOT sell it"
- Claude **cannot know** if this was the previous run
- Claude will guess or assume
- Leads to either:
  - False HOLD signals (being too protective)
  - Premature SELL signals (violating rule #2)

### Example Scenario
```
Run 1: Claude recommends BUY NVDA @ $100
Run 2: NVDA drops to $95, news says earnings miss
       Claude sees the miss and wants to SELL
       But WITHOUT run history, Claude doesn't know if this is the previous run
       Result: Either protected HOLD (good) or immediate SELL (violates rule #2)
```

### Impact
**HIGH** - Claude can't reliably implement its own "no flip-flopping" rule

---

## 🔴 **CRITICAL ISSUE #2: No Portfolio History / "Last Alert" Context**
**Risk Level:** CRITICAL

### The Problem
The prompt data includes `last_alert` but the **build_prompt() function doesn't use it**.

```python
# from main.py line 56:
portfolio["last_alert"] = {
    "ticker": alert_action["ticker"],
    "action": alert_action.get("action"),
    "reasoning": alert_action.get("reasoning", ""),
    "all_actions": actions,
}

# BUT build_prompt() NEVER passes this to Claude
```

### What This Breaks
- Claude can't see what it recommended before
- Can't verify if it's flip-flopping
- Can't track thesis changes
- **Contradiction:** Rule #2 requires tracking previous runs, but no historical data provided

### Example
```
Run 1: Claude says "NVDA down 15%, thesis broken, SELL 50%"
Run 2: Claude sees NVDA is now down 20%
       WITHOUT seeing previous run data, Claude might:
       - SELL another 50% (already provided that reasoning once!)
       - Create circular/repetitive reasoning
       - Hallucinate new reasoning to justify the SELL
```

### Impact
**CRITICAL** - Violates fundamental rule #2 in the prompt itself

---

## 🔴 **CRITICAL ISSUE #3: Conflicting Requirements in Rule #2**
**Risk Level:** HIGH

### The Problem
Rule #2 is **self-contradictory and unmeasurable**:

```
"If a position was bought in the IMMEDIATELY PREVIOUS RUN ONLY, do NOT sell it 
unless something fundamentally changed. However, if more than one run has passed, 
evaluate with fresh eyes"
```

**Questions Claude must guess at:**
- What is a "fundamental change"? (not defined)
- How would Claude know it's THE previous run vs. 3 runs ago?
- Is "earnings miss 5%" fundamental? 10%? 15%?
- Is "stock down 15% in one run" fundamental? (defined elsewhere)

### Example of Hallucination Risk
```
Run 1: NVDA bought at $100
Run 2: NVDA at $99 (-1%)
       Prompt says: "don't sell unless fundamentally changed"
       
       Claude might hallucinate:
       - "Market uncertainty is fundamental" → SELL
       - "Down 1% is minor, HOLD" → HOLD
       - "The investor needs cash, that's fundamental" → SELL (no evidence!)
```

### Impact
**HIGH** - Claude will hallucinate definition of "fundamental change"

---

## 🔴 **CRITICAL ISSUE #4: Contradictory Sell Triggers (Rules #3 vs #6)**
**Risk Level:** HIGH

### The Contradiction
**Rule #3:** "High conviction bar. Only recommend BUY or SELL if you have strong, specific evidence. If the news is vague, mixed, or routine, HOLD is appropriate."

**SELL Triggers include:** 
- "Momentum loss: No positive catalyst for 2+ runs while market moves sideways or down"

### What's Wrong?
"No positive catalyst" + "market sideways" = **vague evidence** by definition!

This directly contradicts Rule #3.

### Claude's Dilemma
```
Rule #3 says: Vague evidence → HOLD
SELL Trigger says: No catalyst for 2+ runs → SELL

If NVDA has no news for 2 runs, is that HOLD or SELL?
Claude must choose. It will hallucinate which rule takes precedence.
```

### Impact
**HIGH** - Claude will make inconsistent decisions on the same stock

---

## 🔴 **CRITICAL ISSUE #5: Unrealistic 2-Month Profit-Taking Rule**
**Risk Level:** MEDIUM

### The Problem
SELL trigger: "Position up >30% in <2 months with no new bullish catalysts"

**Issues:**
- The prompt runs **4 times per day** (every 6 hours)
- In 2 months, Claude sees ~240 data points (4 runs/day × 60 days)
- Claude receives no timestamps or date information
- **How would Claude calculate "2 months"?**

### What Claude Will Do
Claude will either:
1. **Hallucinate dates** - "This must be ~2 months based on ... something"
2. **Ignore the rule** - Can't calculate without time data
3. **Overestimate duration** - Count "runs" as months (confusion)

### Example
```
Portfolio started with €100, now €135 (35% gain)
Claude sees no dates/timestamps in the input
Claude might think:
- "35% in maybe 20 days? That's fast" → SELL (wrong timing)
- "I see 150 news items, that feels like 2 months" → SELL (hallucinated)
- Completely ignore the trigger (safest option)
```

### Impact
**MEDIUM** - This trigger might never fire, or fire wrongly

---

## 🔴 **CRITICAL ISSUE #6: No Watchlist Entry/Exit Criteria**
**Risk Level:** MEDIUM-HIGH

### The Problem
The prompt allows watchlist_additions and watchlist_removals, but provides **zero criteria**:

```
"watchlist_additions": ["AMD"],  # OK, but when?
"watchlist_removals": ["INTC"]   # OK, but when?
```

**The prompt never states:**
- When to add to watchlist
- When to remove from watchlist
- What makes something "promising" for watchlist?
- Should watchlist_additions block BUY signals?

### What Claude Will Do
Claude will hallucinate watchlist logic:
```
- "This is trending, add to watchlist" (contradicts Rule #4!)
- "This stock is bad, remove watchlist" (but no criteria)
- Arbitrarily add/remove based on vibes
```

### Example Contradiction
Rule #4: "Do not BUY into a stock just because it is trending. Trending tickers are for watchlist consideration only"

SELL Triggers: "Momentum loss: No positive catalyst for 2+ runs"

**So a trending stock gets added to watchlist, then 2 runs later with no news, Claude removes it? Or sells it if held? Unclear.**

### Impact
**MEDIUM-HIGH** - Inconsistent watchlist management leads to unstable signals

---

## 🔴 **CRITICAL ISSUE #7: 40% Position Size Rule Has No Baseline**
**Risk Level:** MEDIUM**

### The Problem
Rule #5: "For BUY: never allocate more than 40% of available cash to a single position"

**Missing context:**
- Is "available cash" before or after the BUY?
- What if available cash is €5? (40% = €2, fractional share)
- What if available cash is negative (leveraged)? No data on T212 leverage limits

### Example
```
Portfolio: €100 cash
Claude wants to buy: €50 (50% of cash)
Prompt says: "max 40%"
Claude might:
- Reject the position entirely (too conservative)
- Buy €40 anyway (violates conviction - why 40 not 50?)
- Buy €50 (ignores rule)
```

### Impact
**MEDIUM** - Inconsistent position sizing

---

## 🟡 **HIGH ISSUE #8: Data Format Inconsistency**
**Risk Level:** HIGH

### The Problem
Look at the data provided to Claude (from build_prompt):

```
Holdings display:  "$118.40" (USD in holdings section)
Watchlist display: "€95.00"  (EUR in watchlist section) ❌ WRONG
Prices data fed:   "$" in calculations, "€" in display

Line 106 in build_prompt():
lines.append(f"  {ticker}: €{current} ({pct:+.1f}%)")
```

**EURO SYMBOLS ON US STOCKS! Trading 212 shows USD not EUR!**

### What Claude Sees
```
Current holdings:
  NVDA: 0.25 shares @ avg $110.00, now $118.40 (+7.6%)
    - Export controls
    
Watchlist (not held):
  AMD: €95.00 (+1.1%)  ← This looks like a EUR price!
```

### Claude's Hallucination
- "AMD is €95? That's expensive" (confusion with USD)
- "Why is AMD in euros when NVDA is in dollars?" (inconsistency)
- May make wrong trading decisions based on "cheaper" apparent price

### Impact
**HIGH** - Currency confusion leads to wrong position sizing

---

## 🟡 **HIGH ISSUE #9: No Data Validation**
**Risk Level:** MEDIUM-HIGH**

### The Problem
The prompt has **no safeguards** if data is missing or bad:

```python
current_usd = price_data.get("price", 0)  # Returns 0 if missing! ⚠️
pct_change = price_data.get("pct_change", 0)  # Same problem

# If price is 0:
pct_since_buy = ((0 - 110) / 110 * 100) = -100%  # Looks like stock crashed!
```

### What Claude Sees with Missing Data
```
NVDA: 0.25 shares @ avg $110.00, now $0.00 (-100.0%)
```

Claude will:
- **SELL immediately** - "Stock collapsed 100%!"
- Generate reasoning: "Major crash, technical breakdown"
- Ignore the fact that data is just missing

### Impact
**MEDIUM-HIGH** - Bad data triggers false SELL signals

---

## 🟡 **MEDIUM ISSUE #10: Overnight Interest Irrelevant**
**Risk Level:** LOW-MEDIUM

### The Problem
The prompt calculates overnight interest (lines 84-88) but:
- Never mentions it in decision logic
- Claude doesn't know if interest is high or low
- €0.0694% overnight seems random (is that even accurate for T212?)
- Not used in any recommendation

### What This Does
```
lines.append(f"Overnight interest charge: ${interest_charge:.4f}\n")

Result: Claude sees "$0.0694" per day
Claude: "Oh, we're paying interest... I should... do what exactly?"
```

### Impact
**LOW-MEDIUM** - Noise in the prompt that wastes tokens

---

## 🟡 **MEDIUM ISSUE #11: Ambiguous "Thesis" Concept**
**Risk Level:** MEDIUM

### The Problem
The prompt uses "thesis" repeatedly but never defines it:
- "original reason for holding no longer applies"
- "evaluate actively: if holding has deteriorated, thesis is weakened"
- "No flip-flopping" protecting thesis

**Claude must infer what a thesis is from context.**

### Example
```
Portfolio has: Apple, Microsoft, Nvidia, SPY

Which have a clear "thesis"?
- Boring holds (no thesis)
- Trendy stocks (no thesis mentioned)
- Sector bets (is "AI" a thesis? Undefined)

Claude will hallucinate theses:
- "NVDA: playing AI trend" ← Not stated in portfolio
- "MSFT: stable dividend play" ← Not stated
- "SPY: core holding" ← Guessed

Then when news comes, Claude might break imaginary theses.
```

### Impact
**MEDIUM** - Claude invents investment rationales

---

## 🟡 **MEDIUM ISSUE #12: "Recent News" Can Be Stale**
**Risk Level:** MEDIUM

### The Problem
The prompt receives news but has no timestamps:
```python
headlines = news.get(h["ticker"], [])
lines.append(f"    - {hl}")
# No dates! Is this from today? Last week? Last month?
```

### Claude's Hallucination
```
NVDA: 0.25 shares @ avg $110.00, now $118.40
  - Export controls hit Nvidia
  - Analysts cut target
  
Claude thinks: "Fresh news today!"
Actually: Could be 3 months old from NewsAPI.

Claude SELLS based on stale news while market already priced it in.
```

### Impact
**MEDIUM** - False signals on old news

---

## 🟠 **LOWER ISSUES**

### Issue #13: EUR/USD Conversion Rate Hardcoded (1.09)
- Line 82 uses hardcoded 1.09
- Real rate fluctuates
- Not business-critical but imprecise

### Issue #14: 6-8 Sentence Requirement
- "Reasoning needs 6-8 sentences"
- Claude may hallucinate sentences to hit count
- May pad reasoning with irrelevant text

### Issue #15: No Risk/Tolerance Definition
- Prompt assumes medium-term horizon
- Never defines what "medium-term" means
- 3 weeks vs 3 months vs 3 years?
- Claude may over/under-weight short-term moves

---

## SUMMARY TABLE

| Issue | Type | Risk | Impact |
|-------|------|------|--------|
| No run history | Design | CRITICAL | Can't implement Rule #2 |
| No last_alert data passed | Design | CRITICAL | Rule #2 doesn't work |
| Conflicting Rule #2 | Logic | HIGH | Hallucinated definitions |
| Rule #3 vs SELL triggers | Logic | HIGH | Inconsistent decisions |
| 2-month calc impossible | Data | MEDIUM | Trigger may never fire |
| Watchlist criteria missing | Design | MEDIUM-HIGH | Arbitrary decisions |
| Currency symbol mismatch | Data | HIGH | Wrong position sizing |
| Missing price = 0 | Logic | MEDIUM-HIGH | False crash signals |
| Interest charge irrelevant | Design | LOW-MEDIUM | Token waste |
| Thesis never defined | Design | MEDIUM | Hallucinated rationales |
| News has no dates | Data | MEDIUM | Stale news signals |

---

## 🎯 MOST DANGEROUS SCENARIOS

### Scenario 1: False Crash Signal
```
Market data missing for NVDA
Claude sees: NVDA now $0.00 (-100%)
Claude recommends: SELL ALL
Actual: Just bad API response
Reality: Portfolio liquidated incorrectly
```

### Scenario 2: Flip-Flopping Violation
```
Run 1: Claude recommends BUY NVDA €50
Run 2: Claude sees -2% drop
       Doesn't know it's the previous run
       Recommends SELL 50%
Result: Violates own Rule #2, rapid buy/sell
```

### Scenario 3: Currency Confusion Signal
```
AMD watchlist shows: €95.00 (actually $95 USD)
Claude thinks: "Expensive at €95"
       But needs $50 to buy, shows as €50
Claude: "AMD is 1.9x the price of my cash position!"
       Avoids buying (wrong decision)
```

---

## 🔧 WHAT NEEDS TO BE FIXED

1. **PASS HISTORICAL DATA**
   - Include last_alert in build_prompt()
   - Track previous run actions
   - Give Claude timestamps

2. **RESOLVE RULE CONFLICTS**
   - Define "fundamental change" with examples
   - Clarify Rule #3 vs SELL triggers precedence
   - Remove 2-month trigger or add date tracking

3. **FIX DATA ISSUES**
   - Use currency consistent (all USD)
   - Add dates to news items
   - Use None instead of 0 for missing prices
   - Validate data before sending to Claude

4. **DEFINE MISSING CONCEPTS**
   - Thesis definition with examples
   - Watchlist entry/exit criteria
   - Available cash calculation

5. **REMOVE NOISE**
   - Delete irrelevant interest calculation
   - Focus on high-signal items

