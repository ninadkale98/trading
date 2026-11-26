"""Post-earnings drift in mid-caps ($1B-$15B): confirmed EPS beat with positive price and sales reaction, bought days after the report."""
import numpy as np

from core.backtest.engine import Signal
from core.strategy.base import FeatureStrategy, earnings_clear


class SueDriftMidcap(FeatureStrategy):
    name = "sue_drift_midcap"
    version = "1"
    description = ("Mid-cap stocks ($1B-$15B, trading >= $5M/day) that reported earnings 2-10 trading days ago with an EPS beat "
                   "(surprise >= 0.1% of price), a market-adjusted reaction of at least +2%, and quarterly sales growth of at least 5%. "
                   "Only the first eligible day per report. Ranked by the average percentile of surprise size and price reaction. "
                   "Exit with a 20% stop, 20% trailing stop, before the next report (<= 3 days away), or after 55 trading days.")
    hypothesis = ("Post-earnings drift is strongest where fewer analysts and funds watch a stock, because they absorb news slowly. "
                  "Drift has largely vanished in mega-caps but may survive in liquid $1-15B companies, where holders and analysts "
                  "are slow to revise estimates. Same rules as the parent drift strategy with a market-cap ceiling added.")
    needs_fundamentals = True
    min_adv = 5_000_000
    max_new_per_day = 3
    params = {"dse_min": 2, "dse_max": 10, "min_surprise": 0.001, "surprise_cap": 0.05, "min_reaction": 0.02,
              "reaction_cap": 0.25, "min_rev_growth": 0.05, "min_mcap": 1e9, "max_mcap": 15e9,
              "min_adv20": 5e6, "min_days_to_next": 30, "exit_days_to_next": 3,
              "stop": 0.20, "trail": 0.20, "max_hold": 55}

    def helper_base(self, t):
        p = self.params
        f = self.f
        dse = f["days_since_earnings"][t]
        with np.errstate(invalid="ignore"):
            ok = ((dse >= p["dse_min"]) & (dse <= p["dse_max"])
                  & (f["eps_surprise_px"][t] >= p["min_surprise"])
                  & (f["earnings_reaction"][t] >= p["min_reaction"])
                  & (f["rev_growth_q"][t] >= p["min_rev_growth"])
                  & (f["market_cap"][t] >= p["min_mcap"])
                  & (f["market_cap"][t] <= p["max_mcap"])
                  & (f["adv20"][t] >= p["min_adv20"])
                  & (f["days_to_earnings_est"][t] > p["min_days_to_next"]))
        return ok

    def eligible(self, t):
        return super().eligible(t) & earnings_clear(self.f, t)

    def helper_pct(self, x, ok):
        out = np.full(len(x), np.nan)
        idx = np.where(ok)[0]
        n = len(idx)
        if n == 0:
            return out
        order = np.argsort(x[idx], kind="stable")
        ranks = np.empty(n)
        ranks[order] = np.arange(n)
        out[idx] = (ranks + 1.0) / n
        return out

    def score(self, t):
        p = self.params
        n = len(self.m.symbols)
        if t < 1:
            return np.full(n, np.nan)
        ok = self.helper_base(t) & self.eligible(t)
        # only the first eligible day per report
        prev = self.helper_base(t - 1)
        with np.errstate(invalid="ignore"):
            same = self.f["days_since_earnings"][t - 1] == self.f["days_since_earnings"][t] - 1
        ok = ok & ~(prev & same)
        if not ok.any():
            return np.full(n, np.nan)
        sur = np.minimum(self.f["eps_surprise_px"][t], p["surprise_cap"])
        rea = np.minimum(self.f["earnings_reaction"][t], p["reaction_cap"])
        s = (self.helper_pct(sur, ok) + self.helper_pct(rea, ok)) / 2.0
        return np.where(ok, s, np.nan)

    def plan(self, t, j):
        p = self.params
        c = self.m.close[t, j]
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
            if v == v and v <= self.params["exit_days_to_next"]:
                out.append(s)
        return out

    def why(self, t, j):
        return "EPS beat %.2f%% of price, reaction %+.1f%%, mcap $%.1fB" % (
            self.f["eps_surprise_px"][t][j] * 100, self.f["earnings_reaction"][t][j] * 100,
            self.f["market_cap"][t][j] / 1e9)
