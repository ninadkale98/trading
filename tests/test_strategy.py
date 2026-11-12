"""Strategy framework: loader, picks, random twin, slicing, engine integration (synthetic data, no database)."""
import numpy as np
import pandas as pd

from core.backtest.data import Market
from core.backtest.engine import Config, Signal, run
from core.lab.evaluate import slice_market, t_required
from core.strategy.base import FeatureStrategy, RandomTwin, load


class TopReturn(FeatureStrategy):
    name = "test.top_return"
    max_new_per_day = 2

    def score(self, t):
        return self.f["ret_20d"][t]

    def plan(self, t, j):
        c = self.m.close[t, j]
        return Signal(self.m.symbols[j], stop=c * 0.9, max_hold=5, tag=self.name)


def _market(T=300, N=8, seed=3):
    rng = np.random.default_rng(seed)
    c = 50 * np.exp(np.cumsum(rng.normal(0.0004, 0.02, (T, N)), axis=0))
    vol = np.full((T, N), 2e6)
    syms = ["SPY"] + [f"S{i}" for i in range(1, N)]
    m = Market(pd.bdate_range("2020-01-01", periods=T), syms, c * 0.999, c * 1.01, c * 0.99, c, vol, c * vol, np.full(N, T - 1))
    from core.features import price
    m.f = price.compute(m, c[:, 0], rank_mask=np.ones(N, bool))
    m.is_common = np.array([False] + [True] * (N - 1))
    m.sector = np.array([None] * N, dtype=object)
    return m


def test_picks_respect_eligibility_and_held():
    m = _market()
    s = TopReturn()
    s.prepare(m)
    picks = s.picks(250, held=set())
    assert len(picks) == 2 and 0 not in picks                     # SPY isn't common stock → never picked
    held = {m.symbols[picks[0]]}
    assert m.symbols[picks[0]] not in [m.symbols[j] for j in s.picks(250, held)]


def test_random_twin_matches_count_and_runs():
    m = _market()
    s = TopReturn()
    tw = RandomTwin(s, seed=1)
    tw.prepare(m)
    for t in (200, 250):
        assert len(tw.picks(t, set())) == len(s.picks(t, set()))
    res = run(tw, m, Config(enforce_limits=False))
    assert len(res.trades) > 0 and set(res.trades["tag"]) == {"random"}


def test_slice_keeps_features_aligned():
    m = _market()
    s = slice_market(m, "2020-06-01", "2020-12-31")
    i = m.dates.get_loc(s.dates[0])
    np.testing.assert_array_equal(s.f["rsi14"][0], m.f["rsi14"][i])
    assert s.close.shape[0] == len(s.dates) and list(s.is_common) == list(m.is_common)


def test_multiple_testing_bar_rises():
    assert t_required(1) == 2.0 and t_required(10) < t_required(100) < t_required(1000)


def test_strategy_files_load():
    names = {s.name for s in load("experimental")}
    assert {"quality_pullback", "earnings_gap_up", "earnings_overreaction", "return_to_average", "accumulation",
            "relative_strength"} <= names
    assert all(s.description and s.hypothesis for s in load("experimental"))


def test_earnings_clear_blocks_overdue_reports():
    from core.strategy.base import earnings_clear
    d = np.array([[np.nan, 30, 14, 3, 0, -1, -21, -22]], dtype=np.float32)
    ok = earnings_clear({"days_to_earnings_est": d}, 0)
    # unknown, far away and long-overdue are clear; due soon, today, or recently overdue (probably late) are not
    assert ok.tolist() == [True, True, False, False, False, False, False, True]
