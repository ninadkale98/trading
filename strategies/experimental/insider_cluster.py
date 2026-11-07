"""Insider cluster buying: several company insiders buying their own stock with their own money."""
import numpy as np

from core.backtest.engine import Signal
from core.strategy.base import FeatureStrategy, earnings_clear


class InsiderCluster(FeatureStrategy):
    name = "insider_cluster"
    version = "1"
    description = ("At least 2 different insiders (executives, directors) bought shares on the open market within 90 days, "
                   "and the count just went up (a new buyer joined in the last 5 trading days). Company worth ≥ $1B, "
                   "trading ≥ $2M/day, no earnings within 2 weeks. Hold up to ~4 months with a wide 20% safety stop.")
    hypothesis = ("Insiders know their company best and buy with their own money for one reason: they expect the price "
                  "to rise. Several insiders buying at once is a stronger, less noisy signal than one. Research: insider "
                  "purchases earned >6%/year above the market, clusters more (learning/12). Effects are smaller in big "
                  "companies, so we require ≥ $1B to stay tradable.")
    needs_fundamentals = True
    min_adv = 2_000_000
    max_new_per_day = 3
    params = {"min_buyers": 2, "fresh_days": 5, "min_mcap": 1e9, "stop": 0.20, "max_hold": 80}

    def eligible(self, t):
        return super().eligible(t) & earnings_clear(self.f, t)

    def score(self, t):
        p = self.params
        if t < p["fresh_days"]:
            return np.full(len(self.m.symbols), np.nan)
        now, before = self.f["insider_buyers_90d"][t], self.f["insider_buyers_90d"][t - p["fresh_days"]]
        with np.errstate(invalid="ignore"):
            ok = (now >= p["min_buyers"]) & (now > np.nan_to_num(before)) & (self.f["market_cap"][t] >= p["min_mcap"])
        return np.where(ok, now + np.nan_to_num(self.f["insider_net_buy_90d"][t]) * 100, np.nan)

    def plan(self, t, j):
        c = self.m.close[t, j]
        return Signal(self.m.symbols[j], stop=c * (1 - self.params["stop"]), max_hold=self.params["max_hold"], tag=self.name)
