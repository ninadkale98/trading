"""Buy stocks punished on an earnings report whose filed sales growth sped up and margins improved."""
import numpy as np

from core.backtest.engine import Signal
from core.strategy.base import FeatureStrategy, earnings_clear


class MisreadReportRebound(FeatureStrategy):
    name = "misread_report_rebound"
    version = "1"
    description = ("15-40 trading days after an earnings report where the stock fell 3-12% versus the market, but the filed "
                   "numbers improved: quarterly sales growth >= 5% and at least 2 points faster than the prior report, "
                   "operating margin positive and rising. Company >= $1B, >= $5M/day traded, next report > 25 days away, "
                   "selling has stopped (5-day return > -3%, >= 5% above 52-week low). Skip if guidance was lowered or the "
                   "release tone was negative. Only the first qualifying day per report. Hold up to 50 days, 20% stop and "
                   "20% trailing stop, sell just before the next report.")
    hypothesis = ("Sometimes a stock drops on the headline (whisper numbers, one guidance line, a noisy EPS item) while the "
                  "filed numbers show sales growth speeding up and margins growing. Once the 10-Q is out and analysts update "
                  "their models, the price may recover over weeks, against headline-driven sellers. Research says drift "
                  "usually follows the reaction, so this may well fail.")
    needs_fundamentals = True
    min_adv = 5_000_000
    max_new_per_day = 3
    params = {"dse_min": 15, "dse_max": 40, "drop_min": 0.03, "drop_max": 0.12, "min_growth": 0.05,
              "min_speedup": 0.02, "min_mcap": 1e9, "min_adv20": 5e6, "min_days_next": 25,
              "ret5_min": -0.03, "low_min": 0.05, "speed_cap": 0.3, "stop": 0.20, "trail": 0.20,
              "exit_days_to_earn": 3, "max_hold": 50}

    def helper_speedup(self, t):
        n = len(self.m.symbols)
        dse = self.f["days_since_earnings"][t]
        rg = self.f["rev_growth_q"]
        with np.errstate(invalid="ignore"):
            p = t - np.nan_to_num(dse, nan=-1.0) - 1
            valid = np.isfinite(dse) & (p >= 0) & (p < t + 1)
        pi = np.where(valid, p, 0).astype(int)
        prev = rg[pi, np.arange(n)]
        prev = np.where(valid, prev, np.nan)
        return rg[t] - prev

    def helper_cond(self, t):
        p = self.params
        f = self.f
        if t < 1:
            return np.zeros(len(self.m.symbols), dtype=bool)
        dse = f["days_since_earnings"][t]
        sp = self.helper_speedup(t)
        rgq = f["rev_growth_q"][t]
        gc = f["guidance_change"][t]
        tone = f["release_tone"][t]
        with np.errstate(invalid="ignore"):
            ok = ((dse >= p["dse_min"]) & (dse <= p["dse_max"])
                  & (f["earnings_reaction"][t] >= -p["drop_max"]) & (f["earnings_reaction"][t] <= -p["drop_min"])
                  & (rgq >= p["min_growth"]) & (sp >= p["min_speedup"])
                  & (f["op_margin_chg"][t] > 0) & (f["op_margin"][t] > 0)
                  & (f["market_cap"][t] >= p["min_mcap"]) & (f["adv20"][t] >= p["min_adv20"])
                  & (f["days_to_earnings_est"][t] > p["min_days_next"])
                  & (f["ret_5d"][t] > p["ret5_min"]) & (f["dist_52w_low"][t] >= p["low_min"])
                  & ~(gc == -1) & ~(tone < 0))
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
        return super().eligible(t) & earnings_clear(self.f, t)

    def score(self, t):
        n = len(self.m.symbols)
        if t < 2:
            return np.full(n, np.nan)
        cur = self.helper_cond(t)
        prev = self.helper_cond(t - 1)
        first = cur & ~prev
        sp = np.minimum(self.helper_speedup(t), self.params["speed_cap"])
        drop = -self.f["earnings_reaction"][t]
        a = self.helper_pct(np.nan_to_num(sp), first)
        b = self.helper_pct(np.nan_to_num(drop), first)
        return np.where(first, (a + b) / 2.0, np.nan)

    def plan(self, t, j):
        c = self.m.close[t, j]
        return Signal(self.m.symbols[j], stop=c * (1 - self.params["stop"]), trail_pct=self.params["trail"],
                      max_hold=self.params["max_hold"], tag=self.name)

    def exits(self, t, m, held):
        out = []
        d = self.f["days_to_earnings_est"][t]
        syms = list(self.m.symbols)
        for s in held:
            if s in syms:
                v = d[syms.index(s)]
                if np.isfinite(v) and v <= self.params["exit_days_to_earn"]:
                    out.append(s)
        return out

    def why(self, t, j):
        return "dropped %.0f%% on report; sales growth sped up, margin up" % (
            -100 * self.f["earnings_reaction"][t][j])
