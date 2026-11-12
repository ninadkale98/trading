"""Relative-strength leaders in a clean uptrend whose last earnings reaction, sales growth and margins confirm the move."""
import numpy as np

from core.backtest.engine import Signal
from core.strategy.base import FeatureStrategy, earnings_clear


class RsEarningsConfirmed(FeatureStrategy):
    name = "rs_earnings_confirmed"
    version = "1"
    description = ("Stocks in the top 10% of relative strength, with a perfect 5/5 uptrend score, within 10% of the "
                   "52-week high, no earnings within 14 days. Added filter: the last earnings reaction was positive "
                   "and within 63 trading days, quarterly sales growth >= 10%, operating margin positive and not "
                   "shrinking vs a year ago. Ranked by relative strength. Exits: stop 2.5x ATR, 15% trailing stop, "
                   "sell if price falls more than 3% below the 50-day average, max hold 120 days.")
    hypothesis = ("Price momentum is partly earnings momentum in disguise. Leaders whose last report was received well "
                  "and whose sales and margins are improving have a fundamental reason to keep rising, while momentum "
                  "without that backing is more often crowding that reverses. Same entry, ranking and exits as the "
                  "parent, so this is a clean A/B test of the earnings filter.")
    needs_fundamentals = True
    min_adv = 1_000_000
    max_new_per_day = 3
    params = {"min_rs": 90, "min_trend": 5, "max_dist_high": -0.10, "min_days_earn": 14,
              "max_days_since": 63, "min_rev_q": 0.10, "atr_mult": 2.5, "trail": 0.15,
              "trend_break": -0.03, "max_hold": 120}

    def eligible(self, t):
        return super().eligible(t) & earnings_clear(self.f, t)

    def score(self, t):
        p = self.params
        f = self.f
        with np.errstate(invalid="ignore"):
            ok = ((f["rs_rank"][t] >= p["min_rs"])
                  & (f["trend_score"][t] >= p["min_trend"])
                  & (f["dist_52w_high"][t] >= p["max_dist_high"])
                  & (f["days_to_earnings_est"][t] > p["min_days_earn"])
                  & (f["earnings_reaction"][t] > 0)
                  & (f["days_since_earnings"][t] <= p["max_days_since"])
                  & (f["rev_growth_q"][t] >= p["min_rev_q"])
                  & (f["op_margin_chg"][t] >= 0)
                  & (f["op_margin"][t] > 0))
            ok = ok & self.eligible(t)
        tie = np.clip(np.nan_to_num(f["rev_growth_q"][t]), 0, 10) * 1e-3
        return np.where(ok, f["rs_rank"][t] + tie, np.nan)

    def plan(self, t, j):
        p = self.params
        c = self.m.close[t, j]
        a = self.f["atr_pct"][t][j]
        if not np.isfinite(a) or a <= 0:
            a = 0.04
        stop = c * (1 - min(p["atr_mult"] * a, 0.5))
        return Signal(self.m.symbols[j], stop=stop, trail_pct=p["trail"], max_hold=p["max_hold"], tag=self.name)

    def exits(self, t, m, held):
        idx = {s: i for i, s in enumerate(self.m.symbols)}
        d = self.f["dist_sma50"][t]
        out = []
        for s in held:
            i = idx.get(s)
            if i is not None and np.isfinite(d[i]) and d[i] < self.params["trend_break"]:
                out.append(s)
        return out

    def why(self, t, j):
        return "RS leader %d, earnings confirmed" % int(self.f["rs_rank"][t][j])
