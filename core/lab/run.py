"""Run the idea lab on a period and write a report.

  .venv/bin/python -m core.lab.run --period train                      # every strategy in strategies/experimental
  .venv/bin/python -m core.lab.run --period train --only accumulation
  .venv/bin/python -m core.lab.run --period validate --only quality_pullback

Loads the market once (today's universe + delisted stocks, features attached), then evaluates each strategy against
its random twin and SPY. Every run is recorded in backtest_runs; the report goes to lab/experiments/.
"""
from __future__ import annotations

import argparse
import time
from datetime import date, timedelta

from core.backtest.metrics import PERIODS
from core.config import ROOT
from core.features.build import research_market
from core.lab.evaluate import evaluate, report_md
from core.strategy.base import load


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--period", default="train", choices=["train", "validate", "holdout"])
    ap.add_argument("--stage", default="experimental")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--no-fundamentals", action="store_true")
    ap.add_argument("--allow-holdout", action="store_true")
    ap.add_argument("--notes", default="")
    a = ap.parse_args(argv)

    strategies = [s for s in load(a.stage) if not a.only or s.name in a.only]
    if not strategies:
        print("no strategies matched")
        return 1
    start, end = PERIODS[a.period]
    load_from = date.fromisoformat(start) - timedelta(days=400)        # a year of history for the features
    t0 = time.time()
    m = research_market(max(load_from, date(2016, 1, 1)), min(date.fromisoformat(end), date.today()),
                        fundamentals_too=not a.no_fundamentals)
    print(f"market loaded: {m.close.shape[0]} days × {m.close.shape[1]} symbols in {time.time() - t0:.0f}s")

    out = [f"# Lab run: {a.period} ({start} → {end}), {date.today()}", "",
           "Each strategy is compared with SPY over the same holding days and with a random twin (same number of "
           "picks per day, random stocks from the same pool, same exits). Gates are fixed in core/lab/evaluate.py.",
           "Features need a year of history, so the first months of the period have few or no signals.", ""]
    for s in strategies:
        t1 = time.time()
        rep = evaluate(s, m, a.period, allow_holdout=a.allow_holdout, notes=a.notes)
        md = report_md(rep, s)
        out.append(md)
        mm = rep.metrics
        print(f"{s.name:<24} trades {mm.get('trades', 0):>4}  excess/trade {(mm.get('avg_excess') or 0):+.2%} "
              f"(t {(mm.get('t_excess') or 0):.2f})  vs twin {(mm.get('excess_vs_twin') or 0):+.2%} "
              f"(t {mm.get('t_vs_twin', 0):.2f})  {'PASS' if rep.passed else 'fail'}  [{time.time() - t1:.0f}s]")
    path = ROOT / "lab" / "experiments" / f"{date.today()}-{a.period}{'-' + '-'.join(a.only) if a.only else ''}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out))
    print(f"report: {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
