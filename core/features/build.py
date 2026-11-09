"""Load prices for the universe, compute every feature, and turn the result into database rows.
Shared by the nightly job, the backfill and research scripts."""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from core.backtest.data import Market, load
from core.db import conn, query
from core.features import earnings, fundamentals, news, price, releases

COLUMNS = list(price.FEATURES) + list(earnings.FEATURES) + list(fundamentals.FEATURES) + list(news.FEATURES) + list(releases.FEATURES)
INT_COLUMNS = price.INT_FEATURES | earnings.INT_FEATURES | fundamentals.INT_FEATURES | news.INT_FEATURES | releases.INT_FEATURES
LOOKBACK_DAYS = 460          # calendar days of history needed before the first output date (252-day windows + slack)


def universe() -> pd.DataFrame:
    return pd.DataFrame(query("SELECT DISTINCT ON (symbol) symbol, asset_type, sector, cik FROM stocks "
                              "WHERE is_universe ORDER BY symbol, last_seen DESC"))


def info_for(symbols: list[str]) -> pd.DataFrame:
    """asset_type / sector / cik per symbol (active listing preferred over an old delisted one)."""
    return pd.DataFrame(query("""SELECT DISTINCT ON (symbol) symbol, asset_type, sector, cik FROM stocks
                                 WHERE symbol = ANY(%s) ORDER BY symbol, (status = 'active') DESC, last_seen DESC""",
                              (symbols,))).set_index("symbol").reindex(symbols)


def features_for_market(m: Market, fundamentals_too: bool = True) -> dict[str, np.ndarray]:
    """Every feature for an already-loaded Market. Also attaches is_common / sector to `m` for strategies."""
    info = info_for(m.symbols)
    m.is_common = (info["asset_type"] == "common").to_numpy()
    m.sector = info["sector"].to_numpy(dtype=object)
    if "SPY" not in m.symbols:
        raise RuntimeError("SPY prices missing; can't compute market-relative features")
    spy = m.close[:, m.col("SPY")]
    bench = np.full_like(m.close, np.nan)
    for j, sector in enumerate(m.sector):
        etf = price.SECTOR_ETF.get(sector)
        if etf and etf in m._cols and m.is_common[j]:
            bench[:, j] = m.close[:, m.col(etf)]
    feats = price.compute(m, spy, bench, m.is_common)
    feats.update(earnings.compute(m, spy))
    if fundamentals_too:
        ciks = {s: int(c) for s, c, common in zip(m.symbols, info["cik"], m.is_common) if common and pd.notna(c)}
        feats.update(fundamentals.compute(m, ciks))
    feats.update(news.compute(m))
    feats.update(releases.compute(m))
    return feats


def compute_all(start: date, end: date) -> tuple[Market, dict[str, np.ndarray]]:
    m = load(start, end, symbols=universe()["symbol"].tolist())
    return m, features_for_market(m)


def research_market(start: date | str, end: date | str, fundamentals_too: bool = True) -> Market:
    """Market for backtests: today's universe PLUS delisted company stocks (survivorship rule), features attached
    as `m.f`. Features need ~1 year of history, so the first year after `start` has gaps (e.g. no RS rank)."""
    syms = [r["symbol"] for r in query("""SELECT symbol FROM stocks WHERE is_universe
                                          UNION SELECT symbol FROM stocks WHERE status='inactive' AND asset_type='common'""")]
    m = load(start, end, symbols=syms)
    m.f = features_for_market(m, fundamentals_too)
    return m


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
                v = [None if x is None or not np.isfinite(float(x)) else x for x in v]
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
