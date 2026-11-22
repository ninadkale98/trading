"""Insider buys after a punished earnings report at a company with shrinking sales, losses or thin margins."""
import numpy as np

from core.backtest.engine import Signal
from core.strategy.base import FeatureStrategy, earnings_clear


class InsiderDropTroubled(FeatureStrategy):
    name = "insider_drop_troubled"
    version = "1"
    description = ("After an earnings report the stock fell at least 5% (but not more than 30%) vs the market, 2-40 trading "
                   "days ago, and a new insider buyer joined within the last 5 days (1-4 buyers in 90 days, net insider "
                   "buying positive). Company worth >= $500M, trading >= $2M/day, next report > 20 days away. The company "
                   "must look troubled: falling quarterly sales, no operating profit, or gross margin under 20%. First "
                   "qualifying day per report only. 25% stop, hold up to 80 days, through the next report.")
    hypothesis = ("Troubled companies that report badly get dumped mechanically by quality and momentum funds. An insider "
                  "buying into that is taking a visible, non-routine bet (opportunistic buys, Cohen-Malloy-Pomorski), "
                  "while the selling is forced rather than informed. The reward concentrates where the fear is.")
    needs_fundamentals = True
    min_adv = 2_000_000
    max_new_per_day = 3
    holds_through_earnings = True
    params = {"react_min": -0.05, "react_cap": -0.30, "dse_min": 2, "dse_max": 40, "fresh_days": 5,
              "min_buyers": 1, "max_buyers": 4, "min_mcap": 5e8, "min_dte": 20, "net_cap": 0.01,
              "gm_floor": 0.20, "stop": 0.25, "max_hold": 80}
    cache = {}

    def helper_cond(self, t):
        key = (id(self.m), t)
        if key in self.cache:
            return self.cache[key]
        p = self.params
        n = len(self.m.symbols)
        if t < p["fresh_days"]:
            return np.zeros(n, dtype=bool)
        f = self.f
        buyers = f["insider_buyers_90d"][t]
        before = np.nan_to_num(f["insider_buyers_90d"][t - p["fresh_days"]])
        with np.errstate(invalid="ignore"):
            react = f["earnings_reaction"][t]
            dse = f["days_since_earnings"][t]
            troubled = ((f["rev_growth_q"][t] < 0) | (f["op_margin"][t] <= 0) | (f["gross_margin"][t] < p["gm_floor"]))
            ok = ((react <= p["react_min"]) & (react >= p["react_cap"])
                  & (dse >= p["dse_min"]) & (dse <= p["dse_max"])
                  & (buyers > before) & (buyers >= p["min_buyers"]) & (buyers <= p["max_buyers"])
                  & (f["insider_net_buy_90d"][t] > 0)
                  & (f["market_cap"][t] >= p["min_mcap"])
                  & (f["adv20"][t] >= self.min_adv)
                  & (f["days_to_earnings_est"][t] > p["min_dte"])
                  & troubled)
        ok = np.asarray(ok, dtype=bool)
        self.cache[key] = ok
        return ok

    def eligible(self, t):
        return super().eligible(t)

    def score(self, t):
        p = self.params
        n = len(self.m.symbols)
        out = np.full(n, np.nan)
        ok = self.helper_cond(t) & self.eligible(t)
        if not ok.any():
            return out
        dse = self.f["days_since_earnings"][t]
        first = ok.copy()
        kmax = int(min(p["dse_max"], t))
        for k in range(1, kmax + 1):
            with np.errstate(invalid="ignore"):
                same = dse >= k
            first &= ~(self.helper_cond(t - k) & same)
            if not first.any():
                return out
        net = np.minimum(np.nan_to_num(self.f["insider_net_buy_90d"][t]), p["net_cap"])
        react = np.nan_to_num(self.f["earnings_reaction"][t])
        sc = net - react * 1e-4
        return np.where(first, sc, np.nan)

    def plan(self, t, j):
        c = self.m.close[t, j]
        return Signal(self.m.symbols[j], stop=c * (1 - self.params["stop"]),
                      max_hold=self.params["max_hold"], tag=self.name)
