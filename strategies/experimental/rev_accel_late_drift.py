"""Late post-earnings drift: buy 15-35 days after a report with accelerating sales and a positive price reaction."""
import numpy as np

from core.backtest.engine import Signal
from core.strategy.base import FeatureStrategy, earnings_clear


class RevAccelLateDrift(FeatureStrategy):
    name = "rev_accel_late_drift"
    version = "1"
    description = ("15-35 trading days after an earnings report where the stock reacted at least +2% vs SPY, quarterly sales "
                   "grew at least 10% and at least 3 points faster than the trailing 12 months, operating margin did not "
                   "shrink, and the stock is above its 50-day average and within 20% of its 52-week high. Company worth "
                   ">= $1B, trading >= $5M/day, next report more than 30 days away. Only the first eligible day per report. "
                   "Exit with a 20% stop, 20% trailing stop, before the next report, or after 50 trading days.")
    hypothesis = ("Accelerating revenue is absorbed slowly as analysts raise estimates over 1-3 months. A positive reaction "
                  "shows the market noticed but did not fully price it. Entering 15-35 days after the report avoids the "
                  "first-day spike and gives SEC filings time to appear. Investors still extrapolating the slower 12-month "
                  "growth rate create the drift.")
    needs_fundamentals = True
    min_adv = 5_000_000
    max_new_per_day = 3
    holds_through_earnings = False
    params = {"dse_min": 15, "dse_max": 35, "min_react": 0.02, "min_growth_q": 0.10, "min_accel": 0.03,
              "min_mcap": 1e9, "min_adv": 5e6, "max_dist_high": -0.20, "min_days_next": 30,
              "stop": 0.20, "trail": 0.20, "max_hold": 50, "exit_days": 3,
              "cap_accel": 0.5, "cap_react": 0.25, "cap_opm": 0.10}

    def helper_cond(self, t):
        """Base conditions (without first-day rule and without super eligibility) for day t."""
        p = self.params
        x = self.x
        dse = x("days_since_earnings", t)
        react = x("earnings_reaction", t)
        gq = x("rev_growth_q", t)
        gy = x("rev_growth_yoy", t)
        opm = x("op_margin_chg", t)
        gm = x("gross_margin", t)
        d50 = x("dist_sma50", t)
        dh = x("dist_52w_high", t)
        mc = x("market_cap", t)
        adv = x("adv20", t)
        dn = x("days_to_earnings_est", t)
        with np.errstate(invalid="ignore"):
            ok = ((dse >= p["dse_min"]) & (dse <= p["dse_max"]) & (react >= p["min_react"])
                  & (gq >= p["min_growth_q"]) & ((gq - gy) >= p["min_accel"]) & (opm >= 0) & (gm > 0)
                  & (d50 > 0) & (dh >= p["max_dist_high"]) & (mc >= p["min_mcap"]) & (adv >= p["min_adv"])
                  & (dn > p["min_days_next"]))
        return ok

    def eligible(self, t):
        return super().eligible(t) & earnings_clear(self.f, t)

    def helper_pct(self, v, mask):
        out = np.full(len(v), np.nan)
        idx = np.where(mask)[0]
        n = len(idx)
        if n == 0:
            return out
        order = np.argsort(np.argsort(v[idx]))
        out[idx] = (order + 1.0) / n
        return out

    def score(self, t):
        p = self.params
        n = len(self.m.symbols)
        ok = self.helper_cond(t) & self.eligible(t)
        if not ok.any():
            return np.full(n, np.nan)
        dse = self.x("days_since_earnings", t)
        # first eligible day per report: no earlier day of the same report met the base conditions
        for k in range(1, p["dse_max"] - p["dse_min"] + 1):
            if t - k < 0:
                break
            prev = self.helper_cond(t - k)
            same = np.nan_to_num(self.x("days_since_earnings", t - k), nan=-999.0) == (np.nan_to_num(dse, nan=-1.0) - k)
            ok = ok & ~(prev & same)
            if not ok.any():
                return np.full(n, np.nan)
        gq = self.x("rev_growth_q", t)
        gy = self.x("rev_growth_yoy", t)
        acc = np.minimum(gq - gy, p["cap_accel"])
        rea = np.minimum(self.x("earnings_reaction", t), p["cap_react"])
        opm = np.minimum(self.x("op_margin_chg", t), p["cap_opm"])
        s = (self.helper_pct(acc, ok) + self.helper_pct(rea, ok) + self.helper_pct(opm, ok)) / 3.0
        return np.where(ok, s, np.nan)

    def plan(self, t, j):
        c = self.m.close[t, j]
        p = self.params
        return Signal(self.m.symbols[j], stop=c * (1 - p["stop"]), target=None, trail_pct=p["trail"],
                      max_hold=p["max_hold"], tag=self.name)

    def exits(self, t, m, held):
        dn = self.x("days_to_earnings_est", t)
        pos = {s: i for i, s in enumerate(self.m.symbols)}
        out = []
        for s in held:
            i = pos.get(s)
            if i is None:
                continue
            v = dn[i]
            if v == v and v <= self.params["exit_days"]:
                out.append(s)
        return out

    def why(self, t, j):
        return "sales accelerating, positive earnings reaction, first day in 15-35d post-report window"
