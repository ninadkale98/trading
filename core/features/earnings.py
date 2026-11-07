"""Earnings-timing features from past earnings releases (8-K item 2.02, view `earnings_events`).

The "reaction day" is the first session that could trade on the news: a release after the 4 pm close (or during
the session) is first traded the next trading day; a release before 9:30 am is traded the same day.
A release becomes visible to these features on its reaction day (conservative point-in-time rule).
"""
from __future__ import annotations

from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from core.db import query

ET = ZoneInfo("America/New_York")

FEATURES = {
    "days_since_earnings": "Trading days since the last earnings reaction day (0 = today is the reaction day)",
    "earnings_reaction": "The stock's move on its last earnings reaction day, minus SPY's move that day",
    "days_to_earnings_est": "Calendar days to the next report: the exact date when the earnings calendar knew it that day, otherwise estimated as last report + 91 days",
}
INT_FEATURES = {"days_since_earnings", "days_to_earnings_est"}


def reaction_days(dates: pd.DatetimeIndex, symbols: list[str]) -> pd.DataFrame:
    """One row per (symbol, reaction day index) for symbols in the Market."""
    rows = query("""SELECT symbol, accepted_at, timing FROM earnings_events
                    WHERE symbol = ANY(%s) AND accepted_at >= %s AND accepted_at <= %s""",
                 (symbols, dates[0].to_pydatetime(), dates[-1].to_pydatetime() + pd.Timedelta(days=1)))
    if not rows:
        return pd.DataFrame(columns=["symbol", "t"])
    df = pd.DataFrame(rows)
    local = pd.to_datetime(df["accepted_at"], utc=True).dt.tz_convert(ET)
    day = local.dt.tz_localize(None).dt.normalize()
    same_day = df["timing"].eq("before_open")
    # first trading day >= release day (before the open) or > release day (during / after the session)
    pos_same = dates.searchsorted(day, side="left")
    pos_next = dates.searchsorted(day, side="right")
    df["t"] = np.where(same_day, pos_same, pos_next)
    df = df[df["t"] < len(dates)]
    return df.drop_duplicates(["symbol", "t"])[["symbol", "t"]]


def calendar_days_to_next(dates: pd.DatetimeIndex, symbols: list[str]) -> np.ndarray | None:
    """Days from each date to the next scheduled report, using only calendar snapshots taken on or before that date
    (≤ 7 days old). NaN where no snapshot covers it. Calendar history starts when we began saving it (Nov 2026)."""
    rows = query("""SELECT as_of, symbol, min(report_date) AS report_date FROM earnings_calendar
                    WHERE as_of BETWEEN %s AND %s AND symbol = ANY(%s) AND report_date >= as_of
                    GROUP BY as_of, symbol""",
                 ((dates[0] - pd.Timedelta(days=7)).date(), dates[-1].date(), symbols))
    if not rows:
        return None
    df = pd.DataFrame(rows)
    snap = df.pivot(index="as_of", columns="symbol", values="report_date")
    snap.index = pd.to_datetime(snap.index)
    snap = snap.reindex(columns=symbols)
    # latest snapshot at or before each trading day, at most 7 calendar days old
    pos = snap.index.searchsorted(dates, side="right") - 1
    out = np.full((len(dates), len(symbols)), np.nan, dtype=np.float32)
    for t, p in enumerate(pos):
        if p < 0 or (dates[t] - snap.index[p]).days > 7:
            continue
        rep = pd.to_datetime(snap.iloc[p].to_numpy())
        days = np.asarray((rep - dates[t]).days, dtype=np.float64)
        out[t] = np.where(days >= 0, days, np.nan)
    return out


def compute(m, spy_close: np.ndarray) -> dict[str, np.ndarray]:
    T, N = m.close.shape
    ev = reaction_days(m.dates, m.symbols)
    marker = np.zeros((T, N), dtype=bool)
    if len(ev):
        col = pd.Index(m.symbols).get_indexer(ev["symbol"])
        marker[ev["t"].to_numpy(dtype=int), col] = True

    # index of the most recent reaction day at or before each t (−1 if none yet)
    t_idx = np.where(marker, np.arange(T)[:, None], -1)
    last = np.maximum.accumulate(t_idx, axis=0)
    has = last >= 0

    days_since = np.where(has, np.arange(T)[:, None] - last, np.nan).astype(np.float32)

    with np.errstate(divide="ignore", invalid="ignore"):
        r1 = m.close / np.vstack([np.full((1, N), np.nan), m.close[:-1]]) - 1
        spy_r1 = spy_close / np.concatenate([[np.nan], spy_close[:-1]]) - 1
    excess = r1 - spy_r1[:, None]
    lc = np.clip(last, 0, None)
    reaction = np.where(has, excess[lc, np.arange(N)[None, :]], np.nan).astype(np.float32)

    cal_days = (m.dates - m.dates[0]).days.to_numpy()
    since_cal = cal_days[:, None] - cal_days[lc]
    to_next = np.where(has, 91 - since_cal, np.nan).astype(np.float32)
    cal = calendar_days_to_next(m.dates, m.symbols)
    if cal is not None:
        to_next = np.where(np.isnan(cal), to_next, cal).astype(np.float32)
    return {"days_since_earnings": days_since, "earnings_reaction": reaction, "days_to_earnings_est": to_next}
