"""Post-earnings drift: buy strong stocks right after a big positive earnings reaction."""
import numpy as np

from core.backtest.engine import Signal
from core.strategy.base import FeatureStrategy, atr_stop


class EarningsGapUp(FeatureStrategy):
    name = "earnings_gap_up"
    version = "1"
    description = ("The day after an earnings report, if the stock beat the market by 5% or more on heavy volume (2× normal) "
                   "and was already in a decent trend (score ≥ 3), buy at the next open and hold up to ~2 months.")
    hypothesis = ("Post-earnings announcement drift, one of the most-replicated findings in finance: after good news, "
                  "prices keep drifting the same way for weeks because investors under-react to it.")
    max_new_per_day = 3
    params = {"min_reaction": 0.05, "min_rvol": 2.0, "min_trend": 3, "stop_atr": 2.0, "trail": 0.12, "max_hold": 40}

    def score(self, t):
        x, p = lambda k: self.x(k, t), self.params
        with np.errstate(invalid="ignore"):
            ok = ((x("days_since_earnings") == 0) & (x("earnings_reaction") >= p["min_reaction"])
                  & (x("rvol") >= p["min_rvol"]) & (x("trend_score") >= p["min_trend"]))
        return np.where(ok, x("earnings_reaction"), np.nan)

    def plan(self, t, j):
        c = self.m.close[t, j]
        stop = max(atr_stop(c, self.x("atr_pct", t)[j], self.params["stop_atr"]), self.m.low[t, j] * 0.99)  # below reaction-day low
        return Signal(self.m.symbols[j], stop=min(stop, c * 0.96), trail_pct=self.params["trail"],
                      max_hold=self.params["max_hold"], tag=self.name)
