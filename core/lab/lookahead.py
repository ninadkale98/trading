"""Look-ahead checks: a strategy or feature must give the SAME answer for day t whether or not the days after t exist.

This is the most important guard of a self-improving lab: code that peeks at the future makes fake winners that
pass every backtest gate and then fail live. Two checks:
  • check_strategy: run the strategy on the full market and on the market cut off at day t; scores, eligibility and
    trade plans for day t must match.
  • check_features: recompute every feature from prices cut off at day t; values for day t must match.
"""
from __future__ import annotations

import numpy as np

from core.lab.evaluate import slice_market


def _same(a, b, tol=1e-9) -> bool:
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    if a.shape != b.shape:
        return False
    both_nan = np.isnan(a) & np.isnan(b)
    with np.errstate(invalid="ignore"):
        close = np.isclose(a, b, rtol=tol, atol=tol)
    return bool(np.all(both_nan | close))


def check_strategy(make, m, days: list[int]) -> list[str]:
    """`make()` returns a fresh strategy instance. Returns a list of problems (empty = no look-ahead found)."""
    full = make()
    full.prepare(m)
    problems = []
    for t in days:
        cut = slice_market(m, str(m.dates[0].date()), str(m.dates[t].date()))
        s = make()
        s.prepare(cut)
        tc = len(cut.dates) - 1
        if not _same(full.eligible(t), s.eligible(tc)):
            problems.append(f"{m.dates[t].date()}: eligible() changes when later days are removed")
        sf, sc = full.score(t), s.score(tc)
        if not _same(sf, sc):
            n = int(np.sum(~(np.isclose(np.nan_to_num(sf, nan=-9e9), np.nan_to_num(sc, nan=-9e9)))))
            problems.append(f"{m.dates[t].date()}: score() differs for {n} stocks when later days are removed")
            continue
        for j in full.picks(t, set())[:3]:
            a, b = full.plan(t, j), s.plan(tc, j)
            for k in ("stop", "limit", "target", "trail_pct", "max_hold"):
                va, vb = getattr(a, k), getattr(b, k)
                if (va is None) != (vb is None) or (va is not None and not _same(va, vb)):
                    problems.append(f"{m.dates[t].date()}: plan().{k} for {m.symbols[j]} differs when later days are removed")
    return problems


def check_features(m, days: list[int], fundamentals_too: bool = False) -> list[str]:
    """Recompute features from a market cut off at each day; compare with the full-history values."""
    from core.features.build import features_for_market
    raw = slice_market(m, str(m.dates[0].date()), str(m.dates[-1].date()))
    if hasattr(raw, "f"):
        del raw.f
    full = features_for_market(raw, fundamentals_too)
    problems = []
    for t in days:
        cut = slice_market(raw, str(m.dates[0].date()), str(m.dates[t].date()))
        if hasattr(cut, "f"):
            del cut.f
        part = features_for_market(cut, fundamentals_too)
        for k, v in full.items():
            if k not in part:
                problems.append(f"{k}: missing when later days are removed")
            elif not _same(v[t], part[k][-1], tol=1e-6):
                bad = int(np.sum(~np.isclose(np.nan_to_num(v[t], nan=-9e9), np.nan_to_num(part[k][-1], nan=-9e9), rtol=1e-6)))
                problems.append(f"{k} on {m.dates[t].date()}: {bad} stocks differ when later days are removed")
    return problems
