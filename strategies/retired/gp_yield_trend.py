"""Cheap gross profit (gross margin / price-to-sales) in profitable stocks that are already in a long-term uptrend."""
import numpy as np

from core.backtest.engine import Signal
from core.strategy.base import FeatureStrategy, earnings_clear


class GpYieldTrend(FeatureStrategy):
    name = "gp_yield_trend"
    version = "1"
    description = ("Gross profit per dollar of company value (gross margin / price-to-sales) in profitable, "
                   "moderately indebted companies worth at least $2B that are above a rising 200-day average with "
                   "relative strength rank 50-95. Score blends gp yield (x2), relative strength and operating margin "
                   "change; buys only the top 10% of eligible stocks. Sells if price falls 5% below the 200-day "
                   "average, with a 25% stop and 120-day max hold. Holds through earnings once in.")
    hypothesis = ("Gross profitability predicts returns about as well as cheapness (Novy-Marx), and the market "
                  "undervalues steady but unexciting profit. Gross margin / ps combines both. Requiring an uptrend "
                  "avoids cheap stocks that keep getting cheaper. Investors chase exciting stories and neglect dull "
                  "profitable firms. Wrong if t_vs_twin < 2.0, the excess lives in one sector or year, or the top "
                  "score third does not beat the bottom third.")
    needs_fundamentals = True
    min_adv = 10_000_000
    max_new_per_day = 3
    holds_through_earnings = True
    params = {"min_mcap": 2e9, "min_adv": 1e7, "min_gm": 0.30, "max_de": 1.5, "rs_lo": 50, "rs_hi": 95,
              "min_days_earn": 7, "top_pct": 90, "stop": 0.25, "exit_dist": -0.05, "max_hold": 120}

    def helper_rank(self, v):
        out = np.full(len(v), np.nan)
        idx = np.where(np.isfinite(v))[0]
        n = len(idx)
        if n == 0:
            return out
        order = np.argsort(v[idx], kind="stable")
        r = np.empty(n)
        r[order] = np.arange(n)
        out[idx] = r / max(n - 1, 1)
        return out

    def eligible(self, t):
        p = self.params
        f = self.f
        base = super().eligible(t)
        ps = f["ps"][t]
        with np.errstate(invalid="ignore", divide="ignore"):
            ok = ((f["market_cap"][t] >= p["min_mcap"]) & (f["adv20"][t] >= p["min_adv"])
                  & (f["gross_margin"][t] >= p["min_gm"]) & (f["op_margin"][t] > 0)
                  & (f["fcf_yield"][t] > 0) & (f["debt_to_equity"][t] >= 0)
                  & (f["debt_to_equity"][t] <= p["max_de"]) & (f["dist_sma200"][t] > 0)
                  & (f["sma200_slope"][t] > 0) & (f["rs_rank"][t] >= p["rs_lo"])
                  & (f["rs_rank"][t] <= p["rs_hi"]) & (f["days_to_earnings_est"][t] > p["min_days_earn"])
                  & (ps > 0))
        return base & ok

    def score(self, t):
        p = self.params
        f = self.f
        n = len(self.m.symbols)
        el = self.eligible(t)
        with np.errstate(invalid="ignore", divide="ignore"):
            gp = np.where(f["ps"][t] > 0, f["gross_margin"][t] / f["ps"][t], np.nan)
        valid = el & np.isfinite(gp) & np.isfinite(f["rs_rank"][t]) & np.isfinite(f["op_margin_chg"][t])
        if valid.sum() < 5:
            return np.full(n, np.nan)
        g = self.helper_rank(np.where(valid, gp, np.nan))
        r = self.helper_rank(np.where(valid, f["rs_rank"][t], np.nan))
        o = self.helper_rank(np.where(valid, f["op_margin_chg"][t], np.nan))
        s = (2 * g + r + o) / 4.0
        s = np.where(valid, s, np.nan)
        thr = np.nanpercentile(s[valid], p["top_pct"])
        with np.errstate(invalid="ignore"):
            return np.where(s >= thr, s, np.nan)

    def plan(self, t, j):
        c = self.m.close[t, j]
        return Signal(self.m.symbols[j], stop=c * (1 - self.params["stop"]), max_hold=self.params["max_hold"],
                      tag=self.name)

    def exits(self, t, m, held):
        d = self.f["dist_sma200"][t]
        syms = list(self.m.symbols)
        out = []
        for s in held:
            if s in syms:
                v = d[syms.index(s)]
                if np.isfinite(v) and v < self.params["exit_dist"]:
                    out.append(s)
        return out

    def why(self, t, j):
        return "high gross-profit yield, uptrend, top-decile blended score"
