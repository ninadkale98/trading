"""Idea-lab evaluation (architecture §9, build plan 1.9 / 2.2): run a strategy on a period, compare it with its random
twin and with SPY, apply the stage gates, record everything.

Measures that matter for multi-week stock picking:
  • excess return per trade = trade return − SPY's return over the same days (did the PICK beat just owning SPY?)
  • vs random twin = same number of picks per day, random stocks from the same pool, same exits
    (did the SELECTION add anything beyond the exit rules and market drift?)
  • with SPY sleeve = account return if money not in picks sits in SPY (how the live system holds idle cash, §10.3)

Gates for the TRAIN period (fixed before results are seen):
  1. ≥ 100 trades
  2. average excess return per trade > 0 with t ≥ the multiple-testing bar (rises with every backtest ever run)
  3. beats the random twin per trade (difference > 0, t ≥ 2)
  4. positive average excess in ≥ 60% of years that have ≥ 10 trades, with at least 4 such years
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from core.backtest.data import Market
from core.backtest.engine import Config, run
from core.backtest.metrics import PERIODS, record, summarize, tests_run
from core.log import event


def slice_market(m: Market, start: str, end: str) -> Market:
    """The part of a loaded Market between start and end, features included (they were computed with full lookback)."""
    idx = np.flatnonzero((m.dates >= pd.Timestamp(start)) & (m.dates <= pd.Timestamp(end)))
    a, b = idx[0], idx[-1] + 1
    arrays = [x[a:b] for x in (m.open, m.high, m.low, m.close, m.volume, m.dollar_volume)]
    has = ~np.isnan(arrays[3])
    last = np.full(len(m.symbols), -1, dtype=np.int64)
    any_ = has.any(axis=0)
    last[any_] = (b - a) - 1 - np.argmax(has[::-1, any_], axis=0)
    s = Market(m.dates[a:b], m.symbols, *arrays, last_index=last)
    for attr in ("is_common", "sector"):
        if hasattr(m, attr):
            setattr(s, attr, getattr(m, attr))
    if hasattr(m, "f"):
        s.f = {k: v[a:b] for k, v in m.f.items()}
    return s


def t_required(n_tests: int) -> float:
    """Multiple-testing bar: the best of N random tries typically reaches t ≈ √(2 ln N). Never below 2."""
    return max(2.0, math.sqrt(2 * math.log(max(n_tests, 1))))


def _tstat(x: pd.Series) -> float:
    x = x.dropna()
    return float(x.mean() / (x.std(ddof=1) / math.sqrt(len(x)))) if len(x) > 2 and x.std(ddof=1) > 0 else 0.0


def add_excess(trades: pd.DataFrame, m: Market) -> pd.DataFrame:
    if trades.empty:
        return trades
    spy_o, spy_c = m.open[:, m.col("SPY")], m.close[:, m.col("SPY")]
    pos = {d: i for i, d in enumerate(m.dates)}
    spy_ret = [spy_c[pos[x]] / spy_o[pos[e]] - 1 for e, x in zip(trades["entry_date"], trades["exit_date"])]
    return trades.assign(spy_ret=spy_ret, excess=trades["ret"] - np.array(spy_ret))


def sleeve_curve(res, m: Market) -> pd.Series:
    """Account value if idle money sits in SPY: each day, picks earn their return and the uninvested share earns SPY's."""
    eq = res.equity
    r = eq.pct_change().fillna(0.0)
    spy = pd.Series(m.close[:, m.col("SPY")], index=m.dates).pct_change().fillna(0.0)
    idle = (1 - res.exposure.shift(1).fillna(0.0)).clip(0, 1)
    cash_share = idle  # strategy return already includes its own invested part; add SPY on the idle part
    return (1 + r + cash_share * spy).cumprod() * eq.iloc[0]


@dataclass
class Report:
    strategy: str
    period: str
    metrics: dict
    twin: dict
    by_year: pd.DataFrame
    gates: dict
    passed: bool
    run_id: int | None
    trades: pd.DataFrame


def evaluate(strategy, m: Market, period: str = "train", twin_seeds=(1, 2, 3), save: bool = True,
             allow_holdout: bool = False, notes: str = "") -> Report:
    if period == "holdout" and not allow_holdout:
        raise PermissionError("The holdout period (2025–2026) is used once, at promotion. Pass allow_holdout=True deliberately.")
    start, end = PERIODS[period]
    pm = slice_market(m, start, end)
    sector_of = dict(zip(pm.symbols, getattr(pm, "sector", [None] * len(pm.symbols))))
    cfg = Config(sector_of=sector_of)

    res = run(strategy, pm, cfg)
    met = summarize(res, pm)
    tr = add_excess(res.trades, pm)
    sleeve = sleeve_curve(res, pm)
    spy_total = met.get("benchmark_return", np.nan)
    met.update({
        "avg_excess": float(tr["excess"].mean()) if len(tr) else None,
        "t_excess": _tstat(tr["excess"]) if len(tr) else None,
        "sleeve_return": float(sleeve.iloc[-1] / sleeve.iloc[0] - 1),
        "sleeve_vs_spy": float(sleeve.iloc[-1] / sleeve.iloc[0] - 1 - spy_total) if np.isfinite(spy_total) else None,
    })

    twins = []
    from core.strategy.base import RandomTwin
    for seed in twin_seeds:
        tw = RandomTwin(strategy, seed=seed)
        tres = run(tw, pm, cfg)
        ttr = add_excess(tres.trades, pm)
        twins.append(ttr.assign(seed=seed))
    twin_tr = pd.concat(twins) if twins else pd.DataFrame()
    twin = {"trades_per_run": len(twin_tr) / max(len(twin_seeds), 1),
            "avg_excess": float(twin_tr["excess"].mean()) if len(twin_tr) else None,
            "win_rate": float((twin_tr["pnl"] > 0).mean()) if len(twin_tr) else None}

    by_year = pd.DataFrame()
    if len(tr):
        by_year = tr.assign(year=pd.to_datetime(tr["entry_date"]).dt.year).groupby("year").agg(
            trades=("ret", "size"), win_rate=("pnl", lambda x: float((x > 0).mean())),
            avg_ret=("ret", "mean"), avg_excess=("excess", "mean"))

    n_tests = tests_run() + 1
    t_bar = t_required(n_tests)
    diff = None
    t_diff = 0.0
    if len(tr) and len(twin_tr):
        diff = float(tr["excess"].mean() - twin_tr["excess"].mean())
        se = math.sqrt(tr["excess"].var(ddof=1) / len(tr) + twin_tr["excess"].var(ddof=1) / len(twin_tr))
        t_diff = diff / se if se > 0 else 0.0
    yrs = by_year[by_year["trades"] >= 10] if len(by_year) else by_year
    good_years = float((yrs["avg_excess"] > 0).mean()) if len(yrs) else 0.0
    gates = {
        "enough_trades": {"ok": met.get("trades", 0) >= 100, "value": met.get("trades", 0), "need": "≥ 100"},
        "beats_spy_per_trade": {"ok": bool(len(tr)) and met["avg_excess"] > 0 and met["t_excess"] >= t_bar,
                                "value": f"{(met['avg_excess'] or 0):+.2%} (t {met['t_excess'] or 0:.2f})",
                                "need": f"> 0 with t ≥ {t_bar:.2f} ({n_tests} backtests run so far)"},
        "beats_random_twin": {"ok": diff is not None and diff > 0 and t_diff >= 2.0,
                              "value": f"{(diff or 0):+.2%} per trade (t {t_diff:.2f})", "need": "> 0 with t ≥ 2"},
        # ≥ 4 years with ≥ 10 trades each: "100% of 2 years" is not evidence (lab round 1)
        "works_most_years": {"ok": len(yrs) >= 4 and good_years >= 0.6,
                             "value": f"{good_years:.0%} of {len(yrs)} years" if len(yrs) >= 4 else
                                      f"insufficient data ({len(yrs)} years with ≥ 10 trades)",
                             "need": "≥ 60% of ≥ 4 years"},
    }
    passed = all(g["ok"] for g in gates.values())
    met.update({"twin": twin, "gates": gates, "passed": passed, "excess_vs_twin": diff, "t_vs_twin": t_diff,
                "by_year": by_year.reset_index().to_dict("records") if len(by_year) else []})
    run_id = record(strategy, period, met, notes) if save else None
    if period == "holdout":
        event("lab", f"HOLDOUT used for {strategy.name} v{strategy.version}", level="warn")
    return Report(strategy.name, period, met, twin, by_year, gates, passed, run_id, tr)


def report_md(rep: Report, strategy) -> str:
    m = rep.metrics
    pct = lambda v: "—" if v is None or (isinstance(v, float) and not np.isfinite(v)) else f"{v:+.1%}"  # noqa: E731
    lines = [f"## {strategy.name} v{strategy.version}, {rep.period} ({m['start']} → {m['end']})", "",
             f"**Idea:** {strategy.description}", "", f"**Why it might work (written before testing):** {strategy.hypothesis}", "",
             "| Measure | Strategy | Random twin |", "|---|---|---|",
             f"| Trades | {m.get('trades', 0)} | {rep.twin['trades_per_run']:.0f} per run |",
             f"| Win rate | {pct(m.get('win_rate'))} | {pct(rep.twin['win_rate'])} |",
             f"| Average return per trade | {pct(m.get('expectancy'))} | |",
             f"| **Average excess vs SPY per trade** | **{pct(m.get('avg_excess'))}** (t {m.get('t_excess') or 0:.2f}) | {pct(rep.twin['avg_excess'])} |",
             f"| Average win / loss | {pct(m.get('avg_win'))} / {pct(m.get('avg_loss'))} | |",
             f"| Average hold | {m.get('avg_hold_days', 0):.0f} trading days | |",
             f"| Account return (picks only, idle cash) | {pct(m.get('total_return'))} | |",
             f"| Account return with SPY sleeve | {pct(m.get('sleeve_return'))} | |",
             f"| SPY over the same period | {pct(m.get('benchmark_return'))} | |",
             f"| Worst drop (picks only) | {pct(m.get('max_drawdown'))} | |", "",
             "| Gate | Result | Needed | |", "|---|---|---|---|"]
    for k, g in rep.gates.items():
        lines.append(f"| {k.replace('_', ' ')} | {g['value']} | {g['need']} | {'✅' if g['ok'] else '❌'} |")
    lines += ["", f"**Verdict: {'PASSED the train gates → validate on 2023–2024' if rep.passed else 'did not pass'}**", ""]
    if len(rep.by_year):
        lines += ["| Year | Trades | Win rate | Avg return | Avg excess vs SPY |", "|---|---|---|---|---|"]
        for y, r in rep.by_year.iterrows():
            lines.append(f"| {y} | {int(r.trades)} | {r.win_rate:.0%} | {r.avg_ret:+.2%} | {r.avg_excess:+.2%} |")
    lines += ["", f"Exit reasons: {m.get('exit_reasons', {})}", f"Run id: {rep.run_id}", ""]
    return "\n".join(lines)
