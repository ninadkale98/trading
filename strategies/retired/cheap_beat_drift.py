"""Post-earnings drift: strong earnings reaction at cheap, cash-generating, profitable companies."""
import numpy as np

from core.backtest.engine import Signal
from core.strategy.base import FeatureStrategy


class CheapBeatDrift(FeatureStrategy):
    name = "cheap_beat_drift"
    version = "1"
    description = ("2 to 10 trading days after an earnings report where the stock beat SPY by at least 4% on the reaction day, "
                   "at a company that is cheap (P/E 4-18 or free-cash-flow yield >= 6%), price/sales <= 3, profitable, "
                   "with positive free cash flow, modest debt, not in a collapse (within 15% of its 200-day average), "
                   "worth >= $1B and trading >= $5M/day. Only the first qualifying day per report. Next report at least "
                   "30 days away. Hold up to 55 days with 20% stop and 20% trailing stop; sell just before the next report.")
    hypothesis = ("Investors stay pessimistic about cheap companies and are slow to believe good news there, so a strong "
                  "positive earnings reaction at a cheap, cash-generating company keeps drifting as value funds and analysts "
                  "re-rate a stock they had written off (La Porta et al. 1997; Skinner and Sloan).")
    needs_fundamentals = True
    min_adv = 5_000_000
    max_new_per_day = 3
    holds_through_earnings = False
    params = {"min_days": 2, "max_days": 10, "min_react": 0.04, "react_cap": 0.25, "fcf_cap": 0.20,
              "pe_lo": 4, "pe_hi": 18, "fcf_value": 0.06, "max_ps": 3.0, "max_de": 2.0,
              "min_sma200": -0.15, "min_mcap": 1e9, "min_adv20": 5e6, "min_next": 30,
              "exit_days": 3, "stop": 0.20, "trail": 0.20, "max_hold": 55}

    def helper_cond(self, d):
        p = self.params
        g = lambda n: self.f[n][d]
        dse, rx, pe, fy = g("days_since_earnings"), g("earnings_reaction"), g("pe"), g("fcf_yield")
        de, nxt = g("debt_to_equity"), g("days_to_earnings_est")
        with np.errstate(invalid="ignore"):
            value = ((pe >= p["pe_lo"]) & (pe <= p["pe_hi"])) | (fy >= p["fcf_value"])
            ok = ((dse >= p["min_days"]) & (dse <= p["max_days"]) & (rx >= p["min_react"]) & value
                  & (g("ps") <= p["max_ps"]) & (g("net_margin") > 0) & (fy > 0)
                  & (np.isnan(de) | (de < p["max_de"]))
                  & (g("dist_sma200") >= p["min_sma200"]) & (g("market_cap") >= p["min_mcap"])
                  & (g("adv20") >= p["min_adv20"]) & (nxt > p["min_next"]))
        return ok

    def eligible(self, t):
        base = super().eligible(t)
        if t < 1:
            return np.zeros(len(self.m.symbols), dtype=bool)
        cur = self.helper_cond(t)
        prev = self.helper_cond(t - 1)
        d0, d1 = self.f["days_since_earnings"][t - 1], self.f["days_since_earnings"][t]
        with np.errstate(invalid="ignore"):
            same_report = d1 == d0 + 1
        already = prev & same_report
        return base & cur & ~already

    def helper_pct(self, v, ok):
        out = np.full(len(v), np.nan)
        idx = np.where(ok & ~np.isnan(v))[0]
        n = len(idx)
        if n == 0:
            return out
        order = np.argsort(v[idx], kind="stable")
        r = np.empty(n)
        r[order] = np.arange(n)
        out[idx] = (r + 1) / n
        return out

    def score(self, t):
        p = self.params
        n = len(self.m.symbols)
        ok = self.eligible(t)
        if not ok.any():
            return np.full(n, np.nan)
        rx = np.minimum(self.f["earnings_reaction"][t], p["react_cap"])
        fy = np.minimum(self.f["fcf_yield"][t], p["fcf_cap"])
        s = (self.helper_pct(rx, ok) + self.helper_pct(fy, ok)) / 2.0
        return np.where(ok, s, np.nan)

    def exits(self, t, m, held):
        nxt = self.f["days_to_earnings_est"][t]
        idx = {s: i for i, s in enumerate(self.m.symbols)}
        out = []
        for s in held:
            j = idx.get(s)
            if j is None:
                continue
            v = nxt[j]
            if not np.isnan(v) and v <= self.params["exit_days"]:
                out.append(s)
        return out

    def plan(self, t, j):
        c = self.m.close[t, j]
        p = self.params
        return Signal(self.m.symbols[j], stop=c * (1 - p["stop"]), target=None, trail_pct=p["trail"],
                      max_hold=p["max_hold"], tag=self.name)

    def why(self, t, j):
        return "earnings reaction %+.1f%%, fcf yield %.1f%%" % (
            100 * self.f["earnings_reaction"][t][j], 100 * self.f["fcf_yield"][t][j])
