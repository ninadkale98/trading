"""Pre-earnings run-up: buy recent winners 12-20 days before their next report and sell before the report."""
import numpy as np

from core.backtest.engine import Signal
from core.strategy.base import FeatureStrategy


class PreEarningsRunup(FeatureStrategy):
    name = "pre_earnings_runup"
    version = "1"
    description = ("Strong-momentum stocks (relative strength rank >= 75, above the 50-day average, within 15% of the 52-week high, "
                   "worth >= $2B, trading >= $10M/day) whose last earnings reaction was positive and whose next report is "
                   "12-20 calendar days away. Buy at the next open, sell at the first close 3 or fewer days before the "
                   "report (or at once if the report came early). Max hold 15 days, stop at the larger of 10% or 2.5x daily range.")
    hypothesis = ("Stocks tend to earn above-market returns in the weeks before a scheduled report (earnings announcement "
                  "premium), strongest for past winners, as retail and momentum traders buy ahead of an event they expect "
                  "to go well. Selling 1-2 days before the report keeps the run-up and avoids the report gap, so it does not "
                  "overlap the post-earnings drift sleeve.")
    needs_fundamentals = True
    min_adv = 1e7
    max_new_per_day = 3
    holds_through_earnings = False
    params = {"dte_min": 12, "dte_max": 20, "dse_min": 40, "dse_max": 58, "min_rs": 75, "max_off_high": 0.15,
              "min_mcap": 2e9, "min_adv20": 1e7, "react_cap": 0.20, "stop_floor": 0.10, "atr_mult": 2.5,
              "exit_dte": 3, "max_hold": 15}

    def eligible(self, t):
        p = self.params
        f = self.f
        dte = f["days_to_earnings_est"][t]
        dse = f["days_since_earnings"][t]
        with np.errstate(invalid="ignore"):
            ok = ((dte >= p["dte_min"]) & (dte <= p["dte_max"])
                  & (dse >= p["dse_min"]) & (dse <= p["dse_max"])
                  & (f["earnings_reaction"][t] > 0)
                  & (f["rs_rank"][t] >= p["min_rs"])
                  & (f["dist_sma50"][t] > 0)
                  & (f["dist_52w_high"][t] >= -p["max_off_high"])
                  & (f["market_cap"][t] >= p["min_mcap"])
                  & (f["adv20"][t] >= p["min_adv20"]))
        return super().eligible(t) & ok

    def helper_pct(self, x, mask):
        out = np.full(len(x), np.nan)
        idx = np.where(mask & ~np.isnan(x))[0]
        n = len(idx)
        if n == 0:
            return out
        order = np.argsort(x[idx], kind="stable")
        r = np.empty(n)
        r[order] = np.arange(n)
        out[idx] = r / max(n - 1, 1)
        return out

    def score(self, t):
        mask = self.eligible(t)
        rs = self.f["rs_rank"][t]
        react = np.minimum(self.f["earnings_reaction"][t], self.params["react_cap"])
        s = (self.helper_pct(rs, mask) + self.helper_pct(react, mask)) / 2.0
        return np.where(mask, s, np.nan)

    def plan(self, t, j):
        p = self.params
        c = self.m.close[t, j]
        atr = self.f["atr_pct"][t][j]
        if not np.isfinite(atr):
            atr = 0.0
        d = max(p["stop_floor"], p["atr_mult"] * atr)
        return Signal(self.m.symbols[j], stop=c * (1 - d), max_hold=p["max_hold"], tag=self.name)

    def exits(self, t, m, held):
        dte = self.f["days_to_earnings_est"][t]
        dse = self.f["days_since_earnings"][t]
        pos = {s: i for i, s in enumerate(self.m.symbols)}
        out = []
        for s in held:
            j = pos.get(s)
            if j is None:
                continue
            d1, d2 = dte[j], dse[j]
            if (np.isfinite(d1) and d1 <= self.params["exit_dte"]) or (np.isfinite(d2) and d2 == 0):
                out.append(s)
        return out

    def why(self, t, j):
        return "report in %d days, last reaction %+.1f%%, RS %d" % (
            self.f["days_to_earnings_est"][t][j], 100 * self.f["earnings_reaction"][t][j], self.f["rs_rank"][t][j])
