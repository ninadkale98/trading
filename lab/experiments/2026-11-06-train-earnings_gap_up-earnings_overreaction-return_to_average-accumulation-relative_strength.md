# Lab run: train (2016-01-01 → 2022-12-31), 2026-11-06

Each strategy is compared with SPY over the same holding days and with a random twin (same number of picks per day, random stocks from the same pool, same exits). Gates are fixed in core/lab/evaluate.py.
Features need a year of history, so the first months of the period have few or no signals.

## accumulation v1, train (2016-01-04 → 2022-12-30)

**Idea:** Over the last 50 and 20 days, clearly more volume on up days than down days (accumulation ≥ 0.15 and ≥ 0.10), price within 10% of its 52-week high and above its 50-day average, not already up more than 40% in 3 months. Strongest accumulation first. Trailing stop, hold up to 3 months.

**Why it might work (written before testing):** Big investors build positions over weeks and can't hide the volume: persistent up-day volume can reveal buying before the price fully reflects it.

| Measure | Strategy | Random twin |
|---|---|---|
| Trades | 894 | 1053 per run |
| Win rate | +40.3% | +35.6% |
| Average return per trade | +1.0% | |
| **Average excess vs SPY per trade** | **-0.6%** (t -1.64) | -0.6% |
| Average win / loss | +11.4% / -6.0% | |
| Average hold | 31 trading days | |
| Account return (picks only, idle cash) | +24.0% | |
| Account return with SPY sleeve | +38.1% | |
| SPY over the same period | +113.7% | |
| Worst drop (picks only) | -36.5% | |

| Gate | Result | Needed | |
|---|---|---|---|
| enough trades | 894 | ≥ 100 | ✅ |
| beats spy per trade | -0.62% (t -1.64) | > 0 with t ≥ 2.00 (5 backtests run so far) | ❌ |
| beats random twin | -0.05% per trade (t -0.12) | > 0 with t ≥ 2 | ❌ |
| works most years | 0% of 7 years | ≥ 60% | ❌ |

**Verdict: did not pass**

| Year | Trades | Win rate | Avg return | Avg excess vs SPY |
|---|---|---|---|---|
| 2016 | 29 | 52% | +3.93% | -0.57% |
| 2017 | 109 | 52% | +2.94% | -0.40% |
| 2018 | 142 | 29% | -0.79% | -0.88% |
| 2019 | 120 | 52% | +2.44% | -0.88% |
| 2020 | 174 | 40% | +2.34% | -0.17% |
| 2021 | 151 | 41% | +0.77% | -1.15% |
| 2022 | 169 | 31% | -1.46% | -0.37% |

Exit reasons: {'stop': 526, 'time': 240, 'stop_gap': 79, 'delisted': 29, 'end_of_test': 20}
Run id: 5

## earnings_gap_up v1, train (2016-01-04 → 2022-12-30)

**Idea:** The day after an earnings report, if the stock beat the market by 5% or more on heavy volume (2× normal) and was already in a decent trend (score ≥ 3), buy at the next open and hold up to ~2 months.

**Why it might work (written before testing):** Post-earnings announcement drift, one of the most-replicated findings in finance: after good news, prices keep drifting the same way for weeks because investors under-react to it.

| Measure | Strategy | Random twin |
|---|---|---|
| Trades | 946 | 938 per run |
| Win rate | +33.8% | +28.6% |
| Average return per trade | +0.3% | |
| **Average excess vs SPY per trade** | **-0.5%** (t -1.26) | -0.4% |
| Average win / loss | +12.9% / -6.2% | |
| Average hold | 18 trading days | |
| Account return (picks only, idle cash) | +1.9% | |
| Account return with SPY sleeve | +32.9% | |
| SPY over the same period | +113.7% | |
| Worst drop (picks only) | -47.0% | |

| Gate | Result | Needed | |
|---|---|---|---|
| enough trades | 946 | ≥ 100 | ✅ |
| beats spy per trade | -0.47% (t -1.26) | > 0 with t ≥ 2.00 (6 backtests run so far) | ❌ |
| beats random twin | -0.12% per trade (t -0.28) | > 0 with t ≥ 2 | ❌ |
| works most years | 43% of 7 years | ≥ 60% | ❌ |

**Verdict: did not pass**

| Year | Trades | Win rate | Avg return | Avg excess vs SPY |
|---|---|---|---|---|
| 2016 | 22 | 50% | +3.68% | +0.07% |
| 2017 | 148 | 41% | -0.11% | -2.01% |
| 2018 | 176 | 31% | -0.46% | -0.05% |
| 2019 | 123 | 33% | -0.76% | -2.30% |
| 2020 | 155 | 29% | +1.79% | +0.76% |
| 2021 | 186 | 37% | +0.42% | -0.79% |
| 2022 | 136 | 30% | +0.09% | +1.25% |

Exit reasons: {'stop': 633, 'time': 227, 'stop_gap': 80, 'end_of_test': 6}
Run id: 6

## earnings_overreaction v1, train (2016-01-04 → 2022-12-30)

**Idea:** A stock that was strong before its report (RS rank ≥ 60, still above its 200-day average) fell at least 8% more than the market on earnings. Wait 3 trading days; buy only if it has held above the reaction-day low and is up from the reaction-day close (selling has stopped).

**Why it might work (written before testing):** Sometimes the first reaction to bad news is too big for a good company (QCOM-type rebound). The 3-day wait and 'held the low' check are meant to skip Intel-type drifts, where bad news keeps getting priced in for weeks. Research says drift usually wins, so this one may well fail: that's what the test is for.

| Measure | Strategy | Random twin |
|---|---|---|
| Trades | 345 | 307 per run |
| Win rate | +33.3% | +39.1% |
| Average return per trade | -0.3% | |
| **Average excess vs SPY per trade** | **-0.3%** (t -0.41) | -0.5% |
| Average win / loss | +12.9% / -6.9% | |
| Average hold | 15 trading days | |
| Account return (picks only, idle cash) | -14.4% | |
| Account return with SPY sleeve | +84.1% | |
| SPY over the same period | +113.7% | |
| Worst drop (picks only) | -23.5% | |

| Gate | Result | Needed | |
|---|---|---|---|
| enough trades | 345 | ≥ 100 | ✅ |
| beats spy per trade | -0.30% (t -0.41) | > 0 with t ≥ 2.00 (7 backtests run so far) | ❌ |
| beats random twin | +0.16% per trade (t 0.20) | > 0 with t ≥ 2 | ❌ |
| works most years | 33% of 6 years | ≥ 60% | ❌ |

**Verdict: did not pass**

| Year | Trades | Win rate | Avg return | Avg excess vs SPY |
|---|---|---|---|---|
| 2017 | 43 | 40% | +0.47% | -0.90% |
| 2018 | 62 | 37% | -0.91% | -0.56% |
| 2019 | 38 | 39% | +2.23% | +0.98% |
| 2020 | 65 | 34% | +1.90% | +2.14% |
| 2021 | 85 | 32% | -0.67% | -0.89% |
| 2022 | 52 | 21% | -4.12% | -2.51% |

Exit reasons: {'stop': 229, 'time': 84, 'stop_gap': 30, 'end_of_test': 2}
Run id: 7

## relative_strength v1, train (2016-01-04 → 2022-12-30)

**Idea:** Top-decile past-year performers (RS rank ≥ 90) with a perfect uptrend checklist (5/5), within 10% of their 52-week high, no earnings due. Strongest first. Wide trailing stop (15%), hold up to ~6 months; sell if the trend breaks (closes more than 3% below its 50-day average).

**Why it might work (written before testing):** Momentum: stocks that outperformed over the past 3–12 months tend to keep outperforming for the next several months (documented across decades and countries). Requiring a clean uptrend avoids stocks whose momentum has already cracked.

| Measure | Strategy | Random twin |
|---|---|---|
| Trades | 1360 | 1405 per run |
| Win rate | +35.3% | +37.0% |
| Average return per trade | +1.4% | |
| **Average excess vs SPY per trade** | **+0.6%** (t 0.97) | -0.3% |
| Average win / loss | +20.7% / -9.1% | |
| Average hold | 19 trading days | |
| Account return (picks only, idle cash) | +44.6% | |
| Account return with SPY sleeve | +75.9% | |
| SPY over the same period | +113.7% | |
| Worst drop (picks only) | -46.5% | |

| Gate | Result | Needed | |
|---|---|---|---|
| enough trades | 1360 | ≥ 100 | ✅ |
| beats spy per trade | +0.60% (t 0.97) | > 0 with t ≥ 2.04 (8 backtests run so far) | ❌ |
| beats random twin | +0.93% per trade (t 1.45) | > 0 with t ≥ 2 | ❌ |
| works most years | 50% of 6 years | ≥ 60% | ❌ |

**Verdict: did not pass**

| Year | Trades | Win rate | Avg return | Avg excess vs SPY |
|---|---|---|---|---|
| 2017 | 183 | 36% | +2.14% | +0.19% |
| 2018 | 230 | 24% | -2.40% | -2.42% |
| 2019 | 192 | 31% | +1.35% | -0.28% |
| 2020 | 262 | 42% | +5.88% | +4.52% |
| 2021 | 297 | 34% | +0.00% | -1.00% |
| 2022 | 196 | 45% | +1.34% | +2.55% |

Exit reasons: {'stop': 1025, 'signal': 137, 'stop_gap': 124, 'delisted': 40, 'end_of_test': 20, 'time': 14}
Run id: 8

## return_to_average v1, train (2016-01-04 → 2022-12-30)

**Idea:** Liquid stock above its 200-day average that just dropped sharply: RSI below 30 or down 8%+ in a week, with no earnings due. Buy at the next open; sell when it closes back above its 20-day average, or after 15 trading days.

**Why it might work (written before testing):** Short-term reversal: sharp drops in otherwise healthy, liquid stocks are often driven by temporary selling pressure and partly bounce back within days to weeks.

| Measure | Strategy | Random twin |
|---|---|---|
| Trades | 2474 | 3827 per run |
| Win rate | +54.4% | +57.1% |
| Average return per trade | +0.4% | |
| **Average excess vs SPY per trade** | **-0.1%** (t -0.51) | -0.1% |
| Average win / loss | +7.4% / -7.9% | |
| Average hold | 10 trading days | |
| Account return (picks only, idle cash) | +58.5% | |
| Account return with SPY sleeve | +80.7% | |
| SPY over the same period | +113.7% | |
| Worst drop (picks only) | -37.2% | |

| Gate | Result | Needed | |
|---|---|---|---|
| enough trades | 2474 | ≥ 100 | ✅ |
| beats spy per trade | -0.10% (t -0.51) | > 0 with t ≥ 2.10 (9 backtests run so far) | ❌ |
| beats random twin | +0.02% per trade (t 0.10) | > 0 with t ≥ 2 | ❌ |
| works most years | 14% of 7 years | ≥ 60% | ❌ |

**Verdict: did not pass**

| Year | Trades | Win rate | Avg return | Avg excess vs SPY |
|---|---|---|---|---|
| 2016 | 91 | 54% | +0.35% | -0.73% |
| 2017 | 371 | 57% | +0.55% | -0.33% |
| 2018 | 380 | 50% | -0.69% | -0.45% |
| 2019 | 364 | 57% | +0.86% | -0.17% |
| 2020 | 435 | 57% | +2.05% | +1.07% |
| 2021 | 397 | 54% | +0.30% | -0.63% |
| 2022 | 436 | 51% | -0.57% | -0.09% |

Exit reasons: {'signal': 1253, 'stop': 589, 'time': 541, 'stop_gap': 71, 'end_of_test': 19, 'delisted': 1}
Run id: 9
