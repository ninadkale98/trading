"""Post-earnings drift: stocks that jumped on earnings with revenue growth and price leadership, entered 2-10 days after the report."""
import numpy as np

from core.backtest.engine import Signal
from core.strategy.base import FeatureStrategy, earnings_clear


class ReactDriftMomentum(FeatureStrategy):
    name = "react_drift_momentum"
    version = "1"
    description = ("Stock reported earnings 2-10 trading days ago and rose at least 2% more than SPY on the reaction day, "
                   "revenue grew >= 5% year over year in the latest quarter, price is within 15% of its 52-week high, "
                   "above its 50-day average, relative-strength rank >= 60, company >= $1B, trading >= $5M/day, next "
                   "report more than 30 days away. Only the first eligible day per report. Ranked by the average "
                   "percentile of the reaction (capped at 25%) and RS rank. Wide 20% stop plus 20% trailing stop, sold "
                   "before the next report, max hold 55 days. EPS surprise data is not used.")
    hypothesis = ("Analysts and funds update slowly after a report the market liked, and leaders near highs attract "
                  "follow-on buying for 1-3 months, while holders anchored to the old price and profit-takers sell "
                  "early. Momentum plus a strong reaction should carry most of the edge without sparse surprise data.")
    needs_fundamentals = True
    min_adv = 5_000_000
    max_new_per_day = 3
    holds_through_earnings = False
    params = {"min_days": 2, "max_days": 10, "min_react": 0.02, "react_cap": 0.25, "min_rev_q": 0.05,
              "max_dist_high": 0.15, "min_rs": 60, "min_mcap": 1e9, "min_adv20": 5e6,
              "min_days_to_next": 30, "exit_days_to_next": 3, "stop": 0.20, "trail": 0.20, "max_hold": 55}

    def helper_cond(self, t):
        p = self.params
        f = self.f
        with np.errstate(invalid="ignore"):
            ds = f["days_since_earnings"][t]
            ok = ((ds >= p["min_days"]) & (ds <= p["max_days"])
                  & (f["earnings_reaction"][t] >= p["min_react"])
                  & (f["rev_growth_q"][t] >= p["min_rev_q"])
                  & (f["dist_52w_high"][t] >= -p["max_dist_high"])
                  & (f["rs_rank"][t] >= p["min_rs"])
                  & (f["dist_sma50"][t] > 0)
                  & (f["market_cap"][t] >= p["min_mcap"])
                  & (f["adv20"][t] >= p["min_adv20"])
                  & (f["days_to_earnings_est"][t] > p["min_days_to_next"]))
        return ok

    def helper_pct(self, x, mask):
        out = np.full(len(x), np.nan)
        idx = np.where(mask)[0]
        n = len(idx)
        if n == 0:
            return out
        order = np.argsort(x[idx], kind="stable")
        r = np.empty(n)
        r[order] = np.arange(n)
        out[idx] = (r + 1) / n
        return out

    def eligible(self, t):
        return super().eligible(t) & earnings_clear(self.f, t)

    def score(self, t):
        p = self.params
        n = len(self.m.symbols)
        base = self.eligible(t)
        ok = base & self.helper_cond(t)
        if not ok.any():
            return np.full(n, np.nan)
        ds = self.f["days_since_earnings"][t]
        for k in range(1, p["max_days"] + 1):
            if t - k < 0:
                break
            prev = self.helper_cond(t - k)
            with np.errstate(invalid="ignore"):
                same = self.f["days_since_earnings"][t - k] == (ds - k)
            ok = ok & ~(prev & same)
        if not ok.any():
            return np.full(n, np.nan)
        react = np.minimum(self.f["earnings_reaction"][t], p["react_cap"])
        s = (self.helper_pct(react, ok) + self.helper_pct(self.f["rs_rank"][t], ok)) / 2.0
        return np.where(ok, s, np.nan)

    def plan(self, t, j):
        c = self.m.close[t, j]
        return Signal(self.m.symbols[j], stop=c * (1 - self.params["stop"]), target=None,
                      trail_pct=self.params["trail"], max_hold=self.params["max_hold"], tag=self.name)

    def exits(self, t, m, held):
        d = self.f["days_to_earnings_est"][t]
        pos = {s: i for i, s in enumerate(self.m.symbols)}
        out = []
        for s in held:
            i = pos.get(s)
            if i is None:
                continue
            v = d[i]
            if v == v and v <= self.params["exit_days_to_next"]:
                out.append(s)
        return out

    def why(self, t, j):
        return "earnings reaction %+.1f%%, rs_rank %.0f" % (
            100 * self.f["earnings_reaction"][t][j], self.f["rs_rank"][t][j])
