"""Operating margin turns up year over year at a report with a positive price reaction; ride the slow estimate revisions."""
import numpy as np

from core.backtest.engine import Signal
from core.strategy.base import FeatureStrategy


class MarginInflectionDrift(FeatureStrategy):
    name = "margin_inflection_drift"
    version = "1"
    description = ("15-40 trading days after an earnings report: the stock reacted up at least 1% vs the market, the year-over-year "
                   "change in operating margin is now >= +1 point but was <= 0 the day before the reaction (trend flipped, 10-Q filed), "
                   "latest-quarter revenue growth is non-negative, gross margin >= 15%, company >= $1B, trading >= $5M/day, "
                   "next report > 25 days away, guidance not lowered. First eligible day per report only. Ranked by margin change and "
                   "reaction. Hold up to 50 days with 20% stop and 20% trailing stop; sell just before the next report.")
    hypothesis = ("Analysts and investors extrapolate recent margin trends. When the year-over-year operating margin change flips from "
                  "negative to positive, models keep shrinking margins too long and estimate revisions arrive over the next 1-3 months. "
                  "A positive reaction shows the market noticed, but slow revisions mean it has not fully priced it in.")
    needs_fundamentals = True
    min_adv = 5_000_000
    max_new_per_day = 3
    params = {"dse_min": 15, "dse_max": 40, "min_react": 0.01, "react_cap": 0.25, "min_opm_chg": 0.01,
              "opm_cap": 0.15, "min_gm": 0.15, "min_mcap": 1e9, "min_adv20": 5e6, "min_days_to_earn": 25,
              "exit_days_to_earn": 3, "stop": 0.20, "trail": 0.20, "max_hold": 50}

    def helper_cond(self, u):
        p = self.params
        n = len(self.m.symbols)
        if u < 1:
            return np.zeros(n, dtype=bool)
        dse = self.f["days_since_earnings"][u]
        react = self.f["earnings_reaction"][u]
        opm = self.f["op_margin_chg"][u]
        with np.errstate(invalid="ignore"):
            pidx = u - np.nan_to_num(dse, nan=-1.0) - 1
            valid = np.isfinite(dse) & (pidx >= 0)
            pi = np.where(valid, pidx, 0).astype(int)
            opm_p = self.f["op_margin_chg"][pi, np.arange(n)]
            ok = (valid & (dse >= p["dse_min"]) & (dse <= p["dse_max"])
                  & (react >= p["min_react"])
                  & (opm >= p["min_opm_chg"]) & (opm_p <= 0)
                  & (self.f["rev_growth_q"][u] >= 0)
                  & (self.f["gross_margin"][u] >= p["min_gm"])
                  & (self.f["market_cap"][u] >= p["min_mcap"])
                  & (self.f["adv20"][u] >= p["min_adv20"])
                  & (self.f["days_to_earnings_est"][u] > p["min_days_to_earn"])
                  & ~(self.f["guidance_change"][u] == -1))
        return ok

    def helper_pct(self, x, mask):
        out = np.full(len(x), np.nan)
        idx = np.where(mask)[0]
        if len(idx) == 0:
            return out
        order = np.argsort(np.argsort(x[idx]))
        out[idx] = (order + 1.0) / len(idx)
        return out

    def eligible(self, t):
        return super().eligible(t)

    def score(self, t):
        p = self.params
        n = len(self.m.symbols)
        ok = self.helper_cond(t)
        if not ok.any():
            return np.full(n, np.nan)
        ok = ok & ~self.helper_cond(t - 1)
        if not ok.any():
            return np.full(n, np.nan)
        opm = np.minimum(self.f["op_margin_chg"][t], p["opm_cap"])
        rea = np.minimum(self.f["earnings_reaction"][t], p["react_cap"])
        s = (self.helper_pct(opm, ok) + self.helper_pct(rea, ok)) / 2.0
        return np.where(ok, s, np.nan)

    def plan(self, t, j):
        c = self.m.close[t, j]
        return Signal(self.m.symbols[j], stop=c * (1 - self.params["stop"]), target=None,
                      trail_pct=self.params["trail"], max_hold=self.params["max_hold"], tag=self.name)

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
        return "op margin YoY turned up (%.1f pts) with reaction %.1f%%" % (
            self.f["op_margin_chg"][t][j] * 100, self.f["earnings_reaction"][t][j] * 100)
