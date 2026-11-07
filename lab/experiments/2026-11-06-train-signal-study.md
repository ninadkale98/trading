# Signal study: train (2016-01-01 → 2022-12-31)

No stops or exits: the entry signal alone. `vs_pool` = flagged stocks minus the average eligible stock that day; `t_vs_pool_adj` is a rough correction for overlapping holding windows.

| strategy | horizon_days | signal_days | signals | vs_pool | t_vs_pool | vs_spy | t_vs_spy | beat_spy_rate | t_vs_pool_adj |
|---|---|---|---|---|---|---|---|---|---|
| insider_cluster | 5 | 1632 | 13824 | +0.11% | 1.12 | +0.10% | 1.4 | 51% | 0.5 |
| insider_cluster | 20 | 1617 | 13735 | +0.36% | 2.64 | +0.25% | 1.82 | 50% | 0.59 |
| insider_cluster | 60 | 1577 | 13445 | +1.06% | 4.99 | +0.61% | 2.58 | 50% | 0.64 |
