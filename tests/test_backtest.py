"""Backtester mechanics on synthetic prices where the right answer is known."""
import numpy as np
import pandas as pd
import pytest

from core.backtest.data import Market
from core.backtest.engine import Config, Signal, Strategy, run
from core.backtest.reference import BuyAndHold, no_lookahead


def market(rows: dict[str, list[tuple]], volume=10_000_000) -> Market:
    """rows: symbol → list of (open, high, low, close) per day."""
    syms = sorted(rows)
    T = max(len(v) for v in rows.values())
    dates = pd.bdate_range("2024-01-01", periods=T)
    arr = {k: np.full((T, len(syms)), np.nan) for k in "ohlc"}
    for j, s in enumerate(syms):
        for t, (o, h, l, c) in enumerate(rows[s]):
            arr["o"][t, j], arr["h"][t, j], arr["l"][t, j], arr["c"][t, j] = o, h, l, c
    vol = np.where(np.isfinite(arr["c"]), volume, np.nan)
    has = np.isfinite(arr["c"])
    last = np.array([T - 1 - np.argmax(has[::-1, j]) for j in range(len(syms))])
    return Market(dates, syms, arr["o"], arr["h"], arr["l"], arr["c"], vol, vol * arr["c"], last)


class OneShot(Strategy):
    """Buy `sym` once at the open after day `t0`, with the given exit settings."""
    name = "test.oneshot"

    def __init__(self, sym, t0=0, **kw):
        self.sym, self.t0, self.kw, self.done = sym, t0, kw, False

    def signals(self, t, m, held):
        if t == self.t0 and not self.done:
            self.done = True
            return [Signal(self.sym, **self.kw)]
        return []


NO_COST = Config(cost_bps={"liquid": 0, "thin": 0, "emerging": 0}, enforce_limits=False)


def test_gap_through_stop_fills_at_open_not_stop():
    # Intel-style: stop at 85, stock gaps from 92 to 68 overnight
    m = market({"X": [(92, 93, 91, 92), (92, 95, 91, 94), (68.36, 68.77, 63.2, 65.76), (65, 66, 64, 65)]})
    res = run(OneShot("X", stop=85, risk_pct=0.01), m, NO_COST)
    tr = res.trades.iloc[0]
    assert tr.exit_reason == "stop_gap" and tr.exit_price == pytest.approx(68.36)
    assert tr.r_multiple < -2.5            # lost far more than the planned 1R


def test_stop_and_target_same_day_assumes_stop_first():
    m = market({"X": [(100, 100, 100, 100), (100, 101, 99, 100), (100, 115, 90, 100), (100, 100, 100, 100)]})
    res = run(OneShot("X", stop=95, target=110), m, NO_COST)
    assert res.trades.iloc[0].exit_reason == "stop"


def test_partial_profit_then_trailing_stop():
    up = [(100, 100, 100, 100), (100, 101, 99, 100), (100, 111, 100, 110), (110, 121, 109, 120),
          (120, 131, 119, 130), (130, 130, 115, 116), (116, 117, 115, 116)]
    m = market({"X": up})
    res = run(OneShot("X", stop=95, target=110, partial=0.5, trail_pct=0.10), m, NO_COST)
    tr = res.trades.iloc[0]
    # half sold at 110; the rest trails 10% under the 130 high → stop 117 hit on the drop to 115
    assert tr.exit_reason == "stop"
    assert tr.pnl > 0


def test_time_stop_and_delisting():
    m = market({"X": [(10, 10, 10, 10)] * 3 + [(10, 11, 10, 11)] * 7,
                "D": [(5, 5, 5, 5), (5, 5, 5, 5), (5, 5, 5, 5), (4, 4, 4, 4)]})  # D's data ends (delisted)
    r1 = run(OneShot("X", stop=9, max_hold=3), m, NO_COST)
    assert r1.trades.iloc[0].exit_reason == "time" and r1.trades.iloc[0].hold_days == 3
    r2 = run(OneShot("D", stop=1), m, NO_COST)
    assert r2.trades.iloc[0].exit_reason == "delisted" and r2.trades.iloc[0].exit_price == pytest.approx(4)


def test_buy_and_hold_matches_price_change():
    closes = [100 * 1.001 ** i for i in range(260)]
    m = market({"SPY": [(c, c, c, c) for c in closes]})
    res = run(BuyAndHold("SPY"), m, NO_COST)
    ret = res.equity.iloc[-1] / res.equity.iloc[0] - 1
    expected = closes[-1] / closes[1] - 1           # bought at day-1 open
    assert ret == pytest.approx(expected * 0.999, rel=0.01)


def test_costs_reduce_returns():
    closes = [100 + i for i in range(30)]
    m = market({"X": [(c, c, c, c) for c in closes]})
    free = run(OneShot("X", stop=50, max_hold=10), m, NO_COST).trades.iloc[0].pnl
    costly = run(OneShot("X", stop=50, max_hold=10), m, Config(enforce_limits=False)).trades.iloc[0].pnl
    assert costly < free


def test_hard_limit_caps_position_size():
    closes = [100.0] * 10
    m = market({"X": [(c, c, c - 0.5, c) for c in closes]})
    # a 0.5% stop with 2% risk would mean 400% of the account; the 15% position cap must win
    res = run(OneShot("X", stop=99.5, risk_pct=0.02, max_hold=2), m, Config())
    tr = res.trades.iloc[0]
    assert tr.cost_basis <= 100_000 * 0.15 * 1.01      # ≤ 15% of the account, not 400%


class LookAheadCheater(Strategy):
    name = "test.cheater"

    def signals(self, t, m, held):
        j = 0
        if t + 1 < len(m.dates) and m.close[t + 1, j] > m.close[t, j]:   # peeks at tomorrow!
            return [Signal(m.symbols[j], stop=m.close[t, j] * 0.9)]
        return []


class Honest(Strategy):
    name = "test.honest"

    def prepare(self, m):
        self.sma = pd.DataFrame(m.close).rolling(20).mean().to_numpy()

    def signals(self, t, m, held):
        j = 0
        if m.close[t, j] > self.sma[t, j]:
            return [Signal(m.symbols[j], stop=m.close[t, j] * 0.9)]
        return []


def test_lookahead_detector():
    rng = np.random.default_rng(1)
    c = 100 * np.cumprod(1 + rng.normal(0, 0.01, 400))
    m = market({"X": [(x, x * 1.01, x * 0.99, x) for x in c]})
    assert no_lookahead(Honest(), m)
    assert not no_lookahead(LookAheadCheater(), m)
