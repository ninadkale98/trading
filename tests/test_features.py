"""Feature math on synthetic data: correct values, and no peeking at the future."""
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from core.backtest.data import Market
from core.features import earnings, price


def _market(close: np.ndarray, symbols=None) -> Market:
    T, N = close.shape
    dates = pd.bdate_range("2024-01-01", periods=T)
    vol = np.full((T, N), 1_000_000.0)
    return Market(dates=dates, symbols=symbols or [f"S{i}" for i in range(N)], open=close * 0.999, high=close * 1.01,
                  low=close * 0.99, close=close, volume=vol, dollar_volume=close * vol, last_index=np.full(N, T - 1))


def _random_walk(T=400, N=6, seed=1):
    rng = np.random.default_rng(seed)
    return 100 * np.exp(np.cumsum(rng.normal(0.0005, 0.02, (T, N)), axis=0))


def test_no_lookahead():
    c = _random_walk()
    m = _market(c)
    spy = c[:, 0].copy()
    a = price.compute(m, spy, rank_mask=np.ones(6, bool))
    k = 300
    c2 = c.copy()
    c2[k + 1:] *= np.random.default_rng(9).uniform(0.5, 1.5, c2[k + 1:].shape)   # scramble the future
    spy2 = c2[:, 0].copy()
    b = price.compute(_market(c2), spy2, rank_mask=np.ones(6, bool))
    for name in a:
        np.testing.assert_array_equal(a[name][: k + 1], b[name][: k + 1], err_msg=name)


def test_values_on_simple_series():
    T = 300
    rising = 100 * 1.001 ** np.arange(T)
    flat = np.full(T, 50.0)
    c = np.column_stack([rising, flat])
    f = price.compute(_market(c), spy_close=flat, rank_mask=np.array([True, True]))
    assert abs(f["ret_20d"][-1, 0] - (1.001 ** 20 - 1)) < 1e-5
    assert f["rsi14"][-1, 0] == 100                       # only up days
    assert abs(f["dist_sma50"][-1, 1]) < 1e-6             # flat price sits on its average
    assert f["trend_score"][-1, 0] == 5                   # textbook uptrend
    assert f["rs_rank"][-1, 0] > f["rs_rank"][-1, 1]       # the riser ranks above the flat stock
    assert abs(f["beta_250"][-1, 0]) < 1e-6 or np.isnan(f["beta_250"][-1, 0])  # SPY flat → no beta signal
    assert abs(f["rvol"][-1, 1] - 1) < 1e-6               # constant volume → relative volume 1


def test_rank_ignores_masked_columns():
    c = _random_walk(N=4)
    f = price.compute(_market(c), c[:, 0], rank_mask=np.array([True, True, True, False]))
    assert np.isnan(f["rs_rank"][-1, 3])
    assert np.nanmin(f["rs_rank"][-1, :3]) >= 1 and np.nanmax(f["rs_rank"][-1, :3]) <= 99


def test_earnings_reaction_day(monkeypatch):
    c = _random_walk(T=30, N=2)
    m = _market(c, ["AAA", "BBB"])
    d = m.dates
    et = lambda day, hh, mm: pd.Timestamp(day).tz_localize("America/New_York").replace(hour=hh, minute=mm).tz_convert("UTC")  # noqa: E731
    events = [
        {"symbol": "AAA", "accepted_at": et(d[10], 16, 5), "timing": "after_close"},    # → traded on d[11]
        {"symbol": "BBB", "accepted_at": et(d[10], 7, 0), "timing": "before_open"},     # → traded on d[10]
    ]
    monkeypatch.setattr(earnings, "query", lambda sql, params: events if "earnings_events" in sql else [])
    f = earnings.compute(m, spy_close=c[:, 0] * 0 + 100)
    assert np.isnan(f["days_since_earnings"][10, 0]) and f["days_since_earnings"][11, 0] == 0
    assert f["days_since_earnings"][10, 1] == 0 and f["days_since_earnings"][15, 1] == 5
    assert abs(f["earnings_reaction"][11, 0] - (c[11, 0] / c[10, 0] - 1)) < 1e-5   # SPY flat → excess = raw move


def test_calendar_is_point_in_time(monkeypatch):
    dates = pd.bdate_range("2026-11-02", periods=10)
    snap = [{"as_of": dates[3].date(), "symbol": "AAA", "report_date": dates[8].date()}]
    monkeypatch.setattr(earnings, "query", lambda sql, params: snap)
    out = earnings.calendar_days_to_next(dates, ["AAA"])
    assert np.isnan(out[2, 0])                          # snapshot not taken yet
    assert out[3, 0] == (dates[8] - dates[3]).days      # known from the snapshot day on
    assert out[8, 0] == 0 and np.isnan(out[9, 0])       # report day, then passed
