"""Insider buys after a punished earnings report at a company whose sales still grow and which still makes an operating profit."""
import numpy as np

from core.backtest.engine import Signal
from core.strategy.base import FeatureStrategy


class InsiderDropIntact(FeatureStrategy):
    name = "insider_drop_intact"
    version = "1"
    description = ("Stock fell at least 5% vs SPY on its last earnings reaction (2-40 trading days ago) and a new insider "
                   "buyer appeared in the last 5 days (1-4 buyers, net buying positive). The business is still healthy: "
                   "quarterly sales growth >= 0, operating margin > 0, gross margin >= 20%. Market cap >= $500M, "
                   "trading >= $2M/day, next report more than 20 days away. First qualifying day per report only. "
                   "Hold up to 80 trading days through the next report with a 25% stop.")
    hypothesis = ("Insider buying after a punished report works best when the reaction overshot, and overshoot is most "
                  "likely when the business is intact: sales growing and profitable. Insiders buying right after the "
                  "report are betting on a business they can see is healthy, while insider buying at troubled companies "
                  "is more often a show of support.")
    needs_fundamentals = True
    min_adv = 2_000_000
    max_new_per_day = 3
    holds_through_earnings = True
    params = {"react": -0.05, "dmin": 2, "dmax": 40, "fresh_days": 5, "max_buyers": 4,
              "min_rev_q": 0.0, "min_gm": 0.2, "min_mcap": 5e8, "min_adv20": 2e6,
              "min_dte": 20, "net_cap": 0.01, "react_cap": 0.30, "stop": 0.25, "max_hold": 80}

    def helper_core(self, s):
        """Insider + fundamentals conditions on day s (not reaction/timing)."""
        p = self.params
        f = self.f
        now = f["insider_buyers_90d"][s]
        before = f["insider_buyers_90d"][s - p["fresh_days"]]
        with np.errstate(invalid="ignore"):
            ok = ((now > np.nan_to_num(before)) & (now <= p["max_buyers"])
                  & (f["insider_net_buy_90d"][s] > 0)
                  & (f["rev_growth_q"][s] >= p["min_rev_q"])
                  & (f["op_margin"][s] > 0)
                  & (f["gross_margin"][s] >= p["min_gm"])
                  & (f["market_cap"][s] >= p["min_mcap"]))
        return ok

    def eligible(self, t):
        base = super().eligible(t)
        p = self.params
        with np.errstate(invalid="ignore"):
            ok = ((self.f["adv20"][t] >= p["min_adv20"])
                  & (self.f["days_to_earnings_est"][t] > p["min_dte"]))
        return base & ok

    def score(self, t):
        p = self.params
        n = len(self.m.symbols)
        if t < p["fresh_days"] + 1:
            return np.full(n, np.nan)
        f = self.f
        dse = f["days_since_earnings"][t]
        react = f["earnings_reaction"][t]
        with np.errstate(invalid="ignore"):
            ok = ((react <= p["react"]) & (dse >= p["dmin"]) & (dse <= p["dmax"]))
        ok = ok & self.helper_core(t) & self.eligible(t)
        if not ok.any():
            return np.full(n, np.nan)
        # first qualifying day per report only
        for k in range(1, p["dmax"]):
            s = t - k
            if s < p["fresh_days"]:
                break
            with np.errstate(invalid="ignore"):
                same = (f["days_since_earnings"][s] == dse - k) & (dse - k >= p["dmin"])
            same = np.nan_to_num(same, nan=0).astype(bool)
            if not (same & ok).any():
                continue
            ok = ok & ~(same & self.helper_core(s))
        idx = np.where(ok)[0]
        out = np.full(n, np.nan)
        if len(idx) == 0:
            return out
        net = np.minimum(f["insider_net_buy_90d"][t][idx], p["net_cap"])
        rx = np.minimum(-react[idx], p["react_cap"])

        def pct(v):
            r = np.argsort(np.argsort(v)).astype(float)
            return r / max(len(v) - 1, 1)

        out[idx] = pct(net) + pct(rx)
        return out

    def plan(self, t, j):
        c = self.m.close[t, j]
        return Signal(self.m.symbols[j], stop=c * (1 - self.params["stop"]),
                      max_hold=self.params["max_hold"], tag=self.name)
