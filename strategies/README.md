# Strategies (architecture §8–9)

One file per idea, subclassing `core.strategy.base.FeatureStrategy`. The folder is the stage:

| Folder | Meaning |
|---|---|
| `experimental/` | New idea, being backtested. AI-written ideas also land here (Phase 4). |
| `paper/` | Passed train + validation gates; proving itself in paper trading with a small risk budget |
| `promoted/` | Proved itself live; normal risk budget |
| `retired/` | Stopped working or failed; kept so nobody retries it blindly |

Every backtest is recorded in `backtest_runs` (multiple-testing counter). Results are written to `lab/experiments/`.
Run the lab: `.venv/bin/python -m core.lab.run --period train` (see `core/lab/run.py`).
