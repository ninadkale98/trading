"""Load daily prices from PostgreSQL into aligned arrays (dates × symbols) for fast simulation.

Prices are split- and dividend-adjusted (raw × adj_factor) so returns are correct.
Dollar volume uses raw close × raw volume (what actually traded)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from core.db import conn


@dataclass
class Market:
    dates: pd.DatetimeIndex
    symbols: list[str]
    open: np.ndarray       # adjusted, shape (T, N); NaN where no bar
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray     # shares
    dollar_volume: np.ndarray  # raw close × volume
    last_index: np.ndarray     # per symbol: index of its final bar (delisting / end of data)

    def col(self, symbol: str) -> int:
        return self._cols[symbol]

    def __post_init__(self):
        self._cols = {s: i for i, s in enumerate(self.symbols)}


def load(start: str | date, end: str | date, symbols: list[str] | None = None,
         universe_only: bool = False, include_delisted: bool = True) -> Market:
    """Load bars between start and end. With universe_only, restrict to our universe (+ delisted company stocks)."""
    where, params = ["p.date BETWEEN %s AND %s"], [start, end]
    if symbols:
        where.append("p.symbol = ANY(%s)")
        params.append(symbols)
    elif universe_only:
        where.append("""p.symbol IN (SELECT symbol FROM stocks WHERE is_universe
                         UNION SELECT symbol FROM stocks WHERE status='inactive' AND asset_type='common' AND %s)""")
        params.append(include_delisted)
    sql = f"""SELECT p.symbol, p.date, p.open * p.adj_factor o, p.high * p.adj_factor h, p.low * p.adj_factor l,
                     p.close * p.adj_factor c, p.volume v, p.close * p.volume dv
              FROM daily_prices p WHERE {' AND '.join(where)}"""
    with conn() as c:
        df = pd.DataFrame(c.execute(sql, params).fetchall())
    if df.empty:
        raise ValueError("no price data for that request")
    df["date"] = pd.to_datetime(df["date"])
    dates = pd.DatetimeIndex(sorted(df["date"].unique()))
    syms = sorted(df["symbol"].unique())
    T, N = len(dates), len(syms)
    di = dates.get_indexer(df["date"])
    si = pd.Index(syms).get_indexer(df["symbol"])

    def grid(col, dtype=np.float64):
        a = np.full((T, N), np.nan, dtype=dtype)
        a[di, si] = df[col].to_numpy(dtype=dtype)
        return a

    close = grid("c")
    last = np.full(N, -1, dtype=np.int64)
    has = ~np.isnan(close)
    any_ = has.any(axis=0)
    last[any_] = T - 1 - np.argmax(has[::-1, any_], axis=0)
    return Market(dates=dates, symbols=syms, open=grid("o"), high=grid("h"), low=grid("l"), close=close,
                  volume=grid("v"), dollar_volume=grid("dv"), last_index=last)
