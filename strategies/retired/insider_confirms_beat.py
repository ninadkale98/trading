"""Insider buys fresh after a good earnings reaction: insiders confirming the beat, expecting post-earnings drift."""
import numpy as np

from core.backtest.engine import Signal
from core.strategy.base import FeatureStrategy


class InsiderConfirmsBeat(FeatureStrategy):
    name = "insider_confirms_beat"
    version = "1"
    description = ("3-30 trading days after an earnings report where the stock beat SPY by at least 3%, a new insider "
                   "buyer appears (distinct buyers in 90 days rose vs 5 days earlier) with net insider buying > 0. "
                   "Company worth >= $500M, trading >= $2M/day, next report more than 30 days away. Only the first "
                   "qualifying day per report. Hold up to 60 days with a 20% stop and 25% trailing stop; sell before "
                   "the next report.")
    hypothesis = ("Insiders can only trade a few days after a report, so timing is mechanical, but direction is not: "
                  "buying right after the stock jumped means paying a higher price with personal money, a sign they "
                  "think the good news is not fully priced. That should strengthen post-earnings drift. Mirror of "
                  "insider_buys_the_drop; tests whether insider buying adds information beyond marking dips.")
    needs_fundamentals = True
    min_adv = 2_000_000
    max_new_per_day = 3
    holds_through_earnings = False
    params = {"dse_min": 3, "dse_max": 30, "min_react": 0.03, "lag": 5, "min_mcap": 5e8,
              "min_adv20": 2e6, "min_days_to_earn": 30, "react_cap": 0.25,
              "stop": 0.20, "trail": 0.25, "max_hold": 60, "exit_days": 3}

    def helper_cond(self, t):
        p = self.params
        n = len(self.m.symbols)
        if t < p["lag"]:
            return np.zeros(n, dtype=bool)
        f = self.f
        dse = f["days_since_earnings"][t]
        react = f["earnings_reaction"][t]
        now = f["insider_buyers_90d"][t]
        before = f["insider_buyers_90d"][t - p["lag"]]
        net = f["insider_net_buy_90d"][t]
        mcap = f["market_cap"][t]
        adv = f["adv20"][t]
        dte = f["days_to_earnings_est"][t]
        with np.errstate(invalid="ignore"):
            ok = ((dse >= p["dse_min"]) & (dse <= p["dse_max"]) & (react >= p["min_react"])
                  & (now > np.nan_to_num(before)) & (net > 0) & (mcap >= p["min_mcap"])
                  & (adv >= p["min_adv20"]) & (dte > p["min_days_to_earn"]))
        return np.nan_to_num(ok, nan=0).astype(bool)

    def eligible(self, t):
        return super().eligible(t) & self.helper_cond(t)

    def helper_pct(self, x):
        out = np.full(len(x), np.nan)
        idx = np.where(~np.isnan(x))[0]
        if len(idx) == 0:
            return out
        order = np.argsort(np.argsort(x[idx]))
        out[idx] = order / max(len(idx) - 1, 1)
        return out

    def score(self, t):
        p = self.params
        n = len(self.m.symbols)
        cond = self.helper_cond(t)
        if not cond.any():
            return np.full(n, np.nan)
        dse = self.f["days_since_earnings"][t]
        first = cond.copy()
        for k in range(1, p["dse_max"] - p["dse_min"] + 1):
            if t - k < 0:
                break
            prev = self.helper_cond(t - k)
            with np.errstate(invalid="ignore"):
                same_report = (dse - k) >= p["dse_min"]
            first &= ~(prev & same_report)
            if not first.any():
                break
        net = np.where(first, self.f["insider_net_buy_90d"][t], np.nan)
        react = np.where(first, np.minimum(self.f["earnings_reaction"][t], p["react_cap"]), np.nan)
        s = (self.helper_pct(net) + self.helper_pct(react)) / 2.0
        return np.where(first, s, np.nan)

    def plan(self, t, j):
        c = self.m.close[t, j]
        return Signal(self.m.symbols[j], stop=c * (1 - self.params["stop"]), target=None,
                      trail_pct=self.params["trail"], max_hold=self.params["max_hold"], tag=self.name)

    def exits(self, t, m, held):
        dte = self.f["days_to_earnings_est"][t]
        syms = list(self.m.symbols)
        out = []
        for s in held:
            if s in syms:
                v = dte[syms.index(s)]
                if not np.isnan(v) and v <= self.params["exit_days"]:
                    out.append(s)
        return out

    def why(self, t, j):
        return "new insider buyer after +%.0f%% earnings reaction" % (100 * self.f["earnings_reaction"][t][j])
