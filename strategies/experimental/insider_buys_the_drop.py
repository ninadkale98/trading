"""Insider buying that newly appears within weeks after a stock was punished on its earnings report."""
import numpy as np

from core.backtest.engine import Signal
from core.strategy.base import FeatureStrategy, earnings_clear


class InsiderBuysTheDrop(FeatureStrategy):
    name = "insider_buys_the_drop"
    version = "1"
    description = ("The last earnings reaction lagged SPY by at least 5%, it is 2-40 trading days after the report, and a new "
                   "insider buyer was reported in the last 5 trading days (net insider buying positive). Company worth "
                   ">= $500M, trading >= $2M/day, next report more than 20 days away. First qualifying day per report only. "
                   "Hold up to 80 trading days with a 25% stop, through the next report.")
    hypothesis = ("After a bad earnings reaction outside investors sell the headline. An insider buying in the window right "
                  "after a bad quarter carries career and legal risk, so it is direct evidence that people who know the "
                  "business think the reaction overshot.")
    needs_fundamentals = True
    holds_through_earnings = True
    min_adv = 2_000_000
    max_new_per_day = 3
    params = {"react": -0.05, "dse_min": 2, "dse_max": 40, "lag": 5, "min_mcap": 5e8,
              "min_days_to_earn": 20, "stop": 0.25, "max_hold": 80, "max_buyers": 4}

    def helper_trigger(self, t):
        p = self.params
        lag = p["lag"]
        n = len(self.m.symbols)
        if t < lag:
            return np.zeros(n, dtype=bool)
        dse = self.f["days_since_earnings"][t]
        now = self.f["insider_buyers_90d"][t]
        before = self.f["insider_buyers_90d"][t - lag]
        with np.errstate(invalid="ignore"):
            ok = ((self.f["earnings_reaction"][t] <= p["react"]) & (dse >= p["dse_min"]) & (dse <= p["dse_max"])
                  & (now > np.nan_to_num(before)) & (self.f["insider_net_buy_90d"][t] > 0))
        return ok

    def eligible(self, t):
        p = self.params
        with np.errstate(invalid="ignore"):
            base = (super().eligible(t) & (self.f["market_cap"][t] >= p["min_mcap"])
                    & (self.f["adv20"][t] >= self.min_adv)
                    & (self.f["days_to_earnings_est"][t] > p["min_days_to_earn"]))
        return base

    def score(self, t):
        p = self.params
        n = len(self.m.symbols)
        ok = self.helper_trigger(t) & self.eligible(t)
        if not ok.any():
            return np.full(n, np.nan)
        dse = self.f["days_since_earnings"][t]
        # first trigger day per report: no trigger on earlier days of the same report
        for k in range(1, min(p["dse_max"], t) + 1):
            prev = self.helper_trigger(t - k)
            with np.errstate(invalid="ignore"):
                same = (self.f["days_since_earnings"][t - k] == dse - k)
            ok = ok & ~(prev & same)
        buyers = np.minimum(np.nan_to_num(self.f["insider_buyers_90d"][t]), p["max_buyers"])
        val = np.nan_to_num(self.f["insider_net_buy_90d"][t]) * buyers
        return np.where(ok, val, np.nan)

    def plan(self, t, j):
        c = self.m.close[t, j]
        return Signal(self.m.symbols[j], stop=c * (1 - self.params["stop"]), max_hold=self.params["max_hold"], tag=self.name)
