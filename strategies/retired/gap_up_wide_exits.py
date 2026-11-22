"""Earnings gap-up entry (same as earnings_gap_up) with wide 20% stop/trail exits to test if tight exits caused the losses."""
import numpy as np

from core.backtest.engine import Signal
from core.strategy.base import FeatureStrategy, earnings_clear


class GapUpWideExits(FeatureStrategy):
    name = "gap_up_wide_exits"
    version = "1"
    description = ("Buys the day after a strong earnings reaction (stock beat SPY by >= 5% on the report day, volume >= 2x normal, "
                   "uptrend score >= 3). Same entry and ranking as earnings_gap_up, but exits are wide: 20% initial stop, "
                   "20% trailing stop from the highest close, sell when the next report is within 3 days, max hold 55 trading days.")
    hypothesis = ("earnings_gap_up lost money with tight 2-ATR stops and a 12% trail, while react_drift_momentum with 20% exits "
                  "made money. After a big beat, short-term traders take profit in the first 1-2 weeks while slower funds keep "
                  "buying for 1-3 months. Tight stops sell at the bottom of that wobble. Wider exits should let the drift pay. "
                  "PROVEN WRONG if excess per trade < +0.53%, t_excess < 1.0, excess without best year <= +0.2%, or t_vs_twin < 1.0.")
    min_adv = 1_000_000
    max_new_per_day = 3
    holds_through_earnings = False
    params = {"min_reaction": 0.05, "reaction_cap": 0.25, "min_rvol": 2.0, "min_trend": 3,
              "stop": 0.20, "trail": 0.20, "max_hold": 55, "exit_days_to_earn": 3}

    def eligible(self, t):
        return super().eligible(t) & earnings_clear(self.f, t)

    def score(self, t):
        p = self.params
        react = self.f["earnings_reaction"][t]
        with np.errstate(invalid="ignore"):
            ok = ((self.f["days_since_earnings"][t] == 0) & (react >= p["min_reaction"])
                  & (self.f["rvol"][t] >= p["min_rvol"]) & (self.f["trend_score"][t] >= p["min_trend"]))
        rs = np.nan_to_num(self.f["rs_rank"][t]) / 1000.0
        return np.where(ok, np.minimum(react, p["reaction_cap"]) + rs, np.nan)

    def plan(self, t, j):
        c = self.m.close[t, j]
        p = self.params
        return Signal(self.m.symbols[j], stop=c * (1 - p["stop"]), target=None, trail_pct=p["trail"],
                      max_hold=p["max_hold"], tag=self.name)

    def exits(self, t, m, held):
        d = self.f["days_to_earnings_est"][t]
        idx = {s: i for i, s in enumerate(self.m.symbols)}
        out = []
        for s in held:
            i = idx.get(s)
            if i is None:
                continue
            v = d[i]
            if v == v and v <= self.params["exit_days_to_earn"]:
                out.append(s)
        return out

    def why(self, t, j):
        return "earnings gap-up %.1f%% vs SPY, rvol %.1f" % (100 * self.f["earnings_reaction"][t][j], self.f["rvol"][t][j])
