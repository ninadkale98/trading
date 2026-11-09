# Lab notebook

Lessons from trade reviews and experiments, newest last. The idea lab reads this before proposing new tests, so failures are never repeated blindly.

## Lab round 1 (2026-11-08)
- rs_wide_leash: reject: no edge: 60d +0.00% vs pool (t_adj 0.00)
- insider_dip_quality: reject: no edge: 60d -0.67% vs pool (t_adj -0.15)
- surprise_near_high: admit: sign of life: backtest +2.18%/trade vs SPY (t 1.25)
- gp_yield_trend: reject: no edge: 60d -1.34% vs pool (t_adj -1.03)
- Lesson: An exact 0.00% vs pool with t 0.00 means the comparison failed, so it must be reported as 'could not measure' and must not be used as a 'no edge' verdict. *(evidence: rs_wide_leash showed vs_pool 0.0 and t 0.0 at 5, 20 and 60 days across about 100,000 signals, and its verdict cited that figure. Its filter-only rules probably made signals and pool identical.; test: Add a build check that fails when the signal set equals the pool or when vs_pool is exactly 0 at all horizons. Re-run rs_wide_leash's signal study against the broader eligible universe.)*
- Lesson: The overlap adjustment divides t by sqrt(horizon) regardless of signal frequency, which probably over-penalises rare signals and biases the lab against low-frequency strategies. *(evidence: t_vs_pool_adj equals t_vs_pool / sqrt(horizon) in every checked case, such as surprise_near_high at 60 days (2.027 to 0.262, 47 signal days) and gp_yield_trend at 60 days (-7.94 to -1.03, 1,422 signal days).; test: Recompute all four signal studies with an overlap-aware method, such as date-clustered errors or a calendar-time portfolio. Confirm that sparse strategies change materially while dense ones change little, then re-check past rejections of sparse ideas.)*
- Lesson: Admission should check each idea's pre-registered falsification criteria, and any idea admitted despite failing one should be labelled probationary with a written retirement rule. *(evidence: surprise_near_high said it was proven wrong if t_vs_twin was below 2.0. It scored 0.41, passed 1 of 4 gates, and still went live under the sign-of-life rule.; test: Add a pass/fail/not-run field for each falsifier to the round output. Backtest the lab's admission rule over past rounds with and without a falsifier requirement, and compare later live or out-of-sample excess.)*
- Lesson: Require positive average excess after removing the single best year, because one exceptional year can create an apparently positive backtest. *(evidence: insider_dip_quality averaged +2.85% per trade vs SPY, but 2020 contributed 71 trades at +15.44%. The other 193 trades averaged about -1.8%.; test: Add a leave-best-year-out statistic to the backtest output and apply it to all 8 live strategies. Flag any whose average excess turns negative.)*
- Lesson: Widening exits alone did not improve relative_strength; longer holding did not add edge to these entries. *(evidence: rs_wide_leash lifted average hold from about 19 to 58 days, but excess vs twin fell from the parent's +0.93% to +0.46% (t 0.31), average excess vs SPY was -1.36%, and 65% of trades still ended at a stop.; test: Before proposing another exit-only variant, run the parent's entry across a preset stop grid of 15%, 25% and 35%, counting each as a test. Continue only if excess vs twin improves steadily with stop width.)*
- Lesson: gp_yield_trend's top-ranked stocks lagged at every horizon, so the score itself needs diagnosing before any further gross-profit-yield variant is built. *(evidence: Excess vs pool was -0.18%, -0.72% and -1.34% at 5, 20 and 60 days. The backtest was -1.90% vs SPY (t -1.98), positive only in 2017, and only 8 of 321 trades exited on a stop.; test: Within the eligible stocks, compare top-third vs bottom-third returns separately for gp_yield, rs_rank and op_margin_chg, as the hypothesis specified. Report sector and year breakdowns. Treat any inverted rule as a new test requiring its own mechanism.)*
- Lesson: Estimate trade count before backtesting; heavily filtered rules can be unable to reach the 100-trade gate within the data available. *(evidence: surprise_near_high stacked nine eligibility conditions and produced 50 trades over 2017-2022, about 8 per year. Reaching 100 at that pace would take roughly 6 more years.; test: Add a pre-backtest count requiring an expected 100 or more trades over the test window. For surprise_near_high, test one preset looser version (for example dist_52w_high >= -0.15) and count it against the multiple-testing bar.)*
- Lesson: The 'works most years' gate should require a minimum number of qualifying years, since a pass based on two years is weak evidence. *(evidence: surprise_near_high passed with '100% of 2 years'. Only 2017 and 2020 appear to have had enough trades to count, while the other four years had 3 to 8 trades.; test: Require at least 4 qualifying years to pass the gate, otherwise report 'insufficient data'. Re-score all live strategies under this rule.)*
- Lesson: surprise_near_high still needs its planned robustness and out-of-sample checks; live simulation is too slow to substitute for them. *(evidence: The validate field is null, the backtest years end at 2022, and the promised run with eps_surprise capped at 0.50 does not appear in the results.; test: Run the 0.50-cap version, and run the unchanged rules on 2023 to the present if that data has not been used for development. Pass only if excess vs SPY and vs twin remain positive, and report the t-stats against the current bar.)*

## User idea (2026-11-09): buy the biggest companies after a news-driven one-day drop
- Idea: when a mega-cap leader (e.g. NVDA on 2026-11-09, −4.3% gap on CEO-scandal news) falls ≥ 4% on company news while
  the market is calm, buy and hold for weeks; "a company this important always comes back".
- Quick event study (Claude, 2026-11-09; daily bars 2016+, top 10 common stocks by 60-day dollar volume point-in-time,
  day ≤ −4% while SPY > −1%; 620 events, 28 stocks): 60 days later avg +3.2% vs SPY but median −0.4% and only 49% beat
  SPY (a few big winners carry the average); 63% fell a further 10%+ within 60 days. Top 50 instead: 60d avg −1.1% vs
  SPY, 40% beat. NVDA alone: +7.1%, 60% beat, but NVDA was the decade's best stock (hindsight).
- To test properly: honest t (overlap), leave-best-year-out, split by news vs no-news drops once 2019+ Haiku labels
  exist (Chan 2003: news-driven moves tend to drift, no-news moves reverse), split by news type (management/legal vs
  earnings/guidance), exit when the thesis breaks (e.g. CEO leaves) vs a fixed stop.
- Follow-up (user, 2026-11-09): "big companies always bounce back after a crash, especially after heavy-volume
  selling" (example QCOM 147 → 170, Jul → Aug 2026). Crash study (one event per stock per 60 days, daily bars 2016+):
  - Any top-50 stock by dollar volume: about a coin flip vs SPY (44–51% beat at 120 days); hype names (COIN, UPST,
    AMC, SE) dominate the losers.
  - **Steadily big only** (top 100 by dollar volume in ≥ 95% of the last 500 days): better. Top 20, ≥ 25% below the
    60-day high with a heavy-volume down day (≥ 2× 60-day average volume) in the last 5 days: 77 events, 120d
    +9.3% vs SPY (median +6.2%, 58% beat). ≥ 35% below: 31 events, 60d +8.8% (65% beat). Without the volume rule:
    weaker (median +0.7%). 2023–2026 events were positive too, but 2021 was −21%.
  - Caveats: 12 variants tried (multiple testing), events cluster in 2020 and 2022 (not independent), ~half fell
    another 15% first, and only ~30% regained the prior high within 6 months.
  - **Test this round as a pre-registered candidate** (`big_crash_capitulation`): steady top 20, ≥ 25% below the
    60-day high, heavy-volume down day within 5 days, hold up to 120 days, wide stop (≥ 25%) or none; honest t,
    leave-best-year-out, ≥ 4 years, out-of-sample 2023+. Variants count against the bar.
- Entry timing (user asked: watch the fall closely, buy when it turns): on the same events, waiting was WORSE on daily
  bars. Steady top 20, ≥ 25%, heavy volume, all exits at signal + 120 days: buy at the signal close +9.3% vs SPY
  (median +6.2%, 58% beat); wait for a close above the prior 5 days' high +5.4% (median 0.0%, 51%; worse than buying
  at once in 74% of pairs); wait for +8% off the low +8.4%; turn + volume calming +6.6% but the fewest "fell 15%+
  after entry" (41% vs 47%; 34% vs 43% in the ≥ 15% version). So the turn signal gives up the bounce's fast start
  and barely avoids the losers; volume calming mainly lowers the pain. Lab: test entry A as the main rule, D as a
  lower-drawdown variant. An intraday (15-min) version needs Alpaca minute history around events; only worth it if
  the daily version passes.
