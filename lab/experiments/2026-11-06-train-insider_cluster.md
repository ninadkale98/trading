# Lab run: train (2016-01-01 → 2022-12-31), 2026-11-06

Each strategy is compared with SPY over the same holding days and with a random twin (same number of picks per day, random stocks from the same pool, same exits). Gates are fixed in core/lab/evaluate.py.
Features need a year of history, so the first months of the period have few or no signals.

## insider_cluster v1, train (2016-01-04 → 2022-12-30)

**Idea:** At least 2 different insiders (executives, directors) bought shares on the open market within 90 days, and the count just went up (a new buyer joined in the last 5 trading days). Company worth ≥ $1B, trading ≥ $2M/day, no earnings within 2 weeks. Hold up to ~4 months with a wide 20% safety stop.

**Why it might work (written before testing):** Insiders know their company best and buy with their own money for one reason: they expect the price to rise. Several insiders buying at once is a stronger, less noisy signal than one. Research: insider purchases earned >6%/year above the market, clusters more (learning/12). Effects are smaller in big companies, so we require ≥ $1B to stay tradable.

| Measure | Strategy | Random twin |
|---|---|---|
| Trades | 517 | 528 per run |
| Win rate | +50.9% | +51.8% |
| Average return per trade | +3.3% | |
| **Average excess vs SPY per trade** | **-0.2%** (t -0.22) | +0.2% |
| Average win / loss | +20.9% / -14.9% | |
| Average hold | 64 trading days | |
| Account return (picks only, idle cash) | +78.4% | |
| Account return with SPY sleeve | +75.5% | |
| SPY over the same period | +113.7% | |
| Worst drop (picks only) | -45.5% | |

| Gate | Result | Needed | |
|---|---|---|---|
| enough trades | 517 | ≥ 100 | ✅ |
| beats spy per trade | -0.20% (t -0.22) | > 0 with t ≥ 2.15 (10 backtests run so far) | ❌ |
| beats random twin | -0.43% per trade (t -0.40) | > 0 with t ≥ 2 | ❌ |
| works most years | 43% of 7 years | ≥ 60% | ❌ |

**Verdict: did not pass**

| Year | Trades | Win rate | Avg return | Avg excess vs SPY |
|---|---|---|---|---|
| 2016 | 64 | 77% | +14.41% | +6.83% |
| 2017 | 64 | 55% | +1.92% | -3.06% |
| 2018 | 74 | 55% | +1.69% | +0.06% |
| 2019 | 65 | 35% | -2.12% | -4.90% |
| 2020 | 103 | 49% | +9.18% | +2.86% |
| 2021 | 67 | 52% | +3.14% | -1.54% |
| 2022 | 80 | 38% | -6.15% | -2.74% |

Exit reasons: {'time': 347, 'stop': 127, 'stop_gap': 26, 'end_of_test': 17}
Run id: 10
