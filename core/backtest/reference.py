"""Reference strategies used to validate the backtester itself (build plan 1.10)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from core.backtest.data import Market
from core.backtest.engine import Signal, Strategy


class BuyAndHold(Strategy):
    """Buy one symbol with ~all the money on day 1 and hold. Must match the symbol's real return (minus a small cost)."""
    name = "ref.buy_and_hold"

    def __init__(self, symbol: str = "SPY"):
        self.symbol = symbol
        self.params = {"symbol": symbol}

    def signals(self, t, m, held):
        if self.symbol in held:
            return []
        return [Signal(self.symbol, weight=0.999, tag="hold")]


class TrendFilter(Strategy):
    """Hold SPY only while it closes above its 200-day average (a classic, well-understood rule)."""
    name = "ref.trend_200d"

    def __init__(self, symbol: str = "SPY", days: int = 200):
        self.symbol, self.days = symbol, days
        self.params = {"symbol": symbol, "days": days}

    def prepare(self, m: Market):
        c = m.close[:, m.col(self.symbol)]
        self.sma = pd.Series(c).rolling(self.days).mean().to_numpy()
        self.above = c > self.sma

    def signals(self, t, m, held):
        if self.symbol not in held and self.above[t]:
            return [Signal(self.symbol, weight=0.999, tag="trend")]
        return []

    def exits(self, t, m, held):
        return [self.symbol] if self.symbol in held and not self.above[t] else []


def no_lookahead(strategy: Strategy, m: Market, sample: int = 30, seed: int = 0) -> bool:
    """Signals at day t must be identical whether or not future data exists. Corrupt the future and compare."""
    rng = np.random.default_rng(seed)
    strategy.prepare(m)
    days = sorted(rng.choice(np.arange(220, len(m.dates) - 1), size=min(sample, len(m.dates) - 221), replace=False))
    for t in days:
        base = [(s.symbol, s.stop, s.target) for s in strategy.signals(t, m, set())]
        garbled = Market(m.dates, m.symbols, *(a.copy() for a in (m.open, m.high, m.low, m.close, m.volume, m.dollar_volume)),
                         last_index=m.last_index)
        for a in (garbled.open, garbled.high, garbled.low, garbled.close, garbled.volume, garbled.dollar_volume):
            a[t + 1:] = a[t + 1:] * rng.uniform(0.5, 1.5, size=a[t + 1:].shape)
        strategy.prepare(garbled)
        if [(s.symbol, s.stop, s.target) for s in strategy.signals(t, garbled, set())] != base:
            return False
        strategy.prepare(m)
    return True
