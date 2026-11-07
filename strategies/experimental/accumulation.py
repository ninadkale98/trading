"""Accumulation: steady buying (more volume on up days than down days) near the highs."""
import numpy as np

from core.backtest.engine import Signal
from core.strategy.base import FeatureStrategy, atr_stop, earnings_clear


class Accumulation(FeatureStrategy):
    name = "accumulation"
    version = "1"
    description = ("Over the last 50 and 20 days, clearly more volume on up days than down days (accumulation ≥ 0.15 and "
                   "≥ 0.10), price within 10% of its 52-week high and above its 50-day average, not already up more than "
                   "40% in 3 months. Strongest accumulation first. Trailing stop, hold up to 3 months.")
    hypothesis = ("Big investors build positions over weeks and can't hide the volume: persistent up-day volume can "
                  "reveal buying before the price fully reflects it.")
    min_adv = 5_000_000
    params = {"acc50": 0.15, "acc20": 0.10, "near_high": -0.10, "max_ret60": 0.40, "stop_atr": 2.5, "trail": 0.12, "max_hold": 60}

    def eligible(self, t):
        return super().eligible(t) & earnings_clear(self.f, t)

    def score(self, t):
        x, p = lambda k: self.x(k, t), self.params
        with np.errstate(invalid="ignore"):
            ok = ((x("accum_50") >= p["acc50"]) & (x("accum_20") >= p["acc20"]) & (x("dist_52w_high") >= p["near_high"])
                  & (x("dist_sma50") > 0) & (x("ret_60d") <= p["max_ret60"]))
        return np.where(ok, x("accum_50"), np.nan)

    def plan(self, t, j):
        c = self.m.close[t, j]
        return Signal(self.m.symbols[j], stop=atr_stop(c, self.x("atr_pct", t)[j], self.params["stop_atr"]),
                      trail_pct=self.params["trail"], max_hold=self.params["max_hold"], tag=self.name)
