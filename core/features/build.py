"""Load prices for the universe, compute every feature, and turn the result into database rows.
Shared by the nightly job, the backfill and research scripts."""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from core.backtest.data import Market, load
from core.db import conn, query
from core.features import earnings, price

COLUMNS = list(price.FEATURES) + list(earnings.FEATURES)
INT_COLUMNS = price.INT_FEATURES | earnings.INT_FEATURES
LOOKBACK_DAYS = 460          # calendar days of history needed before the first output date (252-day windows + slack)


def universe() -> pd.DataFrame:
    return pd.DataFrame(query("SELECT DISTINCT ON (symbol) symbol, asset_type, sector FROM stocks "
                              "WHERE is_universe ORDER BY symbol, last_seen DESC"))


def compute_all(start: date, end: date) -> tuple[Market, dict[str, np.ndarray]]:
    u = universe()
    m = load(start, end, symbols=u["symbol"].tolist())
    info = u.set_index("symbol").reindex(m.symbols)
    if "SPY" not in m.symbols:
        raise RuntimeError("SPY prices missing; can't compute market-relative features")
    spy = m.close[:, m.col("SPY")]
    bench = np.full_like(m.close, np.nan)
    for j, sector in enumerate(info["sector"].tolist()):
        etf = price.SECTOR_ETF.get(sector)
        if etf and etf in m._cols and info["asset_type"].iloc[j] == "common":
            bench[:, j] = m.close[:, m.col(etf)]
    rank_mask = (info["asset_type"] == "common").to_numpy()
    feats = price.compute(m, spy, bench, rank_mask)
    feats.update(earnings.compute(m, spy))
    return m, feats


def rows(m: Market, feats: dict[str, np.ndarray], from_date: date, t_end: int | None = None) -> list[tuple]:
    """(symbol, date, feature…) for every day ≥ from_date (and index < t_end) on which the stock traded."""
    t0 = int(m.dates.searchsorted(pd.Timestamp(from_date)))
    out: list[tuple] = []
    syms = np.array(m.symbols, dtype=object)
    for t in range(t0, len(m.dates) if t_end is None else min(t_end, len(m.dates))):
        ok = ~np.isnan(m.close[t])
        if not ok.any():
            continue
        d = m.dates[t].date()
        cols = []
        for name in COLUMNS:
            v = feats[name][t, ok].astype(object)
            v[pd.isna(feats[name][t, ok])] = None
            if name in INT_COLUMNS:
                v = [None if x is None else int(round(float(x))) for x in v]
            else:
                v = [None if x is None else float(x) for x in v]
            cols.append(v)
        out.extend(zip(syms[ok], [d] * int(ok.sum()), *cols))
    return out


def store(rows_: list[tuple]) -> int:
    if not rows_:
        return 0
    names = ["symbol", "date", *COLUMNS]
    sets = ", ".join(f"{c}=EXCLUDED.{c}" for c in COLUMNS)
    with conn() as c, c.cursor() as cur:
        cur.execute(f"CREATE TEMP TABLE _f (LIKE features_daily INCLUDING DEFAULTS) ON COMMIT DROP")
        with cur.copy(f"COPY _f ({', '.join(names)}) FROM STDIN") as cp:
            for r in rows_:
                cp.write_row(r)
        cur.execute(f"""INSERT INTO features_daily ({', '.join(names)}) SELECT {', '.join(names)} FROM _f
                        ON CONFLICT (symbol, date) DO UPDATE SET {sets}, computed_at = now()""")
        return cur.rowcount


def build_range(write_from: date, write_to: date, batch_days: int = 20) -> int:
    """Compute and store features for [write_from, write_to], writing ~20 trading days at a time (bounded memory)."""
    m, feats = compute_all(write_from - timedelta(days=LOOKBACK_DAYS), write_to)
    t = int(m.dates.searchsorted(pd.Timestamp(write_from)))
    n = 0
    while t < len(m.dates):
        n += store(rows(m, feats, m.dates[t].date(), t + batch_days))
        t += batch_days
    return n
