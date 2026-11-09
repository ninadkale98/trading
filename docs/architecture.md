# Market Research & Paper-Trading System: Architecture

> Status: **design agreed; Phase 0–1 built** (Nov 2026). Memory, market analysis and study of big moves added Nov 6 2026.
> Goal: a background system that keeps a living map of the US stock market, keeps inventing and
> testing investing ideas, paper-trades the ones that prove themselves on Alpaca, and reports
> where the odds look best for **multi-week to multi-month** holds (not day trading).
>
> Terms used here are explained in [`learning/`](../learning/README.md).

---

## 1. Principles

1. **Stable foundation, changing ideas.** Data, the testing bench, risk rules and the trading
   connection are fixed code. Investing ideas are plug-ins the AI can invent, write and retire freely,
   but every idea must pass the same test bench before it touches money.
2. **Plain code does the heavy lifting, AI does the judgment.** About 95% of the work (data, math,
   backtests, orders) is Python and costs nothing. Claude is used for reading, understanding,
   summarizing and inventing.
3. **Add, never overwrite.** Every fact is stored with the date it became known, so the system can
   always answer "what did we know on date X?". This keeps backtests honest and makes every change
   traceable.
4. **Nothing fails the whole system.** Every unit of work is a task in the database, with retries.
   A Claude usage limit, an API outage or a bug in one job just defers that task.
5. **Guardrails beat ideas.** Trying many ideas guarantees some look great by luck. Dated data,
   unseen test years, counting how many ideas were tried, trading costs and paper forward-tests are what
   stop the system from fooling itself.
6. **Routine is automatic, risk is escalated, real money is never automatic.** Normal paper trades on Alpaca run on
   their own; conviction bets, emerging stocks and other unusual cases wait for the user's approval (§10.8); any
   real-money order (Robinhood) needs the user's explicit approval for that specific order.

---

## 2. System overview

```
                              SCHEDULER + TASK QUEUE  (always-on Mac, restarted by the macOS service manager)
                                            │
 DATA ──────► KNOWLEDGE ──────► DAILY FEATURES ──────► STRATEGIES ──────► PLANNER ──────► ALPACA PAPER
 prices        graph +           all stocks,            (plug-ins)         exposure dial,    bracket orders,
 news          claims +          every day                  ▲               sizing, caps      stops, trailing
 filings       company maps                                 │                    ▲                │
 macro                                                      │             Opus 6 am check        │
                                                  IDEA LAB: propose → backtest → validate         │
                                                            → paper → promote / retire            │
                                                            ▲                                     ▼
                                                     LAB NOTEBOOK ◄──────────── JOURNAL (every plan, order, outcome)
                                                            │
                              REPORTS + DASHBOARD → user (daily plan, daily summary, weekly picks, monthly scorecard)
```

---

## 3. Data layer

All loaders are Python, run as scheduled tasks, are safe to rerun, and store everything in PostgreSQL
with a "known at" timestamp.

| Data | Source | Frequency | Notes |
|---|---|---|---|
| Daily price bars, all ~5,000 US stocks | **Alpaca** (`feed=sip`) | Every evening | Free plan: SIP (full-market) data is allowed if the request ends ≥15 min in the past. Use `adjustment=split` (or `all` for return studies). `feed=iex` has only one exchange's volume, so never use it for volume. |
| Minute bars (watchlist and positions only) | Alpaca | Market hours | Kept small on purpose |
| News | **Alpaca news** (Benzinga and others) | Every 15–30 min | Tested on QCOM: fast (2–5 min after releases), granular headlines per guidance item and CFO quote, **full earnings-call transcripts**, analyst target changes. Weaknesses: many quick headlines have no article body, market-wide stories are tagged with dozens of stocks (filter to ≤3 tags for stock-focused news), mostly one source, no sentiment score. |
| Financial statements, official company announcements (8-K), annual and quarterly reports | **SEC EDGAR** | When filed | Free. Requires a name and email in the request header and ≤10 requests/sec. |
| Insider trades (Form 4) | SEC EDGAR | When filed | Filed within about 2 business days |
| Big funds' holdings (13F) | SEC EDGAR | Quarterly | Up to 45 days late |
| Short interest | FINRA | Twice a month | |
| Earnings calendar + **analyst expectations** | **Finnhub** (free key, tested 2026-11-06) + EDGAR 8-K 2.02 for past dates | Daily | Free tier gives: upcoming earnings dates with EPS and revenue **estimates**, last 4 quarters of beat/miss, monthly analyst buy/hold/sell counts, peers, insider sentiment. Not free: estimate history, price targets, upgrades, supply chain, transcripts. **Saved daily, so we build our own estimate history going forward.** For past years, the earnings-day price reaction stands in for the surprise. |
| **Earnings history and estimate revisions** | **Alpha Vantage** (free key, tested 2026-11-06; 25 requests/day) | Daily | Free: quarterly expected vs actual EPS + surprise + before/after market **back to 1996** (Intel: 123 quarters), the full earnings calendar in one request (~2,000 reports with estimates), estimate revisions (average now vs 7/30/60/90 days ago, up/down counts), earnings-call transcripts. Paid only: news sentiment. Budget: 1 calendar + 24 symbols/day (holdings and candidates first, then liquid stocks). Option: one month of premium (~$50) to download all history at once before testing earnings strategies. Sources disagree on consensus (Intel Q3 2026: $0.28 here vs $0.40 Finnhub), so every estimate is stored with its source. |
| More news sources (Yahoo, Seeking Alpha, CNBC, Benzinga) | **Finnhub company news** (free) | Every evening per active stock; on demand in research | Tested: 248 AMD articles over Nov 3–6 2026 with headline + summary; free history only about 1 year back, so it's saved daily from now on |
| World events and themes (global news volume and tone by topic and country) | **GDELT** (free, no key) | Daily | Max 1 request per 5 seconds; used for theme and macro tracking (e.g. "AI chips", "tariffs", "oil supply") |
| Open web research | **Claude's own web search** inside research runs | During research | Included in the Claude plan |
| Premium AI search: news, transcripts, podcasts, web, with sentiment per passage | **Bigdata.com** (RavenPack) | **Only for high-value cases** (conviction-bet checks, unclear big moves) | Tested 2026-11-06: excellent relevance and sources, but one 10-passage search cost **22 of the 1,000 starter credits** (premium news is ~75% of the cost). Too expensive for daily use across 5,000 stocks; free sources above cover most of it. |
| Macro (rates, inflation, jobs, yields, credit spreads) | **FRED** (St. Louis Fed, free; needs a free API key) | On release | Point-in-time: store the value as first published, plus later revisions |
| **Cross-asset and global markets** | Alpaca daily bars of ETFs | Every evening | Bonds (TLT, IEF, SHY), credit (HYG, LQD), dollar (UUP), gold/silver (GLD, SLV), oil/gas (USO, UNG), commodities (DBC), bitcoin (IBIT), fear (VIXY); Europe, Japan, China, India, emerging markets (VGK, EWJ, FXI, INDA, EEM); styles (RSP equal-weight, IWM small caps, IWF/IWD growth/value, MTUM, QUAL); themes (SMH, IGV, XBI, ITA, KRE, XHB, TAN, URA, CIBR, …). Gives a whole-world view with the data we already have. |
| Deep per-stock detail: analyst ratings, Level 2 order book, politician trades, filing facts | **Robinhood MCP**, **only through Claude** | During research | A Python job can't call it directly, so it's used in the research layer. Per-call limits: fundamentals 10 symbols, analyst ratings 75, quotes 20. **Robinhood MCP has no news.** |

**Universe (decided):** **all ~5,000 US-listed common stocks** get data, daily features and tripwire checks
(cheap, and small stocks can signal through the graph), plus sector ETFs (SPY, SMH, XLE, …) as reference series.
**Liquidity tiers (decided).** Thinly traded stocks have wide bid/ask spreads and move when you trade them, so
position size follows liquidity instead of a single hard cutoff. Rule of thumb: a position should be ≤ ~1% of the
stock's average daily dollar volume (ADV), and the bid/ask spread should be small (< ~0.5%).

| Tier | Avg dollar volume/day | Trading |
|---|---|---|
| **Liquid** | ≥ $5M | Automatic, normal sizing |
| **Thin** | $1M–$5M | Automatic, reduced size (≤ 1% of ADV, half normal risk) |
| **Emerging** | < $1M (or price < $5) | **Manual approval only**, small size. This is for the case where the knowledge map shows a small company positioned to grow a lot. |

The research rotation covers every stock but prioritizes tradable ones; emerging names get researched when the
graph or news flags them.

**Survivorship rule:** backtests must include stocks that were later **delisted** (bankrupt, acquired). Testing only
today's 5,000 survivors would make every strategy look better than it really was.

**Gap checker (nightly):** finds missing days or symbols in any dataset and queues backfill tasks.

---

## 4. Database: PostgreSQL

**Why PostgreSQL:** several processes read and write at once (scheduler, workers, Claude tasks,
dashboard). DuckDB allows one writer at a time, and SQLite gets awkward with many writers. PostgreSQL handles
it, holds the graph as plain tables, stores flexible facts as JSONB, has **built-in full-text search** (the AI searches
news, journals, company maps and transcripts by keywords, dates and symbols), and **pgvector** finds similar *numeric*
situations ("past setups whose numbers look like today's"). No local language model is used (decided): all language
understanding comes from Claude on the user's plan. DuckDB can still read Postgres for very large backtest
calculations. No separate graph database is needed at about 5,000 nodes; Python loads the graph into memory
when needed.

Runs locally (Homebrew service, starts on boot), with a **nightly `pg_dump` backup**. Expected size is
10–20 GB/year (full filings are stored as extracted facts plus links, not whole documents).

### Table groups

```
MARKET DATA   stocks · daily_prices · minute_prices · news · filings · earnings · insider_trades
              fund_holdings · short_interest · macro
KNOWLEDGE     nodes (companies, sectors, themes) · edges (typed, weighted, dated) · claims (versioned)
              company_maps (versioned) · knowledge_changelog
MEMORY        market_days · theme_days · stock_timeline · journal_rollups (week / month / quarter) · predictions
ANALYSIS      features (daily, per stock) · market_snapshot (daily) · signals · big_moves · event_fingerprints (pgvector, numbers only)
LAB           ideas · experiments · backtest_results · strategies (stage + version)
TRADING       trade_plans · approvals (requests, decisions, deadlines, outcomes) · orders · positions · journal · calibration
SYSTEM        tasks · runs · events (the "Today" timeline) · ai_usage · errors
```

### Point-in-time rule
Every row carries `known_at` (when we learned it). Versioned things (claims, edges, company maps,
strategies) carry `valid_from` / `valid_to`; an update closes the old version and inserts a new one.
Backtests may only read data with `known_at` ≤ the simulated date.

---

## 5. Knowledge layer: a living economy map

### 5.1 The graph

**Nodes:** companies (~5,000), sectors and industries, ETFs, and **theme nodes** (forces, not companies):
memory prices, smartphone units, oil, interest rates, AI capex, …

**Edge types**

| Edge | Example | Typical effect |
|---|---|---|
| customer → supplier | Apple → Qualcomm, Skyworks, Cirrus Logic | Customer news moves suppliers, possibly with a delay |
| competitor | Intel ↔ AMD | Either direction: share gain vs sector panic |
| partner | Qualcomm ↔ SpaceX (5G deal) | Deal news |
| shareholder | Alphabet → Qualcomm ($548M stake) | Ownership changes |
| same sector / ETF member | QCOM ∈ SMH | Sold together when money leaves the ETF |
| theme exposure (signed) | memory prices: +MU, −QCOM, −AAPL | Shared drivers |
| statistical (moves together, beyond market and sector) | measured from prices | Hint only, never treated as cause |

Each edge stores: type, direction, **strength** (measured), sign, confidence, evidence links,
source, `first_seen`, `last_confirmed`, `valid_from`/`valid_to`.

**Edge sources (cheapest first):** price-based correlation after removing market and sector moves
(weekly, automatic) → sector/ETF membership → news co-mentions (Alpaca tags) → **annual reports**
(customers above 10% of revenue, suppliers, competitors; extracted by Claude) → 13F common ownership.

### 5.2 Claims: knowledge that updates itself

Every piece of knowledge is a **claim**:

```
Apple → customer_of → Qualcomm
  strength 0.3 (was 0.6) · confidence medium
  evidence: CFO "with Apple product revenue ramp down…" (Nov 4 2026 call);
            link after removing the market ≈ 0 since 2023 (pair study)
  first_seen 2016 · last_confirmed 2026-11-04 · source: earnings call + price study · author: Sonnet
```

**Daily update cycle:** new data → **Haiku** extracts candidate claims → **Sonnet** compares them with
existing claims for the affected companies (*confirm / update / contradict*) → changes are written as new
versions (old ones closed, never deleted) → **Opus** (9 pm) reviews the biggest changes and resolves
contradictions.

**Self-correction:** price-based edge strengths are recalculated weekly (the fading Apple → Qualcomm link
was detected this way); claims that aren't reconfirmed lose confidence over time; every change goes into
the **knowledge changelog** (visible on the dashboard).

### 5.3 Company maps

One per company, versioned in the database and exported to `knowledge/companies/<SYMBOL>.md`:
business and profit sources · key drivers · revenue and margin trend · who's buying and selling (insiders,
funds, politicians, shareholders) · graph neighbors · bull case / bear case · past earnings reactions ·
upcoming catalysts · **tripwires** · last researched.

**Tripwires** are concrete, cheap-to-check conditions written during research, e.g.
"interesting below $145 (bounced twice there in 2 years), only if guidance isn't cut and volume calms; stop
caring if smartphone outlook is cut." The daily math checks every stock's tripwires for free, so the deep
thinking happens once and gets reused every day.


### 5.4 How the graph is stored, analyzed and visualized

**Size:** about 5,000 company nodes plus a few hundred sector/theme nodes, and roughly 50,000–150,000 edges (statistical
edges are kept only above a strength threshold). That's small for any database.

| Need | How |
|---|---|
| **Storage (source of truth)** | PostgreSQL `nodes` and `edges` tables. Edges keep type, sign, strength, evidence and `valid_from`/`valid_to`, so the graph can be shown **as it was on any date**, and it joins directly with prices, news and claims. A separate graph database would mean keeping two systems in sync and losing that. |
| Everyday questions ("Apple's suppliers", "Intel's neighbors with strength > 0.2", 2-hop paths) | Plain SQL joins; recursive queries for longer paths. Fast at this size. |
| **Graph algorithms** (communities/clusters, centrality, shock propagation, shortest paths) | Python **igraph** (fast) / networkx: the whole graph loads into memory in under a second |
| Graph query language, if SQL ever feels clumsy | **Apache AGE**, a PostgreSQL extension that adds the Cypher graph query language (the one Neo4j uses) inside the same database. Optional; compatibility with our PostgreSQL version to be checked before adopting. |
| Dedicated graph database (Neo4j) | Not needed now; reconsider only if the graph grows by 100×. Could be fed from PostgreSQL as a read-only copy. |

**Visualization: the dashboard's Knowledge page (light theme)**
- **Market map:** all companies at once, clustered into communities; node size = company size, color = today's move
  (watch a shock like Intel's Oct 30 crash spread through its neighbors). Built with **Sigma.js** (fast with thousands of nodes).
- **Company view:** click a company → its neighbors 1–2 steps out; edges colored by type (customer, supplier, competitor,
  owner, theme), thicker = stronger, dashed = fading. Built with **Cytoscape.js** (rich styling for smaller views).
- **Time slider:** replay the graph as it was on any past date, to see links appear, strengthen and fade (Apple → Qualcomm weakening).
- **Shock view:** pick an event → expected effect on neighbors vs what actually happened.
- **Path finder:** "how is Apple connected to Micron?"
- Click any edge → its evidence (filing excerpt, news item, price-study numbers) and change history.
- Export to GraphML for deeper exploration in Gephi (a free desktop graph tool) if wanted.

### 5.5 Memory: a daily checkpoint at every level, searchable by the AI

The AI forgets everything between runs, so the **database is its memory**. Every day leaves a dated checkpoint at
three levels; nothing is overwritten, so "what did we know and think on date X?" always has an answer.

| Level | Saved every day | Written by |
|---|---|---|
| **Market** (`market_days`) | The numbers (§5.6 market snapshot) + a written analysis: what happened, why, where money moved, what changed in our view, open questions, predictions | Python (numbers), **Opus** (analysis, 9 pm) |
| **Theme** (`theme_days`) | Each theme's strength (AI chips, rates, oil, consumer, …): how its stocks did, news volume and tone, a short note when something changed | Python + Haiku/Sonnet |
| **Stock** (`stock_timeline`) | Dated events: big moves with their classified cause, earnings and guidance, insider clusters, analyst changes, important news (summarized), research notes, tripwire hits. Plus daily features and the versioned company map | Python + Haiku/Sonnet |

**Roll-ups, so the whole story fits in one reading.** Every Saturday Opus compresses the week into a weekly entry;
at month end, the weeks into a **monthly chapter**; at quarter end, a **quarterly chapter** ("Q3 2026: AI capex
boom broadens from GPUs to memory and power; rates fall; small caps lag"). Any day, Opus can read the last 5 days,
4 weeks, 6 months and every quarterly chapter in one go: the market's story from 2016 to today in a few pages.
Old periods get their chapters written once, from stored prices and news, in a one-time catch-up.

**Predictions log.** Every forecast is written down in a form that can be checked: what, by when, how likely
("SMH beats SPY over the next 4 weeks, 65%"). Python scores each one when its date arrives. Over time this shows
whether the AI's market calls are any good (calibration), and it keeps the story honest: you can't quietly change
your mind after the fact.

**How the AI searches it.** Claude runs headless through Claude Code, which can run commands. Each run gets a
**read-only toolkit** (a read-only database user, so it can't change anything):

```
tradebot memory market --date 2026-11-06        # that day's snapshot + analysis
tradebot memory stock AMD --since 2025-01-01    # AMD's timeline, company map versions
tradebot memory theme "AI chips"                # theme history and member stocks
tradebot search "HBM shortage" --since 2026-06 --kind news,transcript,journal
tradebot sql "SELECT ..."                       # any read-only query
   (every command takes --as-of DATE, which hides anything learned after that date)
```

**Feeding Opus "the whole market".** Giving Opus raw rows for 5,000 stocks would be ~1M+ tokens, mostly noise.
Instead, Python pre-digests everything into a **market pack** (~30–60k tokens): indexes, sectors, themes, breadth,
cross-asset and global moves, the ~150 largest companies with key numbers, every big move with its cause, leaders
and laggards, money-flow shifts, macro releases, yesterday's analysis and open predictions. Opus reads the pack,
then **digs into anything with the toolkit**. Organized tables plus the ability to look things up beat a giant
dump in both cost and quality.

### 5.6 Understanding the market: where money is flowing

Computed daily for all stocks and ETFs by Python (free), stored in `market_snapshot`, read by Opus:

| Lens | Question it answers | Measures |
|---|---|---|
| **Breadth** | Is the whole market rising, or just a few giants? | % of stocks above their 50/200-day averages, new highs vs new lows, up vs down stocks, equal-weight (RSP) vs SPY |
| **Sector and theme rotation** | Where is money moving in and out? | 1-week / 1-month / 3-month strength of each sector and theme vs SPY, and whether it's speeding up or slowing (rotation map: leading, weakening, lagging, improving); shifts in each group's share of total dollar volume |
| **Style** | What kind of stocks does the market want? | Growth vs value, small vs large, momentum, quality, defensive (utilities, staples) vs cyclical (tech, discretionary) |
| **Cross-asset** | Risk-on or risk-off? | Bond yields, dollar, oil, gold, credit spreads (HYG vs IEF), bitcoin, volatility |
| **Global** | Is this a US story or a world story? | Europe, Japan, China, India, emerging markets |
| **Leaders** | Who is the market rewarding? | New 52-week highs by theme, strongest stocks within the strongest groups |
| **Macro** | What is the economy doing? | Rates, inflation, jobs, yield curve (FRED), with release-day surprises |

From these, a **market regime** label (e.g. "risk-on, led by AI hardware, narrow breadth") feeds the exposure dial
(§10.3), the briefing, and the market journal (§5.5).

**Stories vs prices (why the system waits for confirmation).** A macro story can be right while the trade is wrong.
In 2026 "AI needs chips" was true for both AMD (+101% Jan 2 → Nov 6) and NVDA (−1%), and SMH rose +24%. The story
didn't say *which* stock or *when*, and obvious stories are often already in the price. So the AI's role is to
**know the story** (themes in the graph), and the system **acts when the story shows up in the numbers**: revenue
speeding up, guidance raised, estimates rising, the stock starting to beat its sector, volume building.

---

## 6. Coverage: every stock, every day, without researching every stock every day

| Layer | Refresh | Cost |
|---|---|---|
| Prices, volume, features, setups, tripwire checks | **Daily, all stocks** | Free (Python) |
| Fundamentals | After each earnings report | Cheap |
| News headlines | Every 15–30 min, all stocks (multi-symbol requests) | Cheap; Haiku triage |
| Insider trades, fund holdings, short interest | When filed | Cheap |
| **Deep research (company map)** | **On rotation plus right away on events** | AI, so this is what we spread out |

### Research priority queue (recomputed nightly)

```
priority = staleness (days since last deep look)
         + event bonus   (earnings just reported, big drop or gap, volume spike, major news, 8-K, insider cluster)
         + graph bonus   (a strongly connected neighbor just had a big event)
         + setup bonus   (a pattern is forming / tripwire close)
         + holding bonus (we own it)
```

A quiet stock gets a deep look about monthly. A stock that just crashed on earnings goes to the front
**the same evening**. The first full sweep of all stocks runs at a higher daily budget, then the system
switches to keeping maps up to date.

### Stock lifecycle (tracked across days)

```
Not researched → Monitoring → Watching (a tripwire is close) → Candidate (tripwire hit)
   → Confirming (daily: is the selling slowing? is it holding a level? is volume calming?)
   → Trade plan → Position → Exit → Review
```

Good entries usually develop over several days. The "Confirming" stage is what avoids catching
falling knives (Intel kept falling about 20% after its first −28.6% day).

### Classifying every big move
For each large drop or jump, the cause is labeled automatically:
**market-wide** (SPY fell too) · **sector-wide** (sector ETF fell about as much) · **neighbor-driven** (a graph
neighbor had news) · **company-specific** (much worse than its sector, with its own news).
Example: QCOM −11.1% on Oct 30 2026 was sector-driven (Intel's crash, SMH −7%); QCOM −9.5% on
Nov 5 was company-specific (weak guidance, handsets −26%, Apple ramp-down) made worse by a sector-wide selloff.

---

## 7. Daily features (all stocks, Python)

Trend (price vs 20/50/200-day averages, slopes) · momentum (RSI, returns over 1/5/20/60 days) ·
volatility (ATR) · volume (relative volume, accumulation/distribution, OBV) · distance from 52-week
high/low · gap size · earnings surprise and guidance change · revenue and margin growth · valuation ·
insider net buying · analyst revisions · news sentiment and volume · sector and market relative strength ·
**graph features** (shocks to strongly connected neighbors, theme moves) · days to next earnings.

All point-in-time. Strategies read features; they never fetch data themselves.

---

## 8. Strategies: ideas as plug-ins

Each strategy is one Python file with the same interface:

```python
class Strategy:
    name: str
    version: str
    def candidates(self, date, features, knowledge) -> list[Candidate]:
        # Candidate = symbol, entry, stop, targets, horizon_days, p_win, avg_win, avg_loss, rationale
```

```
strategies/
  promoted/      proven; trades with a real risk budget
  paper/         passed backtests; proving itself live with a small budget
  experimental/  the AI writes new ideas here (cannot touch core/)
  retired/       stopped working; kept so the AI doesn't retry them
```

**Starting set**
1. **Quality pullback in an uptrend:** the existing Robinhood scan ([learning/08](../learning/08-our-scan-explained.md)).
2. **Earnings overreaction:** drop much larger than the stock's usual earnings move, guidance not cut,
   selling slowing down. Must separate the QCOM-type rebound from the Intel-type drift (research finds
   bad earnings are often followed by **further drift down**).
3. **Return to the average:** far below its normal range, with a history of recovering from similar drops.
4. **Accumulation:** up days on high volume, down days on low volume.
5. **Relative strength / sector rotation.**
6. **Supplier lag (graph):** customer-specific shock → suppliers' next-day move, **tested pooled across all
   customer→supplier pairs** (see §15 findings).

---

## 9. Idea lab: the self-improving loop

```
propose → backtest (2016–2022) → validate on unseen years (2023–2024) → paper trade 4–8 weeks → promote / retire
                                                     (2025–2026 kept as a final holdout, used once at promotion)
```

| Gate | Requirement |
|---|---|
| Backtest | ≥ ~100 trades; beats SPY after trading costs; t-stat > 2; works in more than one market period |
| Validation | Still works on unseen years; **penalized for how many ideas have been tried** (more attempts mean more lucky flukes); beats a random-entry version of itself |
| Paper | Live results roughly match the backtest (win rate, average win/loss, calibration) |
| Ongoing | Performance-decay monitor: shrink its risk budget, then retire if it stops working |

**Idea sources:** the user · Opus reading the lab notebook · patterns found in the data · known research effects
(post-earnings drift, momentum, insider buying, customer→supplier lag).

**Study of big moves ("what came before the winners").** Every week Python finds every stock that rose ≥ 20% within
~3 months or ≥ 50% within ~6 months since 2016 (and the mirror image: big losers). For each one it records what
was **knowable before the move began**: features, revenue and margin trend, earnings surprises and guidance, insider
buying, sector and theme strength, breadth, news volume and tone, graph neighbors. Then it compares them with
**look-alikes that didn't move** (same date, same sector, similar setup). Without that comparison every pattern looks
great. The output is base rates ("of stocks with X, Y, Z, 18% rose 20%+ in 3 months vs 6% normally") that become
strategy ideas for the gates above. Sonnet writes short case studies of big recent winners for learning, labeled as
hindsight. Going forward, stocks that match a winner profile each day go on a watch list, and their outcomes are
recorded: an honest live test.

**AI judgment can't be backtested honestly.** Claude already knows what happened up to its training date (AMD went up),
so asking it "would you have picked AMD in 2025?" is look-ahead bias, even if nobody intends it. Rules: **number-based
patterns** are tested on history; **AI story-based calls** (theme bets, company-map verdicts, Opus predictions) are
tested **only going forward**, in the predictions log and paper trading. Haiku labels on **old** headlines (backfilled 2019+) may carry hindsight, so news-based backtests count as weak evidence until confirmed forward; a word-list tone score is the hindsight-free version for history.

**Lab notebook:** every experiment logs hypothesis, code version, parameters, data period, results,
verdict and lesson. Opus reads it before proposing the next round, so failures teach the system and are
never repeated blindly.

**Safety boundary:** the AI may write files in `strategies/experimental/` and lab records. It can't edit
`core/` (data, backtester, risk, execution) or rewrite history. Promotion to real money is never
automatic.

### 9.1 The self-improving loop as built (2026-11-08)

Two levels, each feeding the other. The AI proposes and builds; **fixed code** decides.

```
        ┌──────────────────────────── Level 1: strategy lab (automatic, Sun 12:00 + Wed 23:00 ET) ───────────────────────────┐
        │ Opus PROPOSES ideas  →  Sonnet BUILDS a strategy file  →  sandbox validator  →  SMOKE (own process: runs, fast,      │
        │ (reads notebook,        (lab/candidates/)                  (imports, no file/   no look-ahead)  →  TEST (own process:   │
        │  all results, research,                                    network, no t+1)    look-ahead, signal study, 2016–2022     │
        │  feature catalog)                                                              backtest + gates)  →  DECIDE (fixed     │
        │      ▲                                                                         rules)  →  live experimental / paper /  │
        │      │                                                                         retired  →  Opus REPORT → notebook      │
        │      │ lessons, results                                         feature requests → lab/requests.md                    │
        └──────┼───────────────────────────────────────────────────────────────────────────────┬──────────────────────────────┘
               │                                                                               ▼
        live dry-run/paper trades → trade journal → Saturday trade review → lessons   ┌── Level 2: engineer (weekly, Sat 12:30) ──┐
                                                                                       │ Claude Code on its own git branch builds │
                                                                                       │ one system improvement (usually a        │
                                                                                       │ requested feature/data source); fixed    │
                                                                                       │ checks; WAITS FOR REVIEW → merge → the   │
                                                                                       │ lab can use the new features next round  │
                                                                                       └──────────────────────────────────────────┘
```

**Decision rules (fixed in `core/jobs/lab.py`, written before any AI idea was tested):**

| Decision | Rule |
|---|---|
| Reject | build/test error, look-ahead found, or < 30 signals in 2016–2022 |
| Admit to live (experimental, 0.5% risk per trade) | "sign of life" in train: signal-study excess vs the eligible pool > 0 with overlap-adjusted t > 0.5 at 20 or 60 days, or backtest excess per trade > 0 with t > 1. **A low bar on purpose** (user's choice: many live experiments on paper money; live results decide) |
| Promote to `paper/` | passed the strict train gates AND the unseen 2023–2024 years |
| Retire (decay) | live ≥ 15 closed trades with average excess vs SPY < 0 and t < −1.5 |
| Retire (cap) | more than 16 live strategies → the one with the weakest evidence (live t-stat after 10 closed trades, else the train t-stat); strategies admitted in the last ~4 weeks are protected |

**Measurement fixes after round 1** (Opus's round report criticized the lab's own tools; all four fixed the same day):
the signal study uses the strategy's top 10% when it flags ≥ 90% of the pool (otherwise signal = pool, "could not
measure"); the overlap-adjusted t is Hansen–Hodrick by calendar distance (simulated no-edge sd ≈ 1.05–1.1 for dense
and rare signals, instead of a fixed t/√h); a backtest only counts as a sign of life if it stays positive without its
best year; "works most years" needs ≥ 4 years with ≥ 10 trades; the multiple-testing count is distinct strategy
versions, so re-tests after a tool fix aren't new tries (`lab.baseline` re-tests all live strategies).

**Guards against fooling ourselves:** the sandbox validator (no imports beyond numpy/math/strategy helpers, no
files/network/dunder/`while`, no index past day t), the runtime look-ahead check (a strategy's day-t answer must not
change when later days are removed; the same check for features), AI code runs only in a separate process until it
passes, every test counts toward the multiple-testing bar, and the gates, checks and money code are protected from
both AI levels. The planner isolates each strategy, so a broken one can't stop the daily plan.

**The engineer never merges by itself** (decided 2026-11-08). Its branch is checked automatically (protected paths
untouched, nothing deleted, no migration edited, all tests pass, every live strategy passes the smoke check, feature
look-ahead check if features changed) and then waits: the user says "merge engineer #N" or "reject engineer #N" in
chat (`tradebot engineer-merge N` / `engineer-reject N`). It runs headless with no MCP servers (no broker access),
edits only its worktree outside the repo, can't push, and explores the database through a read-only login
(`tradebot_ro`).

---

## 10. Planner & portfolio

### 10.1 Expected value, not just win rate
Profit depends on **win rate and size of wins vs losses**:

| Win rate | Avg win | Avg loss | Per trade |
|---|---|---|---|
| 75% | +2% | −8% | **−0.5%** (loses) |
| 75% | +4% | −4% | +2.0% |
| 45% | +10% | −4% | +2.3% |

Candidates are ranked by **expected value per unit of risk, after costs**.

### 10.2 Calibration
Each strategy's stated odds are checked against reality (calibration chart on the dashboard).
If it says 75% but wins 55%, its probabilities are corrected and its bet sizes shrink automatically.

### 10.3 Market exposure dial

| Market condition | Invested |
|---|---|
| Healthy uptrend (S&P 500 above its 200-day average, broad participation) | up to 90–100% |
| Mixed | ~50% |
| Falling or panicking | 20–30%, mostly cash |

**Market sleeve (decided: yes):** when the market is healthy but there aren't enough good picks, unused money
sits in SPY instead of cash, so the account rides broad rallies. When good picks appear, SPY is sold to fund
them; when the dial turns down, SPY is cut first. Picks are always scored separately against SPY.

### 10.4 Entry filter (all required)
Calibrated chance of success ≥ threshold (start ~60%, raise as the system proves itself) · reward/risk ≥ 1.5–2 ·
positive expected value after costs · no earnings within 10 trading days (unless the strategy is about earnings) ·
sized to its liquidity tier (§3; emerging names need manual approval).

### 10.5 Sizing and limits: two tiers

**Tier 1: hard limits.** Fixed code in a config file; no AI, prompt, agent or approval button can change them.
Only the user can change them, deliberately, by editing the config:
- Max loss per trade **2%** of the account (stop-loss distance × shares).
- ≤ **15%** of the account in one stock · ≤ **30%** per theme cluster from the graph (e.g. "Apple-dependent";
  ten chip-stock bets are one bet) · ≤ 25% per sector · ≤ 40% per strategy until proven.
- Every position has a stop-loss. No margin, no options, no shorting.
- **Circuit breaker:** account down 10% from its peak → no new trades until the **user approves resuming**.

Why hard limits exist even with a good AI: AI conviction isn't calibrated probability; overnight gaps (Intel −28.6%)
aren't predictable from analysis; a critic from the same model family shares blind spots; news text is untrusted
(misleading or planted stories could drive a big bet); and growing bets after wins without a ceiling leads to
overconfidence blow-ups.

**Tier 2: AI discretion, earned with evidence.** Inside Tier 1:
- Normal trades risk **0.5–1%** of the account, scaled by the strategy's calibrated record (a fraction of the Kelly bet size).
- **Conviction bets** may risk up to **2%**, only through a debate:

```
PROPOSER (Opus)  → case for an above-normal bet: why special, expected gain, odds, what would prove it wrong
SKEPTIC (Sonnet, instructed to be pessimistic, given different data: similar past cases that failed,
         upcoming earnings, theme exposure, what's already priced in, base rates, worst realistic scenario)
         → tries to find the reason it fails
CHECK    → continues only if the skeptic finds no serious flaw AND the strategy's track record supports the odds
USER     → goes to the user's approval queue with both arguments side by side; the user approves, trims or rejects
```

- Conviction bets are tracked as **their own record**. If they beat normal-sized trades over time, the allowed
  maximum grows (never past Tier 1); if they underperform, it shrinks automatically.

### 10.6 Exits

| Exit | Rule |
|---|---|
| Stop-loss | Set before entry, below support or ATR-based, **never moved lower** |
| Take partial profit | Sell half at target 1 |
| Let winners run | Remaining half follows a rising **trailing stop** |
| Time stop | Exit if nothing has happened after N days |
| Thesis broken | A "stop caring" tripwire fires (e.g. guidance cut) |
| Earnings | Exit before the report unless the strategy is designed to hold through it |

### 10.7 Flow

```
4:30 pm strategies → candidates (odds, avg win/loss, theme cluster)
   → PLANNER: rank by EV/risk → apply exposure dial and limits → size → tomorrow's plan
   → 6:00 am Opus check (may trim or cancel, never enlarge)
   → normal trades: orders at the open (Alpaca bracket orders)
     escalated trades (§10.8): wait in the approval queue → placed only after the user approves
   → stops and trailing stops managed all day → journal → 9 pm calibration update
```

### 10.8 Human in the loop: what needs the user's approval

The system handles routine, rule-following work alone and **escalates anything unusual or high-risk** to the user.

| Automatic (no approval) | **Needs the user's approval** |
|---|---|
| Normal-size trades (0.5–1% risk) in liquid and thin stocks that pass every rule | **Conviction bets** (above-normal size), after the proposer/skeptic debate |
| Stop-losses, partial profits, trailing stops, time stops, thesis-broken exits | **Emerging stocks** (below the liquidity tiers), for example a small company the map says is positioned to grow a lot |
| Market sleeve (SPY) adjustments within the exposure dial | **Disagreements:** the proposer still wants a trade the skeptic objected to; the user breaks the tie |
| Research, knowledge updates, backtests, strategy experiments | **Holding through earnings** when the strategy isn't designed for it |
| | **First live trades of a newly promoted strategy** |
| | **Resuming after the circuit breaker** |
| | **Anything involving real money (Robinhood)**, always |

**Approval rules**
- Each request shows the case **for** (proposer), the case **against** (skeptic), the size, the worst realistic
  loss, the theme exposure, and a chart link.
- The user decides **approve / trim / reject** on the dashboard's Review page, or by telling Claude in chat
  (e.g. "approve #3, half size"); the decision is recorded with any comment.
- Every request has a **deadline** (e.g. before the open for that day's trades). **If there's no answer by the deadline,
  the safe default applies: no trade** (or, for exits, the exit happens).
- Approved and rejected escalations are tracked, so the user can later see whether their overrides helped.

---

## 11. Execution

- **Alpaca paper account** ($100,000 practice balance, kept as is), fully automatic, inside the risk rules.
- Orders: limit entries as **bracket orders** (entry + stop-loss + take-profit together); trailing stops for runners.
- Paper fills are optimistic, so the journal subtracts an estimated cost for slippage and spread.
- **Real money (Robinhood MCP account): never automatic.** The system can recommend; each order needs the
  user's explicit approval in chat.

---

## 12. AI models and budget

| Model | Jobs | When |
|---|---|---|
| **Haiku** | Headline triage in batches of ~50 (relevant? positive or negative? which company?), extracting facts from filings, simple labeling | All day |
| **Sonnet** | Company research and company maps, reconciling claims, reading full articles and earnings-call transcripts, writing strategy code | 5:30–8 pm research queue |
| **Opus** | **6 am morning plan**; **9 pm daily summary and new ideas**; conviction-bet proposals; weekly lab review; monthly scorecard | Daily ×2, weekly, monthly |
| **Sonnet (skeptic role)** | Pessimistic review of every conviction bet, using bear-side data (§10.5) | When a conviction bet is proposed |

- Runs headless through Claude Code (`claude -p`, model chosen per task) on the user's **$100 Claude Max plan**.
  No local model (decided): the goal is to get the most out of the plan. Plan limits are per 5-hour window and per
  week, so a **budget scheduler** spreads work across windows: scheduled jobs (Opus plan/summary, earnings-day research)
  get reserved room, and **unused capacity in each window is filled** with lower-priority work (research rotation,
  catch-up chapters, case studies) instead of going to waste. Overflow option: pay-per-use API (Haiku is cheap).
- **No daily caps (user decision, 2026-11-08).** Background jobs use the plan freely; the plan's own 5-hour and
  weekly limits are the only limit. When Claude reports a usage limit, that model's queue pauses until the reset
  time (ResourceLimited) and resumes by itself. Usage is still metered per call in `ai_usage`. Optional per-model
  daily caps remain available in `settings.yaml → ai.daily_budget_usd_equiv` if the user ever wants them back.
- Every Claude output is checked against a schema before it's written to the database.
- Optional fallback: if Opus is still blocked hours later, Sonnet writes the daily summary, labeled as such.

---

## 13. Daily schedule (ET)

| Time | Job |
|---|---|
| **6:00 am** | **Opus morning plan:** overnight news, queued plans, market conditions, today's earnings → confirm / trim / cancel plans; today's watch list |
| **6:30 am** | **Daily briefing updated** with the morning plan and any new approval requests |
| 6:00–9:30 am | Overnight news loaded and triaged, pre-market gaps |
| **9:15 am** | **Approval deadline** for today's trades; unanswered requests default to "no trade" |
| 9:30 am – 4:00 pm | Every 15–30 min: news, watchlist prices, tripwires, order and stop management |
| 4:30 pm | Daily bars for all stocks → features → **market snapshot** (breadth, rotation, cross-asset) → strategies → planner → tomorrow's plan |
| 5:30–8:00 pm | **Sonnet research queue**, knowledge-map updates |
| **9:00 pm** | **Opus daily summary, daily market analysis and new ideas** → market journal, reports, predictions log, lab queue |
| **9:30 pm** | **Daily briefing published** (10–15 min read) with approval requests for tomorrow; review it in the evening or by 9:15 am |
| Overnight | Backtests of new ideas, gap checker, database backup |
| Saturday | Opus weekly review: promote, retire, new idea round; weekly picks report; **weekly money-flow map** and journal roll-up; **study of big moves** refreshed |
| **Saturday 10:00 / 12:30** | Opus trade review → lab notebook · **engineer** builds one system improvement on a branch (waits for review) |
| **Sunday 12:00, Wednesday 23:00** | **Idea-lab round:** propose → build → test → admit/retire → report (§9.1) |
| Month end | Monthly scorecard |

---

## 14. Reliability: failures never crash the system

Every unit of work is a row in `tasks`:

```
tasks: id · type · input · priority · status · attempts · last_error · next_try_at · expires_at · created · finished
status: pending → running → done
                         ↘ deferred  (limit hit; retry after reset)
                         ↘ failed    (gave up after N tries; shown on the dashboard)
```

| Failure | Handling |
|---|---|
| Claude usage limit (any model) | Task **deferred**; that model's queue pauses until the limit resets; everything else keeps running; backlog runs by priority after the reset |
| Network / temporary server error | Retry, waiting longer each time (1, 5, 15 min, …) |
| Badly formatted AI output | One retry with stricter instructions, then flagged for review; nothing invalid is written |
| Data API outage | Retried later; nightly gap checker backfills anything missing |
| Program crash | The macOS service manager restarts it; jobs are isolated, so one failure can't stop the scheduler |

Tasks are **safe to rerun** (no duplicates) and long jobs save progress as they go. Stale tasks expire
instead of piling up. Every run, error and AI call is logged (`runs`, `errors`, `ai_usage`).

---

## 15. Findings so far (evidence that shaped this design)

- **Intel, Oct 29–30 2026:** beat on EPS but guided Q4 far below expectations; −28.6% in one day (worst since
  1974), about 5× normal volume, ~−45% over a week. Lesson: guidance beats results; overnight gaps defeat stop-losses
  → earnings blackout rule; falling knife → "Confirming" stage.
- **Qualcomm:** Oct 30 −11.1% was **sector-driven** (no company news; Intel contagion). Nov 5 −9.5% was
  **company-specific** (weak GAAP guidance, handsets −26%, Apple ramp-down) plus a sector-wide selloff → classify every move.
- **Apple → supplier pair studies (2016–2026, daily, Alpaca SIP):**

| | QCOM | SWKS | CRUS |
|---|---|---|---|
| Correlation with Apple, raw | 0.51 | 0.59 | 0.51 |
| After removing the market / chip sector | 0.09 / 0.14 | 0.22 / 0.30 | 0.17 / 0.23 |
| Recent years | faded to ~0 | still ~0.14–0.23 | still ~0.16–0.18 |
| Same day on Apple-only drops (excess, t-stat) | −1.1% (−3.3) | −1.2% (−4.0) | −1.2% (−3.0) |
| Next day (excess, t-stat) | +0.03% (0.1) | −0.41% (−1.2) | −0.42% (−1.5) |

  Lessons: raw "moves together" is mostly the market → always measure against market and sector. Link strength matches
  real dependence and **changes over time**. Same-day links explain moves; only next-day links can be traded. One pair
  (n≈55 events) is too small → test pooled across all customer→supplier pairs.

---

## 16. Dashboard

Local web app on the always-on Mac (FastAPI + a simple live-updating page), reading the same PostgreSQL.
Opened at `localhost:8090` (VS Code port forwarding) or, from any device on the user's Tailscale network, at **http://ichigo:8090** (the server listens only on localhost and ichigo's private Tailscale address, never on the local Wi-Fi).

**Theme:** light and clean: white and soft-gray backgrounds, dark readable text, green and red only for gains and losses,
large text, single-column layout on phones.

| Page | Shows |
|---|---|
| **Review** (home page) | **Today's briefing** (§17) and the **approval queue**: each request with the case for, the case against, size, worst-case loss, chart; approve / trim / reject buttons plus a comment box; history of past decisions and how they turned out |
| **Live** | Running jobs, queue, next scheduled runs, AI budget used today; pause / resume / run now / retry |
| **Today** | Timeline of everything done today ("4:31 pm prices for 1,512 stocks · 6:10 pm researched 32 companies · 9:05 pm Opus summary") |
| **Market** | Today's market analysis; breadth; sector and theme rotation map; cross-asset and global; exposure dial and regime; tripwire hits; big moves with their classified cause; market journal timeline (day → week → month → quarter); predictions and their score |
| **Portfolio** | Paper positions, P&L **vs SPY**, open orders, stops and trailing stops |
| **Idea lab** | Strategies by stage with test results, calibration charts, lab notebook |
| **Knowledge** | Graph explorer, company maps, **knowledge changelog** |
| **Reports** | 6 am plan, 9 pm summary, weekly picks, monthly scorecard |
| **Charts** | Interactive charts (same engine as Stock View) with entry, stop and target lines |
| **Health** | Failed and deferred tasks with reasons and retry times, data gaps, last successful run per job |
| **Data** | What the system holds: stocks covered, history depth per dataset, liquidity tiers, sectors |

The VS Code **Stock View** extension (`stock-view/`) stays for chart work in the editor.

---

## 17. Reports

### Daily briefing: the user's 10–15 minute read
Published at 9:30 pm (updated at 6:30 am) on the dashboard's Review page and saved to `reports/daily/YYYY-MM-DD.md`.
Light theme, readable on a phone, written in plain language, with every term linked to `learning/`.

| Section | Read time | Content |
|---|---|---|
| 1. The day in 5 lines | 1 min | Market mood and exposure dial, account vs SPY, what the system did, anything that needs attention |
| 2. **Decisions needed** | 3–5 min | Approval requests with the case for and against, size, worst-case loss, deadline |
| 3. Top findings | 3–4 min | 3–5 most interesting discoveries: big moves and their cause, new graph connections, tripwire hits, surprising news, each with a chart |
| 4. Portfolio | 2 min | Positions, today's changes, stops hit, profit and loss vs SPY |
| 5. What the system learned | 1–2 min | Knowledge changes, lab results, ideas tested or retired |
| 6. Tomorrow | 1 min | Planned trades, earnings to watch, events |

The user can reply in chat with questions or decisions ("why #2?", "approve #3, half size", "research XYZ deeper"),
and Claude records the decision in the approval queue.

### Daily market analysis: for learning (optional, ~10–15 min)
Written by Opus at 9 pm from the market pack, saved to `reports/market/YYYY-MM-DD.md` and the market journal,
linked from the briefing. Plain language, with terms linked to `learning/`.

1. **What happened:** indexes, breadth, the biggest moves, and **why** (with evidence: news, earnings, macro releases)
2. **Where money moved:** sectors, themes and styles gaining or losing, cross-asset and global picture
3. **The story so far:** how today fits the week's and month's story; what changed in our view
4. **What to watch:** upcoming earnings, macro releases, tripwires close to firing
5. **Predictions:** new ones with odds, and old ones scored
6. **Lesson of the day:** one concept explained with today's example

### Other reports
- **Weekly money-flow map (Saturday):** rotation map, theme leaderboard, the 4-week story, what changed, prediction scorecard.
- **6 am plan:** market conditions, today's plans (confirmed / trimmed / cancelled and why), watch list, earnings today.
- **9 pm summary:** what moved and why, knowledge changes, positions, lab results, new ideas queued.
- **Weekly picks:** top ideas with setup, evidence, historical odds, expected move, risk, theme exposure; vs SPY.
- **Monthly scorecard:** per-strategy results, calibration, what the lab tried and learned.

---

## 18. Evaluation: what 1–2 months of paper trading can show

About 40 trading days, roughly 30–60 finished trades. Enough to verify the system works end to end, that stated odds
roughly match reality, and how it compares with SPY. **Not** enough to prove a lasting edge (a 70% measured win rate
over 40 trades could really be about 55–85%). Judge on many trades across strategies, after estimated costs, always against SPY.

---

## 19. Folder structure

```
trading/
  core/            ingest/ · features/ · backtest/ · planner/ · risk/ · execution/ · tasks/   ← AI can't edit
  strategies/      promoted/ · paper/ · experimental/ · retired/                              ← AI writes here
  knowledge/       companies/<SYMBOL>.md (exported company maps)
  lab/             notebook.md · experiments/
  reports/         daily/ · market/ · weekly/ · monthly/
  dashboard/       FastAPI app + light-theme web page
  docs/            architecture.md (this file)
  learning/        beginner guides to every term
  stock-view/      VS Code chart extension
  charts/          .stock files
  .claude/skills/  research-company · morning-plan · daily-summary · propose-ideas · write-strategy · weekly-review
  .env             API keys (never committed or printed)
```

---

## 20. Build phases

The detailed, step-by-step checklist with progress tracking is in **[build-plan.md](build-plan.md)**.

**Order changed 2026-11-07:** understanding first (news and sentiment, memory and daily market analysis, economy map, a lab for all kinds of strategies), then paper-trading execution. See the re-plan table in build-plan.md.

| Phase | Build | Result |
|---|---|---|
| 1 | PostgreSQL, task queue and scheduler, data loaders (Alpaca prices and news, EDGAR), point-in-time storage, backtester | Can test any idea honestly; data stays up to date |
| 2 | Daily features, **market snapshot (breadth, rotation, cross-asset, macro)**, first strategies, planner and risk rules, Alpaca paper execution, journal, **basic dashboard (Review with daily briefing and approval queue, Live, Today, Portfolio, Health)** | The system paper-trades on its own |
| 3 | Knowledge layer: graph, claims, company maps, research queue (Haiku/Sonnet), **memory (market/theme/stock journals, roll-ups, predictions) + AI search toolkit**, Opus 6 am / 9 pm with **daily market analysis**, study of big moves v1 | It understands companies, connections and the market's story |
| 4 | Idea lab automation (Opus proposes, Sonnet writes strategies, stage gates), full dashboard | It improves itself |
| 5 | Run 1–2+ months; weekly and monthly reviews | Evidence, or lessons |

---

## 21. Decisions

| Decision | Status |
|---|---|
| Paper balance | **Decided:** keep the Alpaca paper balance as is ($100,000) |
| Universe | **Decided:** all ~5,000 US stocks for data, features and research; trade only the liquid subset |
| Where it runs | **Decided:** this Mac, "ichigo", always on |
| AI vs risk rules | **Decided:** two tiers: fixed hard limits + earned AI discretion via proposer/skeptic debate (§10.5) |
| Market sleeve (unused money in SPY when the market is healthy) | **Decided: yes** |
| Liquidity | **Decided:** tiers instead of a $10M cutoff: liquid ≥ $5M/day automatic, thin $1–5M automatic at reduced size, emerging < $1M only with manual approval (§3) |
| Human in the loop | **Decided:** daily 10–15 min briefing; conviction bets go proposer → skeptic → **user approval**; escalation list and safe defaults in §10.8 |
| Local language model (SLM) | **Decided: no.** All language work uses Claude on the $100 Max plan, using spare capacity in each window. Text search uses PostgreSQL full-text search; pgvector is kept for numeric similarity only |
| Market understanding | **Decided:** daily market snapshot (breadth, rotation, style, cross-asset, global, macro), Opus daily market analysis for learning, weekly money-flow map (§5.6, §17) |
| Memory | **Decided:** daily checkpoints at market, theme and stock level, weekly/monthly/quarterly roll-ups, predictions log, read-only search toolkit for the AI (§5.5) |
| Study of big moves | **Decided:** what came before big winners and losers vs look-alikes that didn't move (§9) |
| Daily AI budget numbers (research companies/day, Haiku batch frequency) | **Decided (2026-11-08):** no daily caps; the Max plan's own limits are the only limit (§12) |
| Self-improvement | **Decided (2026-11-08):** two-level loop (§9.1). Strategy lab fully automatic with a low admission bar (paper money, learning first); the system-level engineer builds on a branch and **never merges without the user's OK** |
| Minimum position size | **Decided:** none; tiny trades are fine while learning |
| Data purchases | **Decided (2026-11-08):** none for now; history fills slowly with free sources (Alpha Vantage 25/day, Finnhub; Bigdata key kept for rare special cases). Paid data only after a strategy has a proven thesis and profit, funded from that profit (user: "earn a profit first, then reinvest"). Correctness over speed |
| Direction of research | **Decided (2026-11-08):** non-price evidence first, earnings above all: same-evening release reading, post-earnings drift, pre-earnings predictions scored forward (build plan 4.1) |
| Who runs the roadmap | **Decided (2026-11-08):** Claude, through a daily check-in session (build plan 4.2); the user gives ideas, Claude executes and documents |
