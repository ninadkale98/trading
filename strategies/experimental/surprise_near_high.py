"""Confirmed earnings beat with positive reaction and sales growth, bought 2-10 days after the report while near the 52-week high."""
import numpy as np

from core.backtest.engine import Signal
from core.strategy.base import FeatureStrategy, earnings_clear


class SurpriseNearHigh(FeatureStrategy):
    name = "surprise_near_high"
    version = "1"
    description = ("Stock reported earnings 2-10 trading days ago with an EPS beat of at least 5%, a market-relative reaction "
                   "of at least +2%, quarterly sales growth of at least 10%, within 8% of its 52-week high, relative "
                   "strength rank >= 70 and above its 50-day average. Company worth >= $1B, trading >= $5M/day. Only the "
                   "first eligible day after each report. Ranked by the average percentile of capped EPS surprise, "
                   "reaction, sales growth and relative strength. Hold up to 55 days with a 20% initial stop, 20% trailing "
                   "stop, and sell before the next earnings report (within 3 days).")
    hypothesis = ("Earnings news combined with price strength may identify companies whose improvement analysts and funds "
                  "are slow to absorb. Waiting at least 2 days avoids paying for the first-day spike. Requiring an EPS beat, "
                  "positive reaction and growing sales filters out low-quality beats. Proven wrong if t_vs_twin < 2.0, "
                  "average excess is not clearly above earnings_gap_up's -0.47%, or the result vanishes when eps_surprise "
                  "is capped at 0.50.")
    needs_fundamentals = True
    min_adv = 5_000_000
    max_new_per_day = 3
    holds_through_earnings = False
    params = {"dse_min": 2, "dse_max": 10, "min_surprise": 0.05, "surprise_cap": 0.50, "min_reaction": 0.02,
              "min_rev_q": 0.10, "max_dist_high": 0.08, "min_rs": 70, "min_mcap": 1e9, "min_adv20": 5e6,
              "stop": 0.20, "trail": 0.20, "max_hold": 55, "exit_days_to_earn": 3}

    def helper_base(self, t):
        p = self.params
        f = self.f
        with np.errstate(invalid="ignore"):
            ok = ((f["days_since_earnings"][t] >= p["dse_min"]) & (f["days_since_earnings"][t] <= p["dse_max"])
                  & (f["eps_surprise"][t] >= p["min_surprise"])
                  & (f["earnings_reaction"][t] >= p["min_reaction"])
                  & (f["rev_growth_q"][t] >= p["min_rev_q"])
                  & (f["dist_52w_high"][t] >= -p["max_dist_high"])
                  & (f["rs_rank"][t] >= p["min_rs"])
                  & (f["dist_sma50"][t] > 0)
                  & (f["market_cap"][t] >= p["min_mcap"])
                  & (f["adv20"][t] >= p["min_adv20"]))
        return ok

    def helper_pct(self, x, mask):
        out = np.full(len(x), np.nan)
        n = int(mask.sum())
        if n == 0:
            return out
        v = x[mask]
        r = np.argsort(np.argsort(v)).astype(float)
        out[mask] = r / max(n - 1, 1)
        return out

    def eligible(self, t):
        return super().eligible(t) & earnings_clear(self.f, t)

    def score(self, t):
        p = self.params
        n = len(self.m.symbols)
        ok = self.eligible(t) & self.helper_base(t)
        if not ok.any():
            return np.full(n, np.nan)
        dse = self.f["days_since_earnings"][t]
        # first eligible day after the report: no earlier eligible day in this window
        for k in range(1, p["dse_max"] - p["dse_min"] + 1):
            u = t - k
            if u < 0:
                break
            with np.errstate(invalid="ignore"):
                same = (self.f["days_since_earnings"][u] == dse - k) & (dse - k >= p["dse_min"])
                prev = self.helper_base(u) & same
            ok = ok & ~prev
        if not ok.any():
            return np.full(n, np.nan)
        f = self.f
        eps = np.minimum(f["eps_surprise"][t], p["surprise_cap"])
        parts = [self.helper_pct(eps, ok), self.helper_pct(f["earnings_reaction"][t], ok),
                 self.helper_pct(f["rev_growth_q"][t], ok), self.helper_pct(f["rs_rank"][t], ok)]
        s = (parts[0] + parts[1] + parts[2] + parts[3]) / 4.0
        return np.where(ok, s, np.nan)

    def plan(self, t, j):
        c = self.m.close[t, j]
        return Signal(self.m.symbols[j], stop=c * (1 - self.params["stop"]), trail_pct=self.params["trail"],
                      max_hold=self.params["max_hold"], tag=self.name)

    def exits(self, t, m, held):
        idx = {s: i for i, s in enumerate(self.m.symbols)}
        d = self.f["days_to_earnings_est"][t]
        out = []
        for s in held:
            i = idx.get(s)
            if i is None:
                continue
            v = d[i]
            if np.isfinite(v) and v <= self.params["exit_days_to_earn"]:
                out.append(s)
        return out

    def why(self, t, j):
        return ("EPS beat %.0f%%, reaction %+.1f%%, near 52w high" % (
            self.f["eps_surprise"][t][j] * 100, self.f["earnings_reaction"][t][j] * 100))
