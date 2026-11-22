"""Real EPS beat that the market shrugged off (muted first reaction): buy the late catch-up drift."""
import numpy as np

from core.backtest.engine import Signal
from core.strategy.base import FeatureStrategy, earnings_clear


class QuietBeatDrift(FeatureStrategy):
    name = "quiet_beat_drift"
    version = "1"
    description = ("Company beat EPS estimates by at least 0.2% of share price, but the stock's first reaction was muted "
                   "(between -3% and +2% vs the market). Enter 5-15 trading days after the report, only the first "
                   "eligible day per report, if the price has not fallen back (5-day return > -5%), latest quarter "
                   "sales growth is >= 0, company worth >= $1B, trading >= $5M/day and next report > 30 days away. "
                   "Skip if guidance was lowered or the release tone was negative. Ranked by biggest beat and quietest "
                   "reaction. 20% stop, 20% trailing stop, sell when next earnings are within 3 days, max 50 days.")
    hypothesis = ("Drift after earnings is largest when the first reaction is muted relative to the news (investor "
                  "inattention: DellaVigna & Pollet, Hirshleifer et al.). A beat the price did not reward is still a "
                  "beat; as analysts raise estimates the stock catches up. Guidance and tone vetoes skip beats that "
                  "were muted for a real reason. Proven wrong if excess per trade <= 0.5%, t_excess < 1, "
                  "t_vs_twin < 1, trades < 120, or the top third by surprise does no better than the bottom third.")
    needs_fundamentals = True
    min_adv = 5_000_000
    max_new_per_day = 3
    holds_through_earnings = False
    params = {"min_days": 5, "max_days": 15, "min_surprise": 0.002, "surprise_cap": 0.03,
              "react_lo": -0.03, "react_hi": 0.02, "min_ret5": -0.05, "min_mcap": 1e9,
              "min_adv20": 5e6, "min_to_earn": 30, "exit_to_earn": 3, "stop": 0.20,
              "trail": 0.20, "max_hold": 50}

    def helper_cond(self, t):
        p = self.params
        f = self.f
        ds = f["days_since_earnings"][t]
        sur = f["eps_surprise_px"][t]
        rea = f["earnings_reaction"][t]
        r5 = f["ret_5d"][t]
        rg = f["rev_growth_q"][t]
        mc = f["market_cap"][t]
        adv = f["adv20"][t]
        dte = f["days_to_earnings_est"][t]
        gc = f["guidance_change"][t]
        tone = f["release_tone"][t]
        with np.errstate(invalid="ignore"):
            ok = ((ds >= p["min_days"]) & (ds <= p["max_days"]) & (sur >= p["min_surprise"])
                  & (rea >= p["react_lo"]) & (rea <= p["react_hi"]) & (r5 > p["min_ret5"])
                  & (rg >= 0) & (mc >= p["min_mcap"]) & (adv >= p["min_adv20"])
                  & (dte > p["min_to_earn"]))
            veto = (gc == -1) | (tone < 0)
        return ok & ~veto

    def eligible(self, t):
        return super().eligible(t) & earnings_clear(self.f, t)

    def helper_pct(self, x, mask):
        out = np.full(len(x), np.nan)
        idx = np.where(mask)[0]
        n = len(idx)
        if n == 0:
            return out
        order = np.argsort(x[idx], kind="stable")
        ranks = np.empty(n)
        ranks[order] = np.arange(n)
        out[idx] = ranks / max(n - 1, 1)
        return out

    def score(self, t):
        n = len(self.m.symbols)
        if t < 1:
            return np.full(n, np.nan)
        cond = self.helper_cond(t)
        prev = self.helper_cond(t - 1)
        mask = cond & ~prev & self.eligible(t)
        sur = np.minimum(self.f["eps_surprise_px"][t], self.params["surprise_cap"])
        rea = self.f["earnings_reaction"][t]
        s = self.helper_pct(sur, mask) - self.helper_pct(rea, mask)
        return np.where(mask, s, np.nan)

    def exits(self, t, m, held):
        out = []
        syms = list(self.m.symbols)
        dte = self.f["days_to_earnings_est"][t]
        for s in held:
            if s in syms:
                v = dte[syms.index(s)]
                if v == v and v <= self.params["exit_to_earn"]:
                    out.append(s)
        return out

    def plan(self, t, j):
        c = self.m.close[t, j]
        p = self.params
        return Signal(self.m.symbols[j], stop=c * (1 - p["stop"]), target=None,
                      trail_pct=p["trail"], max_hold=p["max_hold"], tag=self.name)
