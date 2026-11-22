"""Buy a confirmed EPS beat with revenue growth shortly after the report and hold through the next report."""
import numpy as np

from core.backtest.engine import Signal
from core.strategy.base import FeatureStrategy


class SueCarryThroughReport(FeatureStrategy):
    name = "sue_carry_through_report"
    version = "1"
    description = ("2-10 trading days after an earnings report with an EPS beat (surprise >= 0.1% of price), a positive "
                   "report-day reaction (>= +2% vs SPY), quarterly sales growth >= 5%, company >= $1B, trading >= $5M/day, "
                   "and the next report more than 30 days away. First eligible day per report only. Ranked by the "
                   "average percentile of the beat size and the reaction. No sell-before-report rule: hold through the "
                   "next report with a 25% stop, 25% trailing stop, max 110 trading days.")
    hypothesis = ("Earnings surprises repeat (Bernard & Thomas 1990): analysts anchor to old numbers and raise estimates "
                  "too slowly, so the next report is a predictable second beat, and much of the drift is earned on that "
                  "report day. Selling 3 days before it gives that up. Risk: drift has largely vanished in non-tiny "
                  "stocks since 2006, so this may only add report-day noise.")
    needs_fundamentals = True
    min_adv = 5_000_000
    max_new_per_day = 3
    holds_through_earnings = True
    params = {"dse_min": 2, "dse_max": 10, "min_surprise": 0.001, "cap_surprise": 0.05, "min_reaction": 0.02,
              "min_rev_growth": 0.05, "min_mcap": 1e9, "min_adv20": 5e6, "min_days_to_next": 30,
              "stop": 0.25, "trail": 0.25, "max_hold": 110}

    def helper_cond(self, t):
        p = self.p if False else self.params
        n = len(self.m.symbols)
        dse = self.f["days_since_earnings"][t]
        eps = self.f["eps_surprise_px"][t]
        rx = self.f["earnings_reaction"][t]
        rg = self.f["rev_growth_q"][t]
        mc = self.f["market_cap"][t]
        adv = self.f["adv20"][t]
        dte = self.f["days_to_earnings_est"][t]
        with np.errstate(invalid="ignore"):
            ok = ((dse >= p["dse_min"]) & (dse <= p["dse_max"]) & (eps >= p["min_surprise"])
                  & (rx >= p["min_reaction"]) & (rg >= p["min_rev_growth"]) & (mc >= p["min_mcap"])
                  & (adv >= p["min_adv20"]) & (dte > p["min_days_to_next"]))
        return np.where(np.isnan(dse), False, ok) if n else ok

    def helper_first(self, t):
        ok = self.helper_cond(t)
        dse = self.f["days_since_earnings"][t]
        for k in range(1, self.params["dse_max"] + 1):
            if t - k < 0:
                break
            prev = self.helper_cond(t - k)
            pd = self.f["days_since_earnings"][t - k]
            with np.errstate(invalid="ignore"):
                same = pd == (dse - k)
            ok = ok & ~(prev & same)
        return ok

    def eligible(self, t):
        return super().eligible(t) & self.helper_first(t)

    def helper_pct(self, x, mask):
        out = np.full(len(x), np.nan)
        idx = np.where(mask & ~np.isnan(x))[0]
        if len(idx) == 0:
            return out
        order = np.argsort(np.argsort(x[idx]))
        out[idx] = (order + 1.0) / len(idx)
        return out

    def score(self, t):
        p = self.params
        ok = self.eligible(t)
        eps = np.minimum(self.f["eps_surprise_px"][t], p["cap_surprise"])
        rx = self.f["earnings_reaction"][t]
        s = (self.helper_pct(eps, ok) + self.helper_pct(rx, ok)) / 2.0
        return np.where(ok, s, np.nan)

    def plan(self, t, j):
        p = self.params
        c = self.m.close[t, j]
        return Signal(self.m.symbols[j], stop=c * (1 - p["stop"]), target=None, trail_pct=p["trail"],
                      max_hold=p["max_hold"], tag=self.name)

    def why(self, t, j):
        return "EPS beat %.2f%% of price, reaction %+.1f%%, held through next report" % (
            self.f["eps_surprise_px"][t][j] * 100, self.f["earnings_reaction"][t][j] * 100)
