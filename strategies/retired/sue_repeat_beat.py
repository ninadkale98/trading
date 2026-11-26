"""Second consecutive earnings beat confirmed by a positive price reaction: post-earnings drift continuation."""
import numpy as np

from core.backtest.engine import Signal
from core.strategy.base import FeatureStrategy


class SueRepeatBeat(FeatureStrategy):
    name = "sue_repeat_beat"
    version = "1"
    description = ("Stock reported 2-10 trading days ago with an EPS beat (scaled by price, >= 0.1%), a market-adjusted "
                   "reaction of at least +2%, and quarterly sales growth of at least 5%. The report before it must also "
                   "have been a beat. Company worth >= $1B, trading >= $5M/day, next report more than 30 days away. "
                   "Only the first qualifying day per report. Exit with 20% stop, 20% trailing stop, before the next "
                   "report (<= 3 days), or after 55 trading days.")
    hypothesis = ("Earnings surprises repeat (Bernard & Thomas): analysts anchor on old numbers, so a company that beat "
                  "last quarter and beat again is in a run of upward revisions the price keeps catching up to. A one-off "
                  "beat is more often noise or one-time items.")
    needs_fundamentals = True
    min_adv = 5_000_000
    max_new_per_day = 3
    params = {"min_surprise": 0.001, "cap_surprise": 0.05, "min_reaction": 0.02, "cap_reaction": 0.25,
              "min_rev_growth": 0.05, "min_mcap": 1e9, "min_adv20": 5e6, "min_days_to_next": 30,
              "dse_min": 2, "dse_max": 10, "prev_gap": 40, "stop": 0.20, "trail": 0.20,
              "exit_days_to_earnings": 3, "max_hold": 55}

    def helper_prev(self, t, dse):
        """Surprise value at day p = t - dse - 1 per stock (NaN if unknown) and days_since_earnings at p."""
        n = len(self.m.symbols)
        with np.errstate(invalid="ignore"):
            d = np.where(np.isnan(dse), -1, dse).astype(int)
        p = t - d - 1
        valid = (p >= 0) & ~np.isnan(dse)
        pc = np.where(valid, p, 0)
        cols = np.arange(n)
        sp = np.asarray(self.f["eps_surprise_px"])[pc, cols]
        dp = np.asarray(self.f["days_since_earnings"])[pc, cols]
        sp = np.where(valid, sp, np.nan)
        dp = np.where(valid, dp, np.nan)
        return sp, dp

    def helper_ok(self, t):
        p = self.params
        n = len(self.m.symbols)
        if t < 1:
            return np.zeros(n, dtype=bool)
        dse = self.x("days_since_earnings", t)
        sur = self.x("eps_surprise_px", t)
        rea = self.x("earnings_reaction", t)
        rg = self.x("rev_growth_q", t)
        mc = self.x("market_cap", t)
        adv = self.x("adv20", t)
        dte = self.x("days_to_earnings_est", t)
        sp, dp = self.helper_prev(t, dse)
        with np.errstate(invalid="ignore"):
            ok = ((dse >= p["dse_min"]) & (dse <= p["dse_max"]) & (sur >= p["min_surprise"])
                  & (rea >= p["min_reaction"]) & (rg >= p["min_rev_growth"]) & (mc >= p["min_mcap"])
                  & (adv >= p["min_adv20"]) & (dte > p["min_days_to_next"])
                  & (sp > 0) & (dp >= p["prev_gap"]))
        return ok

    def eligible(self, t):
        base = super().eligible(t)
        ok = self.helper_ok(t)
        dse = self.x("days_since_earnings", t)
        if t >= 1:
            prev_ok = self.helper_ok(t - 1)
            dse_prev = self.x("days_since_earnings", t - 1)
            with np.errstate(invalid="ignore"):
                seen = prev_ok & (dse_prev == dse - 1)
            ok = ok & ~seen
        return base & ok

    def helper_pct(self, v, mask):
        out = np.full(len(v), np.nan)
        idx = np.where(mask & ~np.isnan(v))[0]
        k = len(idx)
        if k == 0:
            return out
        order = np.argsort(v[idx], kind="stable")
        ranks = np.empty(k)
        ranks[order] = np.arange(k)
        out[idx] = (ranks + 1) / k
        return out

    def score(self, t):
        p = self.params
        n = len(self.m.symbols)
        if t < 1:
            return np.full(n, np.nan)
        el = self.eligible(t)
        if not el.any():
            return np.full(n, np.nan)
        dse = self.x("days_since_earnings", t)
        sp, _ = self.helper_prev(t, dse)
        a = np.minimum(self.x("eps_surprise_px", t), p["cap_surprise"])
        b = np.minimum(self.x("earnings_reaction", t), p["cap_reaction"])
        c = np.minimum(sp, p["cap_surprise"])
        s = (self.helper_pct(a, el) + self.helper_pct(b, el) + self.helper_pct(c, el)) / 3.0
        return np.where(el, s, np.nan)

    def plan(self, t, j):
        c = self.m.close[t, j]
        return Signal(self.m.symbols[j], stop=c * (1 - self.params["stop"]), target=None,
                      trail_pct=self.params["trail"], max_hold=self.params["max_hold"], tag=self.name)

    def exits(self, t, m, held):
        dte = self.x("days_to_earnings_est", t)
        pos = {s: i for i, s in enumerate(self.m.symbols)}
        out = []
        for s in held:
            i = pos.get(s)
            if i is None:
                continue
            v = dte[i]
            if v == v and v <= self.params["exit_days_to_earnings"]:
                out.append(s)
        return out

    def why(self, t, j):
        return "2nd straight EPS beat, price reaction %.1f%%" % (100 * self.x("earnings_reaction", t)[j])
