"""Earnings-surprise drift: buy confirmed EPS beats with a positive reaction and sales growth, no price-strength filters."""
import numpy as np

from core.backtest.engine import Signal
from core.strategy.base import FeatureStrategy


class SueDriftNoMomentum(FeatureStrategy):
    name = "sue_drift_no_momentum"
    version = "1"
    description = ("Two to ten trading days after an earnings report, buy stocks whose EPS surprise (scaled by price) "
                   "was positive, whose price reaction beat SPY by 2%+, with sales growth of 5%+, company worth "
                   "$1B+, trading $5M+/day, next report more than 30 days away. Only the first eligible day per "
                   "report. No relative-strength, 52-week-high or moving-average filters. Exit on a 20% stop, "
                   "20% trailing stop, 3 days before the next report, or after 55 trading days.")
    hypothesis = ("Prices under-react to a confirmed earnings beat: analysts revise slowly and funds re-weight over "
                  "weeks. If the surprise plus a positive reaction is the real driver, the edge should survive "
                  "without price-strength filters and the number of trades should grow a lot.")
    needs_fundamentals = True
    min_adv = 5_000_000
    max_new_per_day = 3
    params = {"dse_min": 2, "dse_max": 10, "min_surprise": 0.001, "surprise_cap": 0.05, "min_reaction": 0.02,
              "min_rev_growth": 0.05, "min_mcap": 1e9, "min_adv20": 5e6, "min_days_to_next": 30,
              "exit_days_to_next": 3, "stop": 0.20, "trail": 0.20, "max_hold": 55}

    def helper_cond(self, t):
        p = self.params
        f = self.f
        dse = f["days_since_earnings"][t]
        dte = f["days_to_earnings_est"][t]
        with np.errstate(invalid="ignore"):
            ok = ((dse >= p["dse_min"]) & (dse <= p["dse_max"])
                  & (f["eps_surprise_px"][t] >= p["min_surprise"])
                  & (f["earnings_reaction"][t] >= p["min_reaction"])
                  & (f["rev_growth_yoy"][t] >= p["min_rev_growth"])
                  & (f["market_cap"][t] >= p["min_mcap"])
                  & (f["adv20"][t] >= p["min_adv20"])
                  & (dte > p["min_days_to_next"])
                  & ~((dte <= 0) & (dse > 50)))
        return ok

    def eligible(self, t):
        return super().eligible(t)

    def score(self, t):
        p = self.params
        n = len(self.m.symbols)
        if t < 12:
            return np.full(n, np.nan)
        ok = self.helper_cond(t) & self.eligible(t)
        dse = self.f["days_since_earnings"][t]
        for k in range(1, 9):
            with np.errstate(invalid="ignore"):
                same = (dse - k) >= p["dse_min"]
            prev = self.helper_cond(t - k)
            ok = ok & ~(same & prev)
        s = np.clip(np.nan_to_num(self.f["eps_surprise_px"][t]), 0, p["surprise_cap"]) / p["surprise_cap"]
        r = np.clip(np.nan_to_num(self.f["earnings_reaction"][t]), 0, 1.0)
        return np.where(ok, s + 0.01 * r, np.nan)

    def plan(self, t, j):
        c = self.m.close[t, j]
        return Signal(self.m.symbols[j], stop=c * (1 - self.params["stop"]), target=None,
                      trail_pct=self.params["trail"], max_hold=self.params["max_hold"], tag=self.name)

    def exits(self, t, m, held):
        dte = self.f["days_to_earnings_est"][t]
        idx = {s: i for i, s in enumerate(self.m.symbols)}
        out = []
        for s in held:
            i = idx.get(s)
            if i is None:
                continue
            v = dte[i]
            if v == v and v <= self.params["exit_days_to_next"]:
                out.append(s)
        return out

    def why(self, t, j):
        return "EPS beat %.3f of price, reaction %+.1f%%" % (self.f["eps_surprise_px"][t][j],
                                                            100 * self.f["earnings_reaction"][t][j])
