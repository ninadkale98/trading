# Build Plan (living checklist)

> Companion to [architecture.md](architecture.md), which says **what** we're building; this file says **in what order**,
> **how we know each step is done**, and **where we are**. Update the checkboxes and the build log as work happens.
>
> **Resuming in a new session:** read `CLAUDE.md` → `docs/architecture.md` → this file's **Status** table and
> **Build log** → continue with the first unchecked item of the current phase.

## Status

| Phase | Goal | Status | Started | Finished |
|---|---|---|---|---|
| 0 | Prerequisites (disk space, PostgreSQL, settings) | ✅ Done | 2026-11-06 | 2026-11-06 |
| 1 | Foundation: database, task system, data loaders, backtester | 🟡 Code done; historical backfills running | 2026-11-06 | |
| 2 | Paper-trading MVP: features, strategies, planner, Alpaca execution, approvals, briefing, basic dashboard | 🟡 Dashboard, features, market snapshot, earnings + macro data done; strategies next | 2026-11-06 | |
| 3 | Knowledge layer and AI agents: graph, claims, company maps, research queue, memory + AI search, Opus plan, summary and daily market analysis, study of big moves | ⬜ Not started | | |
| 4 | Idea lab: self-improving loop, conviction-bet debate, stage gates | ⬜ Not started | | |
| 5 | Operate 1–2+ months, review, tune | ⬜ Not started | | |

**Re-plan (2026-11-07, user's direction):** the goal for the next few months is **understanding the market** and a system
that can try many kinds of strategies, not rushing price-only rules into paper trading. First train results showed
price-only rules have little edge (only momentum predicts, ~+1.5% vs other stocks over 3 months). So the order is now:

| Step | What | From |
|---|---|---|
| **A** ✅ | Claude runner + **news understanding**: Haiku reads every headline (company, event type, direction, importance); daily per-stock news sentiment and event log. Built 2026-11-07: `core/ai/claude.py`, `news.triage` every 30 min (+ hourly backlog), `news_events`, news features | Phase 3.1–3.2 |
| **B** | **Memory + daily market analysis**: market/theme/stock journals, Opus 9 pm analysis for learning, predictions log (scored automatically) | Phase 3.6b |
| **C** | **Economy map**: themes (AI capex, rates, oil, consumer…), company links (customers/suppliers from 10-Ks), theme strength over time | Phase 3.3–3.4 |
| **D** | **Strategy lab, all kinds**, in the order the research suggests (learning/12): insider cluster buying · earnings surprise + momentum + 52-week high · weekly news tone (word list on 2019–25; Haiku forward) · quality filter · Claude reading earnings calls/guidance (forward) · analyst revisions (once snapshots accumulate) · supplier links (with C). Macro = risk dial, not picker | Phase 2.2 + 4 |
| **E** | Planner + Alpaca paper execution + approvals, trading whatever passes the gates | Phase 2.3–2.9 |

AI story-based calls can't be backtested honestly (Claude already knows how 2016–2025 turned out), so they're tested
**forward** through the predictions log and paper trading. Text signals for history use methods that don't know the
future (word lists, the market's own reaction).

Legend: ⬜ not started · 🟡 in progress · ✅ done · ⏸ blocked

---

## Phase 0: Prerequisites

- [x] Python 3.13 environment (`.venv`, created with uv; pandas, numpy)
- [x] Alpaca paper keys in `.env` (paper account, $100,000), tested
- [x] Machine check: M1 Pro, 8 cores, 16 GB RAM, sleep disabled
- [x] **Free disk space to ≥ 60 GB free.** Done 2026-11-06 with the user's OK: 33 GB → **78 GB free** (cleared npm, uv, pip,
      CocoaPods, Apple ML model cache, Xcode iOS DeviceSupport; kept Xcode UserData/Archives, Hugging Face, Ollama)
- [x] **Power and restart (decided 2026-11-06):** ichigo is a **MacBook Pro** (14-inch, M1 Pro), so its **battery acts as a
      built-in UPS** during power cuts. `pmset autorestart` doesn't apply to laptops (the user ran it; macOS doesn't list it).
      FileVault stays **on**; after any restart **the user logs in with their password**. Requirement: after login,
      **every service must start by itself**, with no manual steps. Keep the lid open (or closed with power + external display)
      so the laptop doesn't sleep.
- [x] Background services run as **launchd user agents** (`RunAtLoad` + `KeepAlive`) in the logged-in session (PostgreSQL, scheduler/workers,
      dashboard): they start at login and restart if they crash. They must run in the user's session because headless
      `claude -p` needs the unlocked login keychain (SSH-only sessions have shown "keychain locked" errors for MCP servers).
      On startup the system catches up: missed jobs run or expire, and the gap checker backfills missing data.
- [x] Install **PostgreSQL 17 + pgvector** via Homebrew; start it as a service (starts on boot); create database `market`
- [x] SEC EDGAR identity saved in `.env` as `SEC_USER_AGENT` (name + email; no account needed)
- [x] Git repo on `main`, pushed to the **private** GitHub repo `ninadkale98/trading` (first commit 2026-11-06). `.gitignore` covers `.env`, `.venv/`, `.stockview/`, logs, backups, `.claude/settings.local.json`. Commit and push at each finished step (user OK, 2026-11-07); never commit secrets.

**Done when:** `psql market` connects, ≥ 60 GB free, auto-restart on, git repo exists.

---

## Phase 1: Foundation

**Goal:** honest, up-to-date data for all ~5,000 stocks (including delisted ones), a task system that survives
failures, and a backtester that can test any idea without cheating.

### 1.1 Project skeleton
- [x] `pyproject.toml` with pinned dependencies; package layout `core/{db,tasks,ingest,features,backtest,planner,risk,execution}`
- [x] `config/settings.yaml` (schedules, budgets) and `config/limits.yaml` (**Tier-1 hard limits**; only the user edits it)
- [x] Logging to the database (`runs`, `events`, `errors`) and to rotating files
- [x] Unit-test setup (`pytest`); tests run before any deploy

### 1.2 Database schema (SQL migrations, versioned)
- [x] Market data (migration 001): `stocks`, `daily_prices` (raw + `adj_factor` instead of a separate `corporate_actions` table), `liquidity`, `news`, `filings`, `financials`, `insider_trades`. **Still to add when their loaders are built:** `earnings`, `fund_holdings`, `short_interest`, `macro`. Original list:
      `earnings`, `insider_trades`, `fund_holdings`, `short_interest`, `macro`
- [x] System: `tasks` (also serves as the run log), `events`, `errors`, `heartbeats`, `schedules`, `resource_pauses`, `backtest_runs` (migration 002). `ai_usage` comes in Phase 3.
- [x] Point-in-time columns on everything (`known_at`; `valid_from`/`valid_to` where versioned)
- [x] Indexes for (symbol, date) lookups; table partitioning by year for `daily_prices` if needed

### 1.3 Task system and scheduler (§14 of the architecture)
- [x] `tasks` queue with priorities, retries with growing waits, **deferral on limits**, expiry, idempotency keys
- [x] Worker process(es); each task isolated so one failure can't stop the rest
- [x] Scheduler (cron-like table) that creates tasks at the agreed times
- [x] macOS service (`launchd` plist) that keeps the daemon alive; heartbeat row updated every minute
- [x] CLI: `tradebot status | run <job> | retry <task> | pause | resume`

### 1.4 Universe
- [x] Load all Alpaca assets (**active and inactive/delisted**), map ticker ↔ SEC CIK
- [x] Sector/industry from SEC SIC codes (Alpaca has none) → our sector map
- [x] Daily liquidity tier per stock (liquid ≥ $5M ADV · thin $1–5M · emerging < $1M), bid/ask spread check

### 1.5 Price loader
- [ ] Backfill daily bars 2016 → today for all symbols, including delisted (multi-symbol requests, ≤ 200 req/min, `feed=sip`)
- [x] Store raw prices + split/dividend adjustment factors (adjusted series derived)
- [x] Nightly incremental load at 4:30 pm ET; request end ≥ 16 min in the past
- [x] Reference ETFs: SPY, QQQ, IWM, sector ETFs (XLK, XLE, XLF, …, SMH)

### 1.6 News loader
- [x] Incremental every 15–30 min (multi-symbol), headlines + summaries; full content for stock-focused items (≤ 3 tags)
- [ ] Backfill 2 years first (bounded size); extend later if useful

### 1.7 SEC EDGAR loader
- [x] Filing index per company (8-K with item codes, 10-Q, 10-K, 20-F, 6-K, Form 4, 13D/G, S-1, proxy). 13F is filed by funds, not companies → separate loader later (Phase 3).
- [x] XBRL company facts → quarterly financials (revenue, gross profit, operating income, net income, EPS, cash, debt)
- [x] Form 4 parsing → insider buys/sells
- [ ] Earnings dates (8-K Item 2.02) as a free earnings calendar
- [x] Rate limit ≤ 10 req/s, identity header

### 1.8 Data quality
- [x] Nightly **gap checker** (missing days or symbols → backfill tasks)
- [ ] Sanity checks: zero/negative prices, extreme moves without news, stale symbols
- [ ] **Survivorship report:** how many delisted stocks have full history; document any gap and its likely effect on backtests

### 1.9 Backtester
- [x] Daily, event-driven simulator that reads **only data known at the simulated date**
- [x] The same order logic as live: limit entries, bracket stops and targets, trailing stops, time stops, earnings exits
- [x] Cost model: spread + slippage by liquidity tier
- [x] Delistings handled (position closed at the last price)
- [x] Metrics: total and yearly return, max drawdown, win rate, avg win/loss, **expected value per trade**, t-stat, vs SPY
- [ ] Splits: train 2016–2022 · validate 2023–2024 · holdout 2025–2026 (holdout use logged)
- [ ] Random-entry baseline; counter of how many ideas have been tested (multiple-testing penalty)

### 1.10 Validation of the foundation
- [x] Buy-and-hold SPY in the backtester matches SPY's actual return
- [x] Re-run the Apple → QCOM/SWKS/CRUS pair study from the database (same numbers as the Nov 2026 study)
- [x] Simple 200-day trend rule produces sensible, reproducible results

### 1.11 Storage and backups
- [ ] Measure database size after backfill; update the storage budget below
- [ ] Nightly compressed `pg_dump`; keep 7 daily + 4 weekly; restore test once

**Done when:** all ~5,000 stocks (and delisted history) load nightly without manual help; tasks survive forced failures
(kill a worker, block network, fake a Claude limit); the backtester passes 1.10.

---

## Phase 2: Paper-trading MVP

**Goal:** the system picks, sizes, places and manages paper trades on its own, asks for approval when it should,
and gives the user a daily briefing and a basic dashboard.

### 2.1 Features (daily, all stocks)
- [x] `core/features/` (one implementation for the nightly job **and** the backtester): returns 1d–1y, distance from
      20/50/200-day averages and their slopes, RSI, ATR %, volatility, relative volume, ADV, accumulation (20/50 d),
      52-week high/low distance, gap, relative strength vs SPY and sector ETF, **RS rank 1–99**, beta, trend score 0–5;
      earnings timing (days since, reaction vs SPY, days to next report: exact calendar date when known that day, else +91 d).
      Table `features_daily` (migration 004), stored from 2024-01-01 (~3.5M rows); older dates recomputed on demand.
      Chain: `prices.daily` → `features.daily` → `market.snapshot`. Tests: values, **no look-ahead** (scrambled future
      leaves the past unchanged), point-in-time earnings calendar
- [ ] Fundamentals: earnings surprise (Alpha Vantage history), revenue and margin growth, valuation (P/E, P/S), insider net buying
- [ ] Finnhub company news (daily, active stocks) and GDELT theme volume/tone (daily) → moved to Phase 3 (research inputs)
- [x] Alpha Vantage loader within 25 requests/day (counted in `api_usage`): daily calendar (1 call, ~2,000 reports);
      earnings history for liquid stocks (just-reported first, then by size; 17 biggest loaded on day 1). Estimate revisions: later, for candidates
- [x] Finnhub: daily calendar snapshot with EPS/revenue estimates (10 weekly windows, ~2,300 reports) → `earnings_calendar`
      keeps every day's snapshot (our own estimate history); view `upcoming_earnings`; weekly analyst rating counts (`analyst_ratings`)

### 2.1b Market snapshot (architecture §5.6)
- [x] 65 reference ETFs in `core/market/groups.py` (index, sector, theme, style, bonds/credit, commodities/currency, global); history loaded
- [x] FRED loader: 23 series (rates, credit, inflation, jobs, growth, housing, dollar/oil, financial conditions); release
      series keep the first-published value and publish date (`output_type=4`), plus the latest revised value
- [x] Daily `market_snapshot` (migration 005): breadth, sector/theme rotation (leading/weakening/lagging/improving), style,
      risk signals, global, leaders, top movers, regime label + exposure-dial level; dashboard **Market** page with
      breadth history and the economy table; backfilled for the stored feature window

### 2.2 Strategies (plug-in interface, architecture §8)
- [ ] Interface + loader for `strategies/{promoted,paper,experimental,retired}`
- [ ] Quality pullback in uptrend
- [ ] Earnings overreaction (must separate QCOM-type rebound vs Intel-type drift)
- [ ] Return to the average
- [ ] Accumulation
- [ ] Each one through backtest + validation gates; results in `lab/`

### 2.3 Market exposure dial + SPY market sleeve
- [ ] Regime from SPY vs 200-day average and market breadth → 90–100% / ~50% / 20–30%
- [ ] Sleeve logic: unused money into SPY when healthy; SPY sold first to fund picks or cut exposure

### 2.4 Planner and risk
- [ ] Rank candidates by expected value per unit of risk after costs
- [ ] Initial calibration from backtests; calibration table updated from live results
- [ ] Sizing (Tier 2 normal 0.5–1% risk) and **Tier-1 hard limits from `config/limits.yaml`, enforced in code with unit
      tests** (2% max loss per trade, 15% per stock, 30% per theme, 25% per sector, 40% per unproven strategy, stop-loss
      required, no margin/options/shorting, −10% circuit breaker)
- [ ] Theme clusters: sector-based until the graph exists (Phase 3)
- [ ] Liquidity-tier sizing

### 2.5 Execution (Alpaca paper)
- [ ] Order client: limit entries as bracket orders, trailing-stop manager, time stops, earnings exits, thesis-broken exits
- [ ] Order and position sync; nightly reconciliation with Alpaca
- [ ] Journal of every plan, order, fill and exit, with estimated real-world costs subtracted

### 2.6 Approvals (architecture §10.8)
- [ ] `approvals` table: request, for/against, size, worst-case loss, deadline, decision, comment, outcome
- [ ] Escalation rules (emerging stocks, holding through earnings, first trades of a newly promoted strategy, circuit breaker resume)
- [ ] Safe defaults at the deadline (no trade; exits proceed)
- [ ] Chat workflow: Claude can list pending approvals and record "approve #3, half size"

### 2.7 Daily briefing v1
- [ ] 9:30 pm (+ 6:30 am update) briefing from data and templates; saved to `reports/daily/YYYY-MM-DD.md`
- [ ] Sections: day in 5 lines · decisions needed · top findings · portfolio vs SPY · learned · tomorrow

### 2.8 Dashboard v1 (FastAPI, light theme, phone-friendly)
- [x] Pages: **Review** (needs-attention list, briefing and approvals placeholders until 2.6/2.7, last 24 h), **Live** (running
      jobs with progress, queue grouped by job, schedule with next/last run + "Run now", pause/resume sources), **Today**
      (timeline, any day), **Portfolio** (Alpaca paper account, positions, orders, account vs SPY), **Data** (coverage,
      liquidity tiers, sectors), **Health** (data freshness vs trading calendar, failed/retrying jobs with Retry, errors, disk)
- [x] Served on ichigo by launchd agent `com.ninad.tradebot.dashboard` (`tradebot dashboard`); **`localhost:8090`** (8080 is
      taken by another local project) via VS Code port forwarding; no-cache headers so updates show on refresh; 12 tests
- [ ] Approval queue with buttons (with 2.6), briefing rendering (with 2.7), Market page (with 2.1b), phone-width check by the user

### 2.9 Go-live
- [ ] **Dry run 3–5 trading days:** plans and briefings only, no orders; fix issues
- [ ] Enable paper orders → **start the 1–2 month clock** (record the date in the build log)

**Done when:** a full trading week runs unattended: data → plans → approvals → orders → stops → journal → briefing,
with zero crashes and every failure visible on the Health page.

---

## Phase 3: Knowledge layer and AI agents

### 3.1 Claude runner
- [ ] Headless `claude -p` wrapper: model per task (Haiku/Sonnet/Opus), daily budget, limit detection → defer,
      output checked against a schema, `ai_usage` logging, optional Opus → Sonnet fallback (labeled)

### 3.2 News and filings understanding (Haiku)
- [ ] Headline triage in batches (~50): relevance, direction, companies, event type
- [ ] Fact extraction from 8-Ks and 10-K/10-Q text (customers, suppliers, competitors, guidance, risks)

### 3.3 Economy graph (architecture §5.1)
- [ ] `nodes`, `edges` tables (typed, signed, weighted, dated, sourced, versioned)
- [ ] Weekly statistical edges (correlation after removing market and sector), sector/ETF edges, news co-mention edges
- [ ] Customer/supplier/competitor edges from annual reports; theme nodes and exposures
- [ ] Python graph engine (igraph/networkx): neighbors, communities, centrality, shock propagation, paths
- [ ] Theme clusters from the graph replace the sector-based proxy in the risk limits

### 3.4 Claims, company maps, research queue
- [ ] Claims with evidence and versions; Sonnet reconciliation (confirm / update / contradict); knowledge changelog
- [ ] Company maps + tripwires; export to `knowledge/companies/<SYMBOL>.md`
- [ ] Research priority queue (staleness + event + graph + setup + holding bonuses); first full sweep, then rotation
- [ ] Stock lifecycle states (Monitoring → Watching → Candidate → Confirming → Plan → Position → Exit → Review)
- [ ] Move classification: market / sector / neighbor / company-specific

### 3.5 Opus daily agents
- [ ] 6:00 am morning plan (may trim/cancel only); 9:00 pm summary + new ideas; briefing v2 written with Opus input

### 3.6 Similar past situations
- [ ] pgvector numeric fingerprints (feature vectors, no language model); "this looks like…" lookups in research and briefings

### 3.6b Memory and AI search toolkit (architecture §5.5)
- [ ] `market_days`, `theme_days`, `stock_timeline`, `journal_rollups`, `predictions` tables
- [ ] Read-only database user + `tradebot memory / search / sql` commands with `--as-of`; PostgreSQL full-text search over
      news, transcripts, journals, company maps, claims
- [ ] Market pack builder (~30–60k tokens) for Opus
- [ ] **Opus daily market analysis** (9 pm) → `reports/market/` + market journal; predictions written and auto-scored
- [ ] Saturday weekly roll-up + **weekly money-flow map**; monthly and quarterly chapters
- [ ] One-time catch-up: quarterly chapters 2016 → today from stored prices and news (spare plan capacity)
- [ ] Budget scheduler fills unused capacity in each 5-hour window with low-priority work

### 3.6c Study of big moves v1 (architecture §9)
- [ ] Find big winners/losers since 2016; snapshot what was knowable before; compare with look-alikes that didn't move
- [ ] Base-rate report; case studies of recent winners (labeled hindsight)

### 3.7 Dashboard: Knowledge and Market pages
- [ ] Graph explorer (see architecture §5.4), company maps, changelog; sector heat map, big moves with causes

### 3.8 Research studies
- [ ] **Pooled customer → supplier lag test** across all graph pairs (the single-pair Apple studies were too small)

**Done when:** every stock has a company map (first sweep finished), the graph updates weekly, Opus plan/summary run
daily, and limits/failures defer cleanly.

---

## Phase 4: Idea lab and self-improvement

- [ ] `ideas`, `experiments`, `backtest_results`, `strategies` (stage + version) tables; `lab/notebook.md` generated from them
- [ ] Opus idea generation (nightly short list, weekly round) reading the notebook
- [ ] Sonnet writes strategies into `strategies/experimental/` only; sandboxed runs; `core/` and `config/limits.yaml` protected
- [ ] Automated stage gates (backtest → validation → paper → promote/retire), holdout usage logged, multiple-testing penalty
- [ ] **Conviction bets:** Opus proposer → Sonnet skeptic (bear-side data) → **user approval** → tracked as its own record;
      allowance grows or shrinks with results
- [ ] Performance-decay monitor; retirement
- [ ] Study of big moves feeds idea proposals automatically; daily "matches a winner profile" watch list, outcomes recorded
- [ ] Weekly picks, monthly scorecard, Idea lab dashboard page with calibration charts

**Done when:** the lab runs a full weekly cycle by itself (propose → test → promote or retire) and the user sees it in reports.

---

## Phase 5: Operate and review

- [ ] Weekly check-ins: briefing quality, approvals, failures, AI usage vs plan limits
- [ ] Monthly scorecard vs SPY; calibration review; tune budgets and thresholds
- [ ] After 1–2 months: written review (what worked, what didn't, next steps). Any discussion of real money starts here,
      and every real order still needs explicit approval

---

## Cross-cutting rules
- Tier-1 limits are code-enforced with unit tests; changes only via the user editing `config/limits.yaml`
- Secrets only in `.env`; never logged or printed
- Every phase updates `docs/architecture.md` if the design changes, and this file's checkboxes and build log
- New concepts the user may not know → `learning/` (+ glossary)

## Storage budget
| Item | Estimate (year 1) |
|---|---|
| Daily prices, ~5,000 stocks × 10 years (+ delisted) | 2–3 GB with indexes |
| Daily features (recent years stored; older recomputed on demand) | 2–4 GB |
| News (headlines + summaries; full text for focused items) | 2–4 GB |
| Filings facts, insider trades, holdings | 1–2 GB |
| Knowledge, graph, tasks, logs, journal | < 1 GB |
| Backups (compressed, 7 daily + 4 weekly) | 5–8 GB |
| **Total** | **~15–20 GB**; keep ≥ 40 GB free on the disk |

## Build log
| Date | Entry |
|---|---|
| 2026-11-06 | Architecture agreed. Python env, Alpaca paper keys, Stock View extension, learning docs done. Disk: 33 GB free (needs cleanup before Phase 1). |
| 2026-11-06 | Phase 0 started. Caches cleared → 78 GB free. SEC identity saved. Power: MacBook battery = UPS; FileVault stays on; user logs in after restarts; all services must auto-start at login. |
| 2026-11-06 | **Phase 0 done.** PostgreSQL 17.11 + pgvector 0.8.7 via `brew services` (starts at login, KeepAlive). Database `market`. Python 3.13 venv via uv (system python3 is 3.15 and breaks venv/ensurepip). |
| 2026-11-06 | **Phase 1 code done:** `core/` package, migrations 001–002, task queue + scheduler + daemon (launchd agent `com.ninad.tradebot`, `scripts/install_services.sh`), CLI `tradebot`, loaders (universe, prices, liquidity, news, SEC profiles/filings/financials, insider trades), quality (gaps, survivorship), nightly backup, backtester + validation. 18 tests pass (`pytest`). |
| 2026-11-06 | Universe: 5,445 active common stocks (SPACs, warrants, units, preferreds, debt, ETFs excluded) → 5,431 tradable + reference ETFs; 663 delisted common stocks known to Alpaca (fewer than real-world delistings → survivorship report will quantify). Liquidity: ~2,750 liquid / ~480 thin / ~2,120 emerging. |
| 2026-11-06 | Validation (`python -m core.backtest.validate`): SPY buy & hold +329.54% vs actual +329.64%; AAPL adj factor 0.2249; 200-day rule cuts max drawdown −33.8% → −19.5%; look-ahead detector works; Apple→supplier study reproduced exactly from the database. |
| 2026-11-06 | Lessons/fixes: (1) API timestamps must be converted to UTC (DB session is Pacific). (2) Unknown task types now wait for a daemon restart instead of failing. (3) Rate limiter is now shared across processes via lock files (CLI + daemon together must stay under SEC's 10 req/s). (4) SEC lists insider quarters before publishing them → 404s skipped. (5) Long backfills starved short jobs at 4 threads → 8 worker threads. (6) Benchmarks must run with `enforce_limits=False` (the 15% cap otherwise applies). |
| 2026-11-06 | Backfills queued (running in the daemon): prices 2016→today for ~6,100 symbols, news 2 years, SEC profiles/filings/financials for 5,326 companies, insider trades 2016→2026q1 bulk. **Remaining for Phase 1:** let backfills finish, then run survivorship report, measure DB size, test a backup restore, earnings-date table from 8-K item 2.02. |
| 2026-11-06 | Backfills done: prices 11.46M bars / 5,986 symbols; news 535k items (from 2019-07); insider 2.31M transactions (41 quarters, through 2026q1). SEC backfill hit a company whose XBRL file has no `facts` section (KeyError, 5 retries) → fixed: missing facts = 0, and one company's bad data is now logged and skipped instead of stopping the run. DB 3.5 GB; 74 GB free. |
| 2026-11-06 | **Design additions (user request):** no local language model, maximize the Claude Max plan (budget scheduler fills spare capacity); memory at market/theme/stock level with roll-ups, predictions log and a read-only AI search toolkit (arch §5.5); market snapshot + Opus daily market analysis for learning + weekly money-flow map (§5.6, §17); study of big moves (§9). AI story calls are tested only going forward (Claude knows past outcomes). Added to Phases 2 (2.1b), 3 (3.6b, 3.6c) and 4. |
| 2026-11-06 | Data keys: **FRED** verified (10-year yield; vintage dates available → point-in-time macro). **Finnhub free** verified: upcoming earnings calendar with EPS/revenue estimates, last 4 quarters of surprises, recommendation counts, peers, insider sentiment; 403 on estimate history, price targets, upgrades, supply chain, transcripts, economic calendar. Bigdata.com key received in chat; waiting for it to be placed in `.env` to evaluate. |
| 2026-11-06 | Bigdata.com tested: AMD search returned 9 highly relevant docs (Benzinga, CNBC, Globe and Mail, Motley Fool, Quartr transcript, podcasts) with per-passage sentiment; cost 22 of 1,000 starter credits per 10-passage search (premium news ≈ 75%). Decision: reserve for high-value cases only. Free substitutes verified: Finnhub company news (248 AMD articles Nov 3–6, ~1-year history), GDELT (free, 1 req / 5 s), Claude web search inside research runs. |
| 2026-11-06 | **Phase 2 started: dashboard v1** at `localhost:8090` (FastAPI + one plain-JS page, light theme; launchd agent `com.ninad.tradebot.dashboard`). While building it, found that the **scheduler thread had died at 5:15 pm PT**: `scheduler.sync()` crashed on the one schedule with a payload dict (`**d` overwrote the JSON-encoded payload), and the exception escaped the loop while the heartbeat kept saying "healthy". Fixed: payload encoding; sync retried inside the loop; heartbeat now reports `scheduler_age_s` and live worker count; the daemon exits (launchd restarts it) if any thread dies; dashboard flags a scheduler with no pass in 5 min. Missed jobs ran on catch-up (gap check backfilled 74 stocks). Regression tests added; 32 tests pass. |
| 2026-11-06 | Dashboard reachable from other Tailscale devices at **http://ichigo:8090** (also `http://ichigo.saanen-shark.ts.net:8090`, `http://100.85.155.36:8090`): it listens on localhost + the Tailscale address only (`dashboard.tailnet_hosts`), not on the Wi-Fi; if Tailscale isn't up at login it starts on localhost and adds the address when it appears. The user's existing `tailscale serve` / Funnel setup (ports 443 and 8443 → other local apps) was left untouched. |
| 2026-11-06 | SEC backfill finished: 5,326 companies, 2.43M filings, 3.02M financial facts, 0 skipped; 5,246 / 5,431 stocks now have a sector. First backup: 0.76 GB. **Alpha Vantage** (free key) tested: earnings history with estimates since 1996, full calendar in 1 call, estimate revisions, transcripts free; news sentiment is premium. 25 requests/day. |
| 2026-11-07 | **Features + market snapshot (2.1, 2.1b).** `features_daily` 2024→today; first snapshot (Nov 6): *Mixed: S&P 500 uptrend, only 45% of stocks above their 200-day average, risk-off* → exposure 50%; tech lagging (XLK −17% in a month), healthcare/staples/real estate leading. Earnings calendars (AV 1,983 + Finnhub 2,301 reports), AV earnings history for 17 largest stocks, 23 FRED series (33k observations). Fixes: (1) ETFs/ETNs/commodity and currency trusts that SEC lists as companies (QQQ, MicroSectors ETNs, Sprott trusts, CurrencyShares…) were counted as common stock → classifier patterns + reference ETFs always "etf"; universe now 5,364 companies + 65 ETFs (SPCX is SpaceX, correctly common). (2) Feature backfill memory: 500-column chunks and 20-day write batches (~1.2 GB peak). Learning: `11-our-daily-numbers.md`. |
| 2026-11-07 | **Re-plan (user):** understanding first, all kinds of strategies, no rush to paper trade. First train results: no price-only strategy passes; signal study shows only momentum predicts (+1.5% vs pool at 60 days, stops cut it short). Research agent → `learning/12` (ranked shortlist: insiders, earnings surprise + momentum, weekly news tone, quality, Claude on calls forward, revisions). **Step A done:** Claude runner (headless `claude -p`, custom short system prompt, JSON schema, usage log `ai_usage`, per-model daily budget, limits → pause), Haiku news triage (100 headlines ≈ 45–110 s ≈ $0.01 equiv; ~3,200/day), news features (count, net tone, major event over 5 days). Works from the launchd daemon (no keychain problem). |
