"""Insider cluster buying in a fallen but profitable small/mid-cap company with positive free cash flow and modest debt."""
import numpy as np

from core.backtest.engine import Signal
from core.strategy.base import FeatureStrategy, earnings_clear


class InsiderDipQuality(FeatureStrategy):
    name = "insider_dip_quality"
    version = "1"
    description = ("At least 2 different insiders bought on the open market within 90 days, and the buyer count rose in the "
                   "last 5 trading days. Net insider buying is positive, company worth $500M-$10B, trading >= $2M/day, "
                   "price at least 20% below its 52-week high, positive free cash flow yield, debt-to-equity between 0 and 2, "
                   "no earnings within 14 days. Ranked by net insider buying relative to company size. Hold up to 100 "
                   "trading days with a stop 25% below entry, holding through later earnings reports.")
    hypothesis = ("Insiders know their business better than outside sellers, who may be reacting to a falling price. Buying "
                  "after a decline is less likely to be routine, and the effect is larger in smaller companies. The other "
                  "side is momentum and tax-driven selling plus thin analyst coverage. Requiring positive cash flow avoids "
                  "insiders simply supporting a failing company.")
    needs_fundamentals = True
    min_adv = 2_000_000
    max_new_per_day = 3
    params = {"min_buyers": 2, "fresh_days": 5, "min_mcap": 5e8, "max_mcap": 1e10, "min_drop": -0.20,
              "max_de": 2.0, "min_earn_days": 14, "stop": 0.25, "max_hold": 100}

    def eligible(self, t):
        return super().eligible(t) & earnings_clear(self.f, t)

    def score(self, t):
        p = self.params
        n = len(self.m.symbols)
        if t < p["fresh_days"]:
            return np.full(n, np.nan)
        f = self.f
        now = f["insider_buyers_90d"][t]
        before = f["insider_buyers_90d"][t - p["fresh_days"]]
        net = f["insider_net_buy_90d"][t]
        mc = f["market_cap"][t]
        de = f["debt_to_equity"][t]
        with np.errstate(invalid="ignore"):
            ok = ((now >= p["min_buyers"]) & (now > np.nan_to_num(before)) & (net > 0)
                  & (mc >= p["min_mcap"]) & (mc <= p["max_mcap"])
                  & (f["adv20"][t] >= self.min_adv)
                  & (f["dist_52w_high"][t] <= p["min_drop"])
                  & (f["fcf_yield"][t] > 0)
                  & (de >= 0) & (de <= p["max_de"])
                  & (f["days_to_earnings_est"][t] > p["min_earn_days"]))
        return np.where(ok, net, np.nan)

    def plan(self, t, j):
        c = self.m.close[t, j]
        return Signal(self.m.symbols[j], stop=c * (1 - self.params["stop"]), max_hold=self.params["max_hold"], tag=self.name)

    def why(self, t, j):
        return "insiders buying after a drop; profitable, modest debt"
