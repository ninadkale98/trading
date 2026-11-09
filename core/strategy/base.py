"""Strategy plug-in interface (architecture §8). The SAME class runs in backtests and live:

  • `prepare(m)` gets features for the whole Market (computed by core/features, or precomputed and attached as `m.f`)
  • `eligible(t)` → which stocks may be traded that day (common stock, price ≥ $5, liquid enough, has data)
  • `score(t)`    → NaN = not a candidate; higher = better candidate
  • `plan(t, j)`  → how to trade a pick: entry, stop, target, trailing stop, max holding time

The engine (core/backtest/engine.py) asks `signals(t, …)` at each close; live trading (Phase 2.4) asks the same
methods for the latest day and turns picks into Candidates for the planner.
Strategy files live in strategies/{experimental,paper,promoted,retired}/ and subclass FeatureStrategy.
"""
from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from core.backtest.engine import Signal, Strategy
from core.config import ROOT, limits

STAGES = ("experimental", "paper", "promoted", "retired")


@dataclass
class Candidate:
    """A live pick for the planner: what to buy, how, and why."""
    strategy: str
    symbol: str
    date: str
    score: float
    entry: str
    limit: float | None
    stop: float
    target: float | None
    trail_pct: float | None
    max_hold: int | None
    rationale: str
    facts: dict = field(default_factory=dict)


class FeatureStrategy(Strategy):
    name = "base"
    version = "1"
    stage = "experimental"
    description = ""           # plain language: what it looks for
    hypothesis = ""            # why it might work (written BEFORE testing)
    max_new_per_day = 3
    min_price = 5.0
    min_adv = 1_000_000        # thin tier and above (architecture §3)
    needs_fundamentals = False
    holds_through_earnings = False   # False → open positions are sold before the company reports (architecture §10.6)
    params: dict = {}

    # ── data ──────────────────────────────────────────────────────────────────────────────────────────────
    def prepare(self, m) -> None:
        f = getattr(m, "f", None)
        if f is None:
            from core.features.build import features_for_market
            f = features_for_market(m, fundamentals_too=self.needs_fundamentals)
        self.m, self.f = m, f
        self.common = getattr(m, "is_common", np.ones(len(m.symbols), dtype=bool))
        self.sector = getattr(m, "sector", np.array([None] * len(m.symbols), dtype=object))

    def x(self, name: str, t: int) -> np.ndarray:
        return self.f[name][t]

    # ── the three methods each strategy fills in ───────────────────────────────────────────────────────────
    def eligible(self, t: int) -> np.ndarray:
        c = self.m.close[t]
        with np.errstate(invalid="ignore"):
            return self.common & np.isfinite(c) & (c >= self.min_price) & (self.x("adv20", t) >= self.min_adv)

    def score(self, t: int) -> np.ndarray:
        raise NotImplementedError

    def plan(self, t: int, j: int) -> Signal:
        raise NotImplementedError

    def why(self, t: int, j: int) -> str:
        return self.description

    # ── engine hooks ───────────────────────────────────────────────────────────────────────────────────────
    def picks(self, t: int, held: set[str]) -> list[int]:
        s = np.where(self.eligible(t), self.score(t), np.nan)
        order = [j for j in np.argsort(-np.nan_to_num(s, nan=-np.inf)) if np.isfinite(s[j])]
        return [j for j in order if self.m.symbols[j] not in held][: self.max_new_per_day]

    def signals(self, t: int, m, held: set[str]) -> list[Signal]:
        return [self.plan(t, j) for j in self.picks(t, held)]

    def candidates(self, t: int, held: set[str] = frozenset()) -> list[Candidate]:
        out = []
        s = self.score(t)
        for j in self.picks(t, set(held)):
            sig = self.plan(t, j)
            out.append(Candidate(self.name, self.m.symbols[j], str(self.m.dates[t].date()), float(s[j]), sig.entry,
                                 sig.limit, float(sig.stop), sig.target, sig.trail_pct, sig.max_hold, self.why(t, j),
                                 {k: _num(self.f[k][t, j]) for k in self.facts_to_show() if k in self.f}))
        return out

    def facts_to_show(self) -> list[str]:
        return ["close", "ret_20d", "rs_rank", "trend_score", "rsi14", "dist_sma50", "days_to_earnings_est"]


def _num(v):
    v = float(v)
    return None if not np.isfinite(v) else round(v, 4)


def atr_stop(price: float, atr_pct: float, mult: float = 2.0, floor: float = 0.04, cap: float = 0.15) -> float:
    """Stop below the entry at `mult` × the stock's normal daily range, kept between 4% and 15% below."""
    dist = min(max(mult * (atr_pct if np.isfinite(atr_pct) else 0.03), floor), cap)
    return price * (1 - dist)


def earnings_clear(f, t: int, days: int = 14) -> np.ndarray:
    """Entry filter (architecture §10.4): True where no report is due within ~10 trading days (14 calendar days)."""
    d = f["days_to_earnings_est"][t]
    with np.errstate(invalid="ignore"):
        return ~(np.isfinite(d) & (d >= 0) & (d <= days))


class RandomTwin(FeatureStrategy):
    """Fairness check: picks the same NUMBER of stocks per day as `inner`, at random from the same eligible pool,
    and trades them with the same plan (stops, targets, holding time). If the real strategy can't beat its random
    twin, its 'edge' is just the market or the exit rules."""

    def __init__(self, inner: FeatureStrategy, seed: int = 0):
        self.inner, self.rng = inner, np.random.default_rng(seed)
        self.name, self.version = f"{inner.name}.random_twin", inner.version
        self.params = {"twin_of": inner.name, "seed": seed}
        self.max_new_per_day = inner.max_new_per_day

    def prepare(self, m) -> None:
        self.inner.prepare(m)
        self.m, self.f = m, self.inner.f

    def picks(self, t, held):
        n = len(self.inner.picks(t, held))
        if not n:
            return []
        pool = [j for j in np.flatnonzero(self.inner.eligible(t)) if self.m.symbols[j] not in held]
        return list(self.rng.choice(pool, size=min(n, len(pool)), replace=False)) if pool else []

    def plan(self, t, j):
        sig = self.inner.plan(t, j)
        sig.tag = "random"
        return sig

    def exits(self, t, m, held):
        return self.inner.exits(t, m, held)


def load_file(path: Path, stage: str = "experimental") -> list[type]:
    """Import one strategy file and return its FeatureStrategy subclasses (each instance gets `.stage`)."""
    spec = importlib.util.spec_from_file_location(f"strategies.{stage}.{path.stem}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return [obj for obj in vars(mod).values()
            if isinstance(obj, type) and issubclass(obj, FeatureStrategy) and obj not in (FeatureStrategy, RandomTwin)
            and obj.__module__ == mod.__name__]


def load(stage: str | None = None) -> list[FeatureStrategy]:
    """Import every strategy file under strategies/<stage>/ (all non-retired stages if None). A file that fails to
    import is skipped and reported, so one broken strategy never stops the planner."""
    from core.log import event
    out = []
    stages = [stage] if stage else [s for s in STAGES if s != "retired"]
    for st in stages:
        for path in sorted((ROOT / "strategies" / st).glob("*.py")):
            if path.name.startswith("_"):
                continue
            try:
                classes = load_file(path, st)
            except Exception as e:                       # noqa: BLE001
                event("strategy", f"could not load {st}/{path.name}: {e}", level="error")
                continue
            for obj in classes:
                inst = obj()
                inst.stage = st
                out.append(inst)
    return out


def risk_budget(stage: str) -> float:
    """Unproven strategies risk less per trade (architecture §10.5)."""
    L = limits()
    return L["normal_risk_per_trade_min"] if stage in ("experimental", "paper") else L["normal_risk_per_trade_max"]
