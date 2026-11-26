"""Short-term return to the average: a sharp dip in a stock that is still in a long-term uptrend."""
import numpy as np

from core.backtest.engine import Signal
from core.strategy.base import FeatureStrategy, atr_stop, earnings_clear


class ReturnToAverage(FeatureStrategy):
    name = "return_to_average"
    version = "1"
    description = ("Liquid stock above its 200-day average that just dropped sharply: RSI below 30 or down 8%+ in a week, "
                   "with no earnings due. Buy at the next open; sell when it closes back above its 20-day average, or "
                   "after 15 trading days.")
    hypothesis = ("Short-term reversal: sharp drops in otherwise healthy, liquid stocks are often driven by temporary "
                  "selling pressure and partly bounce back within days to weeks.")
    max_new_per_day = 3
    min_adv = 5_000_000
    params = {"rsi_max": 30, "ret5_max": -0.08, "stop_atr": 2.5, "max_hold": 15}

    def eligible(self, t):
        return super().eligible(t) & earnings_clear(self.f, t)

    def score(self, t):
        x, p = lambda k: self.x(k, t), self.params
        with np.errstate(invalid="ignore"):
            ok = (x("dist_sma200") > 0) & ((x("rsi14") < p["rsi_max"]) | (x("ret_5d") <= p["ret5_max"]))
        return np.where(ok, -x("rsi14"), np.nan)

    def plan(self, t, j):
        c = self.m.close[t, j]
        return Signal(self.m.symbols[j], stop=atr_stop(c, self.x("atr_pct", t)[j], self.params["stop_atr"]),
                      max_hold=self.params["max_hold"], tag=self.name)

    def exits(self, t, m, held):
        d20 = self.f["dist_sma20"][t]
        return [s for s in held if np.isfinite(d20[m.col(s)]) and d20[m.col(s)] > 0]
