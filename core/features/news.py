"""Daily per-stock news features from Haiku's labels (news_events). Point-in-time: an item counts from the day it
was published (after 4 pm ET → the next trading day). History only exists from when labeling started (Nov 2026),
so these are tested going forward, not on old years."""
from __future__ import annotations

from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from core.db import query

ET = ZoneInfo("America/New_York")
FEATURES = {
    "news_count_5d": "Company-specific news items in the last 5 trading days (price-move recaps excluded)",
    "news_score_5d": "Net news tone over 5 trading days: sum of direction (−2…+2) × importance (1–5)",
    "news_major_5d": "Most important item (importance 4–5) in 5 days, signed by its direction (e.g. −5 = major bad news)",
}
INT_FEATURES = {"news_count_5d"}


def compute(m) -> dict[str, np.ndarray]:
    T, N = m.close.shape
    out = {k: np.full((T, N), np.nan, dtype=np.float32) for k in FEATURES}
    rows = query("""SELECT e.symbol, e.created_at, e.direction, e.importance FROM news_events e
                    JOIN news_ai a ON a.news_id = e.news_id
                    WHERE e.symbol = ANY(%s) AND e.created_at >= %s AND e.created_at < %s + interval '1 day'
                      AND NOT coalesce(a.recap, false)""",
                 (m.symbols, (m.dates[0] - pd.Timedelta(days=10)).date(), m.dates[-1].date()))
    if not rows:
        return out
    df = pd.DataFrame(rows)
    local = pd.to_datetime(df["created_at"], utc=True).dt.tz_convert(ET)
    after_close = local.dt.hour >= 16
    day = local.dt.tz_localize(None).dt.normalize()
    # first trading day on which the item is known at the close: same day if before 4 pm, else the next one
    pos = np.where(after_close, m.dates.searchsorted(day, side="right"), m.dates.searchsorted(day, side="left"))
    df["t"], df["j"] = pos, pd.Index(m.symbols).get_indexer(df["symbol"])
    df = df[(df["t"] < T) & (df["j"] >= 0)]
    df["score"] = df["direction"] * df["importance"]
    df["major"] = np.where(df["importance"] >= 4, df["direction"].clip(-1, 1) * df["importance"], 0)
    first = int(df["t"].min()) if len(df) else T
    cnt, sc, mj = (np.zeros((T, N)) for _ in range(3))
    np.add.at(cnt, (df["t"], df["j"]), 1)
    np.add.at(sc, (df["t"], df["j"]), df["score"])
    for (t, j), v in df.groupby(["t", "j"])["major"].agg(lambda x: x.iloc[np.argmax(np.abs(x.to_numpy()))]).items():
        mj[t, j] = v
    roll = lambda a, fn: getattr(pd.DataFrame(a).rolling(5, min_periods=1), fn)().to_numpy()  # noqa: E731
    c5, s5 = roll(cnt, "sum"), roll(sc, "sum")
    mx, mn = roll(mj, "max"), roll(mj, "min")
    m5 = np.where(np.abs(mn) > np.abs(mx), mn, mx)
    live = np.arange(T)[:, None] >= first          # before labeling started there is no information, not "zero news"
    out["news_count_5d"] = np.where(live, c5, np.nan).astype(np.float32)
    out["news_score_5d"] = np.where(live, s5, np.nan).astype(np.float32)
    out["news_major_5d"] = np.where(live, m5, np.nan).astype(np.float32)
    return out
