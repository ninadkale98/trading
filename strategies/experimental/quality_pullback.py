"""Quality pullback in an uptrend: our Robinhood scan ("Quality Uptrend Pullback", learning/08) as a strategy."""
import numpy as np

from core.backtest.engine import Signal
from core.strategy.base import FeatureStrategy, atr_stop, earnings_clear


class QualityPullback(FeatureStrategy):
    name = "quality_pullback"
    version = "1"
    description = ("Large, liquid company in a long-term uptrend (above its rising 200-day average, 50-day above 200-day) "
                   "that has dipped back to its 50-day average: 5–25% below its 52-week high, RSI 35–50. Profitable with an "
                   "operating margin above 10% and a P/E of 5–40 when fundamentals are known. No earnings report within "
                   "2 weeks. Strongest stocks (RS rank) first.")
    hypothesis = ("Strong trends tend to continue (momentum), and buying a temporary dip in a strong, profitable company "
                  "gets a better price than chasing it at the high. Profitability filters avoid weak businesses that "
                  "are merely bouncing.")
    needs_fundamentals = True
    min_adv = 20_000_000          # size proxy: only big, heavily traded companies
    params = {"dist_sma50": (-0.05, 0.03), "dist_52w_high": (-0.25, -0.05), "rsi": (35, 50), "op_margin_min": 0.10,
              "pe": (5, 40), "stop_atr": 2.0, "target_r": 2.0, "trail": 0.10, "max_hold": 60}

    def eligible(self, t):
        return super().eligible(t) & earnings_clear(self.f, t)

    def score(self, t):
        x, p = lambda k: self.x(k, t), self.params
        with np.errstate(invalid="ignore"):
            uptrend = (x("dist_sma200") > 0) & (x("sma200_slope") > 0) & (x("dist_sma200") > x("dist_sma50"))  # 50-day > 200-day
            dip = ((x("dist_sma50") >= p["dist_sma50"][0]) & (x("dist_sma50") <= p["dist_sma50"][1])
                   & (x("dist_52w_high") >= p["dist_52w_high"][0]) & (x("dist_52w_high") <= p["dist_52w_high"][1])
                   & (x("rsi14") >= p["rsi"][0]) & (x("rsi14") <= p["rsi"][1]))
            om, pe, nm = x("op_margin"), x("pe"), x("net_margin")
            quality = ((np.isnan(om) | (om >= p["op_margin_min"]))
                       & (np.isnan(pe) | ((pe >= p["pe"][0]) & (pe <= p["pe"][1])))
                       & (np.isnan(nm) | (nm > 0)))
        return np.where(uptrend & dip & quality, x("rs_rank"), np.nan)

    def plan(self, t, j):
        c = self.m.close[t, j]
        stop = atr_stop(c, self.x("atr_pct", t)[j], self.params["stop_atr"])
        return Signal(self.m.symbols[j], stop=stop, target=c + self.params["target_r"] * (c - stop), partial=0.5,
                      trail_pct=self.params["trail"], max_hold=self.params["max_hold"], tag=self.name)
