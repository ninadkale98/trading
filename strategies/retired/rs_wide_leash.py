"""Relative-strength leaders in uptrends, held with wide stops and a 200-day trend exit so momentum has room."""
import numpy as np

from core.backtest.engine import Signal
from core.strategy.base import FeatureStrategy, earnings_clear


class RsWideLeash(FeatureStrategy):
    name = "rs_wide_leash"
    version = "1"
    description = ("Stocks in the top 10% of relative strength (rs_rank >= 90) with a perfect 5/5 trend score, within 10% "
                   "of the 52-week high, trading >= $10M/day, no earnings within 14 days. Ranked by 6-month strength "
                   "vs SPY. Exits are wide: 25% initial stop, 25% trailing stop, sell if price closes below the "
                   "200-day average, max 120 trading days. Positions hold through earnings reports.")
    hypothesis = ("Investors under-react to sustained good performance and institutions build positions slowly, so "
                  "winners keep outperforming for months. The parent strategy held only ~19 of 120 allowed days, "
                  "suggesting normal pullbacks forced exits. Keeping nearly the same entry and widening exits tests "
                  "that directly.")
    needs_fundamentals = False
    min_adv = 10_000_000
    max_new_per_day = 3
    holds_through_earnings = True
    params = {"min_rs_rank": 90, "min_trend": 5, "max_dist_high": -0.10, "min_adv20": 10_000_000,
              "min_days_to_earn": 14, "stop": 0.25, "trail": 0.25, "max_hold": 120}

    def eligible(self, t):
        p = self.params
        base = super().eligible(t)
        with np.errstate(invalid="ignore"):
            ok = ((self.f["rs_rank"][t] >= p["min_rs_rank"])
                  & (self.f["trend_score"][t] >= p["min_trend"])
                  & (self.f["dist_52w_high"][t] >= p["max_dist_high"])
                  & (self.f["adv20"][t] >= p["min_adv20"])
                  & (self.f["days_to_earnings_est"][t] > p["min_days_to_earn"]))
        return base & ok

    def score(self, t):
        s = np.asarray(self.f["rs_spy_120"][t], dtype=float)
        return np.where(self.eligible(t), s, np.nan)

    def plan(self, t, j):
        c = self.m.close[t, j]
        p = self.params
        return Signal(self.m.symbols[j], stop=c * (1 - p["stop"]), target=None,
                      trail_pct=p["trail"], max_hold=p["max_hold"], tag=self.name)

    def exits(self, t, m, held):
        d = self.f["dist_sma200"][t]
        syms = np.asarray(self.m.symbols)
        out = []
        for s in held:
            idx = np.where(syms == s)[0]
            if len(idx) == 0:
                continue
            v = d[idx[0]]
            if v == v and v < 0:
                out.append(s)
        return out

    def why(self, t, j):
        return "RS rank>=90, trend 5/5, near 52w high; rs_spy_120=%.2f" % float(self.f["rs_spy_120"][t][j])
