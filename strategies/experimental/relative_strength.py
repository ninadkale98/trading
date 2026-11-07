"""Relative strength (momentum): own the strongest stocks while their uptrend is intact."""
import numpy as np

from core.backtest.engine import Signal
from core.strategy.base import FeatureStrategy, atr_stop, earnings_clear


class RelativeStrength(FeatureStrategy):
    name = "relative_strength"
    version = "1"
    description = ("Top-decile past-year performers (RS rank ≥ 90) with a perfect uptrend checklist (5/5), within 10% of "
                   "their 52-week high, no earnings due. Strongest first. Wide trailing stop (15%), hold up to ~6 months; "
                   "sell if the trend breaks (closes more than 3% below its 50-day average).")
    hypothesis = ("Momentum: stocks that outperformed over the past 3–12 months tend to keep outperforming for the next "
                  "several months (documented across decades and countries). Requiring a clean uptrend avoids "
                  "stocks whose momentum has already cracked.")
    min_adv = 5_000_000
    params = {"min_rs": 90, "near_high": -0.10, "stop_atr": 2.5, "trail": 0.15, "max_hold": 120, "trend_break": -0.03}

    def eligible(self, t):
        return super().eligible(t) & earnings_clear(self.f, t)

    def score(self, t):
        x, p = lambda k: self.x(k, t), self.params
        with np.errstate(invalid="ignore"):
            ok = (x("rs_rank") >= p["min_rs"]) & (x("trend_score") == 5) & (x("dist_52w_high") >= p["near_high"])
        return np.where(ok, x("rs_rank") + x("ret_60d").clip(-1, 1), np.nan)

    def plan(self, t, j):
        c = self.m.close[t, j]
        return Signal(self.m.symbols[j], stop=atr_stop(c, self.x("atr_pct", t)[j], self.params["stop_atr"]),
                      trail_pct=self.params["trail"], max_hold=self.params["max_hold"], tag=self.name)

    def exits(self, t, m, held):
        d50 = self.f["dist_sma50"][t]
        return [s for s in held if np.isfinite(d50[m.col(s)]) and d50[m.col(s)] < self.params["trend_break"]]
