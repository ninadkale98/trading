"""Backtest metrics + recording (every run is stored → multiple-testing counter)."""
from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd

from core.backtest.data import Market
from core.backtest.engine import Result
from core.db import query

PERIODS = {"train": ("2016-01-01", "2022-12-31"), "validate": ("2023-01-01", "2024-12-31"),
           "holdout": ("2025-01-01", "2099-12-31")}


def summarize(res: Result, m: Market | None = None, benchmark: str = "SPY") -> dict:
    eq = res.equity[res.equity > 0]
    years = max((eq.index[-1] - eq.index[0]).days / 365.25, 1e-9)
    total = eq.iloc[-1] / eq.iloc[0] - 1
    daily = eq.pct_change().dropna()
    dd = (eq / eq.cummax() - 1).min()
    out = {
        "start": str(eq.index[0].date()), "end": str(eq.index[-1].date()),
        "total_return": total, "cagr": (1 + total) ** (1 / years) - 1, "max_drawdown": dd,
        "sharpe": (daily.mean() / daily.std() * math.sqrt(252)) if daily.std() > 0 else 0.0,
        "avg_exposure": float(res.exposure.mean()),
    }
    tr = res.trades
    if len(tr):
        wins, losses = tr[tr.pnl > 0], tr[tr.pnl <= 0]
        r = tr["ret"]
        out.update({
            "trades": int(len(tr)), "win_rate": len(wins) / len(tr),
            "avg_win": float(wins.ret.mean()) if len(wins) else 0.0,
            "avg_loss": float(losses.ret.mean()) if len(losses) else 0.0,
            "expectancy": float(r.mean()),                       # average return per trade (after costs)
            "t_stat": float(r.mean() / (r.std(ddof=1) / math.sqrt(len(r)))) if len(r) > 2 and r.std() > 0 else 0.0,
            "avg_r": float(tr["r_multiple"].mean()) if tr["r_multiple"].notna().any() else None,
            "avg_hold_days": float(tr.hold_days.mean()),
            "exit_reasons": tr.exit_reason.value_counts().to_dict(),
        })
    else:
        out["trades"] = 0
    if m is not None and benchmark in m._cols:
        c = m.close[:, m.col(benchmark)]
        ok = np.where(np.isfinite(c))[0]
        b_total = c[ok[-1]] / c[ok[0]] - 1
        out["benchmark"] = benchmark
        out["benchmark_return"] = float(b_total)
        out["excess_return"] = float(total - b_total)
    return {k: (round(v, 6) if isinstance(v, float) else v) for k, v in out.items()}


def record(strategy, period: str, metrics: dict, notes: str = "") -> int:
    start, end = (PERIODS.get(period) or (metrics["start"], metrics["end"]))
    row = query(
        """INSERT INTO backtest_runs (strategy, version, params, period, start_date, end_date, metrics, notes)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
        (strategy.name, getattr(strategy, "version", None), json.dumps(getattr(strategy, "params", {}), default=str),
         period, metrics["start"], metrics["end"], json.dumps(metrics, default=str), notes),
    )
    return row[0]["id"]


def tests_run(strategy_name: str | None = None) -> int:
    """How many DIFFERENT ideas have been tested (all, or one strategy): the multiple-testing count. Re-running the same
    strategy version with the same parameters (e.g. after a measurement fix) is not a new try, so it isn't counted
    again; any change of version or parameters is."""
    sql = "SELECT count(DISTINCT (strategy, coalesce(version, ''), params::text)) n FROM backtest_runs"
    if strategy_name:
        return query(sql + " WHERE strategy=%s", (strategy_name,))[0]["n"]
    return query(sql)[0]["n"]
