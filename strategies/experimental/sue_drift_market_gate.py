"""Post-earnings drift on positive-surprise, positive-reaction growers, entered only when SPY's 6-month trend is up."""
import numpy as np

from core.backtest.engine import Signal
from core.strategy.base import FeatureStrategy, earnings_clear


class SueDriftMarketGate(FeatureStrategy):
    name = "sue_drift_market_gate"
    version = "1"
    description = ("Stocks 2-10 trading days after an earnings reaction with a positive EPS surprise (scaled by price), "
                   "a reaction of at least +2% vs SPY, revenue growth of at least 5%, market cap >= $1B and "
                   "$5M/day traded, with the next report more than 30 days away. Only the first eligible day per report, "
                   "and only when SPY's 6-month return is positive and its 3-month return is above -5% "
                   "(derived from the stocks' own return minus relative-strength features). Ranked by surprise plus "
                   "reaction percentile. 20% stop, 20% trailing stop, exit before the next report, max 55 days.")
    hypothesis = ("Post-earnings drift is relative to the market, but in bear markets forced fund selling swamps the slow "
                  "buying that follows good earnings news. Skipping entries when SPY's trend is down should remove most "
                  "bear-market losses (e.g. 2022) while costing little edge elsewhere.")
    needs_fundamentals = True
    min_adv = 5_000_000
    max_new_per_day = 3
    params = {"min_days": 2, "max_days": 10, "min_surprise": 0.001, "surprise_cap": 0.05, "min_reaction": 0.02,
              "min_rev_growth": 0.05, "min_mcap": 1e9, "min_adv20": 5e6, "min_days_to_next": 30,
              "spy120_min": 0.0, "spy60_min": -0.05, "stop": 0.20, "trail": 0.20,
              "exit_days_to_earnings": 3, "max_hold": 55}

    def helper_base(self, t):
        p = self.params
        ds = self.f["days_since_earnings"][t]
        sp = self.f["eps_surprise_px"][t]
        rx = self.f["earnings_reaction"][t]
        rg = self.f["rev_growth_yoy"][t]
        mc = self.f["market_cap"][t]
        adv = self.f["adv20"][t]
        dn = self.f["days_to_earnings_est"][t]
        with np.errstate(invalid="ignore"):
            return ((ds >= p["min_days"]) & (ds <= p["max_days"]) & (sp >= p["min_surprise"])
                    & (rx >= p["min_reaction"]) & (rg >= p["min_rev_growth"]) & (mc >= p["min_mcap"])
                    & (adv >= p["min_adv20"]) & (dn > p["min_days_to_next"]))

    def helper_gate(self, t):
        with np.errstate(invalid="ignore"):
            a = self.f["ret_120d"][t] - self.f["rs_spy_120"][t]
            b = self.f["ret_60d"][t] - self.f["rs_spy_60"][t]
            if not np.isfinite(a).any() or not np.isfinite(b).any():
                return False
            s120 = np.nanmedian(a)
            s60 = np.nanmedian(b)
        return bool(s120 > self.params["spy120_min"] and s60 > self.params["spy60_min"])

    def eligible(self, t):
        return super().eligible(t) & earnings_clear(self.f, t)

    def score(self, t):
        n = len(self.m.symbols)
        out = np.full(n, np.nan)
        if t < 1 or not self.helper_gate(t):
            return out
        ok = self.helper_base(t) & ~self.helper_base(t - 1) & self.eligible(t)
        idx = np.where(ok)[0]
        if len(idx) == 0:
            return out
        sp = np.minimum(self.f["eps_surprise_px"][t][idx], self.params["surprise_cap"])
        rx = self.f["earnings_reaction"][t][idx]
        k = len(idx)
        r1 = np.argsort(np.argsort(sp)) / max(k - 1, 1)
        r2 = np.argsort(np.argsort(rx)) / max(k - 1, 1)
        out[idx] = r1 + r2
        return out

    def plan(self, t, j):
        c = self.m.close[t, j]
        return Signal(self.m.symbols[j], stop=c * (1 - self.params["stop"]), trail_pct=self.params["trail"],
                      max_hold=self.params["max_hold"], tag=self.name)

    def exits(self, t, m, held):
        dn = self.f["days_to_earnings_est"][t]
        syms = np.asarray(self.m.symbols)
        out = []
        for h in held:
            s = h if isinstance(h, str) else h.symbol
            w = np.where(syms == s)[0]
            if len(w) == 0:
                continue
            v = dn[w[0]]
            if np.isfinite(v) and v <= self.params["exit_days_to_earnings"]:
                out.append(s)
        return out

    def why(self, t, j):
        return "post-earnings drift, SPY trend up"
