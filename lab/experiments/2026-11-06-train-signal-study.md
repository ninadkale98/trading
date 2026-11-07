# Signal study: train (2016-01-01 → 2022-12-31)

No stops or exits: the entry signal alone. `vs_pool` = flagged stocks minus the average eligible stock that day; `t_vs_pool_adj` is a rough correction for overlapping holding windows.

| strategy | horizon_days | signal_days | signals | vs_pool | t_vs_pool | vs_spy | t_vs_spy | beat_spy_rate | t_vs_pool_adj |
|---|---|---|---|---|---|---|---|---|---|
| accumulation | 5 | 1555 | 294797 | -0.13% | -1.16 | -0.14% | -3.27 | 49% | -0.52 |
| accumulation | 20 | 1540 | 292523 | -0.23% | -1.81 | -0.39% | -5.79 | 47% | -0.4 |
| accumulation | 60 | 1500 | 290082 | +0.19% | 1.24 | -0.49% | -4.31 | 47% | 0.16 |
| earnings_gap_up | 5 | 1007 | 4766 | +0.07% | 0.3 | +0.04% | 0.2 | 49% | 0.14 |
| earnings_gap_up | 20 | 999 | 4754 | -0.05% | -0.14 | -0.31% | -0.93 | 47% | -0.03 |
| earnings_gap_up | 60 | 974 | 4633 | +1.17% | 2.06 | +0.11% | 0.18 | 46% | 0.27 |
| earnings_overreaction | 5 | 251 | 383 | -0.08% | -0.19 | -0.34% | -0.76 | 47% | -0.09 |
| earnings_overreaction | 20 | 251 | 383 | -1.02% | -1.21 | -1.55% | -1.77 | 44% | -0.27 |
| earnings_overreaction | 60 | 238 | 361 | +0.92% | 0.58 | -0.57% | -0.34 | 45% | 0.08 |
| relative_strength | 5 | 1504 | 170588 | -0.13% | -1.03 | -0.14% | -2.13 | 48% | -0.46 |
| relative_strength | 20 | 1489 | 168296 | +0.13% | 0.87 | -0.06% | -0.51 | 47% | 0.2 |
| relative_strength | 60 | 1449 | 163416 | +1.47% | 8.18 | +0.78% | 3.75 | 47% | 1.06 |
| return_to_average | 5 | 1570 | 63291 | -0.26% | -1.85 | -0.27% | -2.34 | 47% | -0.83 |
| return_to_average | 20 | 1555 | 62718 | -0.04% | -0.17 | -0.21% | -0.97 | 45% | -0.04 |
| return_to_average | 60 | 1515 | 62065 | -0.18% | -0.59 | -0.84% | -2.22 | 42% | -0.08 |
