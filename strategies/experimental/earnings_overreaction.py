"""Earnings overreaction: buy a strong company that sold off hard on earnings, once the selling has stopped."""
import numpy as np

from core.backtest.engine import Signal
from core.strategy.base import FeatureStrategy, atr_stop


class EarningsOverreaction(FeatureStrategy):
    name = "earnings_overreaction"
    version = "1"
    description = ("A stock that was strong before its report (RS rank ≥ 60, still above its 200-day average) fell at least "
                   "8% more than the market on earnings. Wait 3 trading days; buy only if it has held above the "
                   "reaction-day low and is up from the reaction-day close (selling has stopped).")
    hypothesis = ("Sometimes the first reaction to bad news is too big for a good company (QCOM-type rebound). The "
                  "3-day wait and 'held the low' check are meant to skip Intel-type drifts, where bad news keeps getting "
                  "priced in for weeks. Research says drift usually wins, so this one may well fail: that's what the test is for.")
    params = {"max_reaction": -0.08, "min_rs": 60, "wait_days": 3, "stop_below_low": 0.98, "trail": 0.10, "max_hold": 30}

    def score(self, t):
        x, p = lambda k: self.x(k, t), self.params
        w = p["wait_days"]
        if t < w:
            return np.full(len(self.m.symbols), np.nan)
        c, low_r, close_r = self.m.close[t], self.m.low[t - w], self.m.close[t - w]
        lows_since = np.nanmin(self.m.low[t - w + 1: t + 1], axis=0)
        with np.errstate(invalid="ignore"):
            ok = ((x("days_since_earnings") == w) & (x("earnings_reaction") <= p["max_reaction"])
                  & (self.f["rs_rank"][t - w - 1] >= p["min_rs"]) & (x("dist_sma200") > 0)
                  & (lows_since > low_r) & (c > close_r))
        return np.where(ok, -x("earnings_reaction"), np.nan)

    def plan(self, t, j):
        w = self.params["wait_days"]
        c = self.m.close[t, j]
        stop = min(self.m.low[t - w, j] * self.params["stop_below_low"], atr_stop(c, self.x("atr_pct", t)[j], 2.5))
        return Signal(self.m.symbols[j], stop=stop, trail_pct=self.params["trail"], max_hold=self.params["max_hold"], tag=self.name)
