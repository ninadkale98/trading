"""Buy a steadily-huge, most-traded stock after a 25%+ crash from its 60-day high with heavy selling; hold 120 days."""
import numpy as np

from core.backtest.engine import Signal
from core.strategy.base import FeatureStrategy


class BigCrashCapitulation(FeatureStrategy):
    name = "big_crash_capitulation"
    version = "1"
    description = ("A company that has been among the 100 most traded stocks at least 95% of the last 250 days, "
                   "ranks in the top 20 by dollar volume, is 25%+ below its 60-day high, and had a heavy-volume "
                   "selling day in the last 5 trading days. One event per crash (skipped if it qualified in the "
                   "previous 60 days). Earnings ignored. Hold 120 trading days with a wide 35% stop.")
    hypothesis = ("The most consistently traded US companies are rarely broken by a single crash. When one falls 25%+ "
                  "from its 60-day high with a heavy-volume selling day, the sellers are often forced or "
                  "risk-driven (funds cutting losers, margin calls, mandate exits) rather than informed. "
                  "Long-horizon buyers and buyback capacity absorb this over months. Pre-test: +9.3% vs SPY over "
                  "120 days, but events cluster in 2020 and 2022, so it must hold up out of sample.")
    needs_fundamentals = False
    min_adv = 1_000_000
    max_new_per_day = 3
    holds_through_earnings = True
    params = {"min_steady": 0.95, "max_rank": 20, "min_drop": -0.25, "heavy_age": 5,
              "dedupe_days": 60, "stop": 0.35, "max_hold": 120}

    def helper_base(self, t, idx=None):
        p = self.params
        a = self.f["big_steady_250"][t]
        b = self.f["adv_rank"][t]
        c = self.f["dist_60d_high"][t]
        d = self.f["heavy_sell_age"][t]
        if idx is not None:
            a, b, c, d = a[idx], b[idx], c[idx], d[idx]
        with np.errstate(invalid="ignore"):
            return ((a >= p["min_steady"]) & (b <= p["max_rank"]) &
                    (c <= p["min_drop"]) & (d <= p["heavy_age"]))

    def eligible(self, t):
        return super().eligible(t)

    def score(self, t):
        n = len(self.m.symbols)
        out = np.full(n, np.nan)
        ok = self.helper_base(t) & self.eligible(t)
        idx = np.where(ok)[0]
        if len(idx) == 0:
            return out
        keep = np.ones(len(idx), dtype=bool)
        for k in range(1, self.params["dedupe_days"] + 1):
            if t - k < 0:
                break
            keep &= ~self.helper_base(t - k, idx)
            if not keep.any():
                return out
        sel = idx[keep]
        dist = self.f["dist_60d_high"][t][sel]
        rank = self.f["adv_rank"][t][sel]
        out[sel] = -dist * 100 - np.nan_to_num(rank, nan=100.0) * 1e-3
        return out

    def plan(self, t, j):
        c = self.m.close[t, j]
        return Signal(self.m.symbols[j], stop=c * (1 - self.params["stop"]),
                      max_hold=self.params["max_hold"], tag=self.name)
