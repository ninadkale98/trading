"""Post-earnings drift: price-scaled EPS beat plus positive reaction, near 52-week high, first eligible day after report."""
import numpy as np

from core.backtest.engine import Signal
from core.strategy.base import FeatureStrategy, earnings_clear


class SueDriftLoose(FeatureStrategy):
    name = "sue_drift_loose"
    version = "1"
    description = ("2-10 trading days after an earnings report, the EPS beat is at least 0.1% of the share price, the stock "
                   "reacted +2% or more versus SPY, sales grew 5%+ year on year, price is within 15% of its 52-week high, "
                   "relative strength rank is 60+ and it is above its 50-day average. Company worth $1B+, trading $5M+/day, "
                   "next report more than 30 days away. Only the first eligible day after each report. Hold up to 55 days "
                   "with a 20% stop and 20% trailing stop; sell before the next report.")
    hypothesis = ("Post-earnings drift survives in liquid stocks mainly when the beat is confirmed by price strength. "
                  "Analysts and funds update slowly after a real beat, so the price keeps drifting for weeks. A looser "
                  "preset of surprise_near_high tests whether its edge was real or a product of tight filters.")
    needs_fundamentals = True
    min_adv = 5_000_000
    max_new_per_day = 3
    params = {"dse_min": 2, "dse_max": 10, "min_sup": 0.001, "min_react": 0.02, "min_revq": 0.05,
              "min_dist_high": -0.15, "min_rs": 60, "min_mcap": 1e9, "min_adv20": 5e6,
              "min_days_next": 30, "stop": 0.20, "trail": 0.20, "max_hold": 55, "exit_days_next": 3}

    def helper_cond(self, s):
        p = self.params
        x = self.f
        with np.errstate(invalid="ignore"):
            ok = ((x["days_since_earnings"][s] >= p["dse_min"]) & (x["days_since_earnings"][s] <= p["dse_max"])
                  & (x["eps_surprise_px"][s] >= p["min_sup"]) & (x["eps_surprise"][s] > 0)
                  & (x["earnings_reaction"][s] >= p["min_react"]) & (x["rev_growth_q"][s] >= p["min_revq"])
                  & (x["dist_52w_high"][s] >= p["min_dist_high"]) & (x["rs_rank"][s] >= p["min_rs"])
                  & (x["dist_sma50"][s] > 0) & (x["market_cap"][s] >= p["min_mcap"])
                  & (x["adv20"][s] >= p["min_adv20"]) & (x["days_to_earnings_est"][s] > p["min_days_next"]))
        return ok

    def eligible(self, t):
        return super().eligible(t) & earnings_clear(self.f, t)

    def helper_pct(self, v, mask):
        out = np.full(len(v), np.nan)
        idx = np.where(mask)[0]
        if len(idx) == 0:
            return out
        order = np.argsort(np.argsort(v[idx]))
        out[idx] = (order + 1.0) / len(idx)
        return out

    def score(self, t):
        n = len(self.m.symbols)
        p = self.params
        cond = self.helper_cond(t) & self.eligible(t)
        if not cond.any():
            return np.full(n, np.nan)
        dse = self.f["days_since_earnings"]
        cur = dse[t]
        seen = np.zeros(n, dtype=bool)
        for k in range(1, p["dse_max"]):
            s = t - k
            if s < 0:
                break
            with np.errstate(invalid="ignore"):
                same = (dse[s] + k == cur) & (dse[s] >= p["dse_min"])
            seen |= same & self.helper_cond(s)
        cond = cond & ~seen
        if not cond.any():
            return np.full(n, np.nan)
        a = np.minimum(self.f["eps_surprise_px"][t], 0.02)
        b = np.minimum(self.f["earnings_reaction"][t], 0.15)
        c = np.minimum(self.f["rev_growth_q"][t], 0.5)
        d = self.f["rs_rank"][t]
        sc = (self.helper_pct(a, cond) + self.helper_pct(b, cond)
              + self.helper_pct(c, cond) + self.helper_pct(d, cond)) / 4.0
        return np.where(cond, sc, np.nan)

    def plan(self, t, j):
        c = self.m.close[t, j]
        return Signal(self.m.symbols[j], stop=c * (1 - self.params["stop"]), target=None,
                      trail_pct=self.params["trail"], max_hold=self.params["max_hold"], tag=self.name)

    def exits(self, t, m, held):
        syms = list(self.m.symbols)
        nxt = self.f["days_to_earnings_est"][t]
        out = []
        for h in held:
            if h in syms:
                v = nxt[syms.index(h)]
                if v == v and v <= self.params["exit_days_next"]:
                    out.append(h)
        return out

    def why(self, t, j):
        return "EPS beat %.2f%% of price, reaction %+.1f%%, near high" % (
            self.f["eps_surprise_px"][t][j] * 100, self.f["earnings_reaction"][t][j] * 100)
