"""Does an entry signal predict anything on its own? (No stops, no position limits, no exits muddying the answer.)

For every day t and every stock a strategy would flag (eligible + finite score), measure the return from the next
open to the close h trading days later, and compare it with:
  • SPY over the same days, and
  • the average eligible stock that day (the pool a random picker would draw from).
Days are the unit of evidence (signals on the same day are not independent), so t-stats are computed on the
per-day average differences.

  .venv/bin/python -m core.lab.signal_study --period train --only relative_strength accumulation
"""
from __future__ import annotations

import argparse
import math
from datetime import date, timedelta

import numpy as np
import pandas as pd

from core.backtest.metrics import PERIODS
from core.config import ROOT
from core.features.build import research_market
from core.lab.evaluate import slice_market
from core.strategy.base import load

HORIZONS = (5, 20, 60)


def forward_returns(m, h: int) -> np.ndarray:
    """Return from the next open to the close h days later; a delisted stock keeps its last price."""
    c = pd.DataFrame(m.close).ffill().to_numpy()
    o = m.open
    T = len(m.dates)
    out = np.full(m.close.shape, np.nan)
    if T > h + 1:
        with np.errstate(divide="ignore", invalid="ignore"):
            out[: T - h - 1] = c[1 + h: T] / o[1: T - h] - 1
    return out


def _t(x: np.ndarray) -> float:
    x = x[np.isfinite(x)]
    return float(x.mean() / (x.std(ddof=1) / math.sqrt(len(x)))) if len(x) > 2 and x.std(ddof=1) > 0 else 0.0


def t_overlap(x: np.ndarray, days: np.ndarray, h: int) -> float:
    """t-stat that allows for overlapping holding windows: two signal days closer than h trading days share part of
    their future returns, so their errors are correlated. Hansen–Hodrick: add the cross-products of every pair of
    signal days less than h apart (equal weights; the overlap itself already shrinks them with distance), falling
    back to Bartlett weights if that comes out negative. Dense daily signals get ~√h deflation; rare, spread-out
    signals barely any. Simulated no-edge data gives t with sd ≈ 1.05–1.1 for both (the old fixed t/√h
    over-penalised rare signals, lab round 1; Bartlett alone was overconfident, sd ≈ 1.3)."""
    ok = np.isfinite(x)
    x, days = x[ok], days[ok]
    n = len(x)
    if n < 3:
        return 0.0
    e = x - x.mean()
    var = varb = float(e @ e)
    for i in range(n):                                   # days are sorted; only neighbours within h matter
        j = i + 1
        while j < n and days[j] - days[i] < h:
            c = 2 * e[i] * e[j]
            var += c
            varb += c * (1 - (days[j] - days[i]) / h)
            j += 1
    v = var if var > 0 else varb
    if v <= 0:
        return 0.0
    return float(x.mean() / (math.sqrt(v) / n))


def study(strategy, m, horizons=HORIZONS, every: int = 1) -> pd.DataFrame:
    """`basis` = which stocks count as the strategy's signal each day: all it flags (eligible + finite score), or, when
    it flags ≥ 90% of the eligible pool (a pure ranking rule), its top 10% by score (at least max_new_per_day). Without
    that switch the 'signal' equals the pool and the comparison is meaningless (lab round 1, rs_wide_leash)."""
    strategy.prepare(m)
    spy = m.col("SPY")
    rows = []
    fwd = {h: forward_returns(m, h) for h in horizons}
    # decide the basis once, from how much of the pool the strategy flags
    sample = range(0, len(m.dates) - 1, max(1, (len(m.dates) - 1) // 40))
    cover = []
    for t in sample:
        el = strategy.eligible(t)
        if el.sum() >= 20:
            cover.append((el & np.isfinite(strategy.score(t))).sum() / el.sum())
    basis = "top_decile" if cover and float(np.median(cover)) >= 0.9 else "flagged"
    k_min = max(int(getattr(strategy, "max_new_per_day", 3)), 1)
    for h in horizons:
        day_vs_pool, day_vs_spy, n_sig, hits, days = [], [], 0, [], []
        for t in range(0, len(m.dates) - h - 1, every):
            el = strategy.eligible(t)
            if not el.any():
                continue
            sc = strategy.score(t)
            sig = el & np.isfinite(sc)
            r = fwd[h][t]
            if basis == "top_decile" and sig.any():
                idx = np.flatnonzero(sig)
                k = max(k_min, len(idx) // 10)
                top = idx[np.argsort(-sc[idx])[:k]]
                sig = np.zeros_like(sig)
                sig[top] = True
            ok_sig, ok_pool = sig & np.isfinite(r), el & np.isfinite(r)
            if not ok_sig.any() or ok_pool.sum() < 20:
                continue
            s_mean, p_mean = r[ok_sig].mean(), r[ok_pool].mean()
            day_vs_pool.append(s_mean - p_mean)
            day_vs_spy.append(s_mean - fwd[h][t, spy])
            hits.append((r[ok_sig] > fwd[h][t, spy]).mean())
            n_sig += int(ok_sig.sum())
            days.append(t)
        a, b, d = np.array(day_vs_pool), np.array(day_vs_spy), np.array(days)
        rows.append({"strategy": strategy.name, "horizon_days": h, "basis": basis, "signal_days": len(a), "signals": n_sig,
                     "vs_pool": float(np.nanmean(a)) if len(a) else np.nan, "t_vs_pool": _t(a),
                     "vs_spy": float(np.nanmean(b)) if len(b) else np.nan, "t_vs_spy": _t(b),
                     "beat_spy_rate": float(np.nanmean(hits)) if hits else np.nan,
                     "t_vs_pool_adj": t_overlap(a, d, h)})
    return pd.DataFrame(rows)


def _md(df: pd.DataFrame) -> str:
    head = "| " + " | ".join(df.columns) + " |\n|" + "---|" * len(df.columns) + "\n"
    return head + "\n".join("| " + " | ".join(str(v) for v in r) + " |" for r in df.itertuples(index=False))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--period", default="train", choices=["train", "validate"])
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--no-fundamentals", action="store_true")
    a = ap.parse_args(argv)
    strategies = [s for s in load("experimental") if not a.only or s.name in a.only]
    start, end = PERIODS[a.period]
    m = research_market(max(date.fromisoformat(start) - timedelta(days=400), date(2016, 1, 1)),
                        min(date.fromisoformat(end), date.today()), fundamentals_too=not a.no_fundamentals)
    pm = slice_market(m, start, end)
    res = pd.concat([study(s, pm) for s in strategies], ignore_index=True)
    pd.set_option("display.width", 200)
    fmt = res.copy()
    for c in ("vs_pool", "vs_spy"):
        fmt[c] = fmt[c].map(lambda v: f"{v:+.2%}")
    fmt["beat_spy_rate"] = fmt["beat_spy_rate"].map(lambda v: f"{v:.0%}")
    for c in ("t_vs_pool", "t_vs_spy", "t_vs_pool_adj"):
        fmt[c] = fmt[c].round(2)
    print(fmt.to_string(index=False))
    path = ROOT / "lab" / "experiments" / f"{date.today()}-{a.period}-signal-study{'-' + '-'.join(a.only) if a.only else ''}.md"
    path.write_text(f"# Signal study: {a.period} ({start} → {end})\n\nNo stops or exits: the entry signal alone. "
                    "`vs_pool` = flagged stocks minus the average eligible stock that day; `t_vs_pool_adj` is a rough "
                    "correction for overlapping holding windows.\n\n" + _md(fmt) + "\n")
    print(f"report: {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
