"""Crash watch (build plan 4.1, user idea 2026-11-09; studies in lab/notebook.md).

Steadily big companies (top 100 US common stocks by 20-day dollar volume on >= 95% of the last 500 trading days) that
now close >= 15% below their 60-day high. For each: how far down, the latest heavy-volume selling day (a down day on
>= 2x the prior 60-day average volume) in the last 10 days, whether selling volume is calming, how far it fell after
that day, and whether it has "turned" (a close above the prior 5 closes' high).

It's for watching and learning, NOT a buy signal. In the 2016-2026 study, buying at the heavy-volume day beat waiting
for the turn; trading it waits for the lab's `big_crash_capitulation` test. Computed nightly into the market snapshot
(`crash_watch`), shown on the dashboard's Market page and in the briefing. Point-in-time: only bars up to `day`."""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from core.db import query

MIN_DRAWDOWN = 0.15
HEAVY_X = 2.0
LOOKBACK_HEAVY = 10


def steady_big(day: date, top: int = 100, share: float = 0.95, days: int = 500) -> dict[str, int]:
    """symbol → today's rank by 20-day dollar volume, for stocks in the top `top` on >= `share` of the last `days` days."""
    rows = query("""
        WITH d AS (SELECT DISTINCT date FROM features_daily WHERE symbol='SPY' AND date <= %(day)s ORDER BY date DESC LIMIT %(days)s),
        r AS (SELECT f.symbol, f.date, rank() OVER (PARTITION BY f.date ORDER BY f.adv20 DESC) rk
              FROM features_daily f JOIN d USING (date)
              WHERE f.adv20 IS NOT NULL
                AND EXISTS (SELECT 1 FROM stocks s WHERE s.symbol=f.symbol AND s.asset_type='common'))
        SELECT symbol, max(rk) FILTER (WHERE date = %(day)s) AS rank_now FROM r GROUP BY symbol
        HAVING count(*) >= %(need)s AND avg((rk <= %(top)s)::int) >= %(share)s""",
                 {"day": day, "days": days, "need": int(days * 0.96), "top": top, "share": share})
    return {r["symbol"]: r["rank_now"] for r in rows if r["rank_now"] is not None}


def compute(day: date) -> list[dict]:
    big = steady_big(day)
    if not big:
        return []
    rows = query("""SELECT symbol, date, close * adj_factor AS c, volume / NULLIF(adj_factor, 0) AS v FROM daily_prices
                    WHERE symbol = ANY(%s) AND date <= %s AND date > %s::date - 140 ORDER BY date""",
                 (list(big), day, day))
    df = pd.DataFrame(rows)
    if df.empty:
        return []
    c = df.pivot(index="date", columns="symbol", values="c").astype(float)
    v = df.pivot(index="date", columns="symbol", values="v").astype(float)
    out = []
    for s in c.columns:
        p, vol = c[s].dropna(), v[s].dropna()
        if len(p) < 65 or p.index[-1] != day:
            continue
        hi = p.iloc[-60:].max()
        dd = p.iloc[-1] / hi - 1
        if dd > -MIN_DRAWDOWN:
            continue
        r = p.pct_change()
        avg60 = vol.rolling(60, min_periods=40).mean().shift(1)
        heavy = ((vol >= HEAVY_X * avg60) & (r < 0)).iloc[-LOOKBACK_HEAVY:]
        hd = heavy[heavy].index.max() if heavy.any() else None
        i_h = p.index.get_loc(hd) if hd is not None else None
        week = vol.iloc[i_h - 4:i_h + 1].mean() if i_h is not None else None
        out.append({
            "symbol": s, "rank": int(big[s]), "close": round(float(p.iloc[-1]), 2), "high_60d": round(float(hi), 2),
            "drawdown": round(float(dd), 4), "ret_1d": round(float(r.iloc[-1]), 4),
            "heavy_day": str(hd) if hd is not None else None,
            "heavy_x": round(float(vol.loc[hd] / avg60.loc[hd]), 1) if hd is not None else None,
            "since_heavy": round(float(p.iloc[-1] / p.loc[hd] - 1), 4) if hd is not None else None,
            # selling calming: last 5 days' volume vs the heavy day's week (or vs the 60-day average if no heavy day)
            "volume_trend": round(float(vol.iloc[-5:].mean() / (week if week else avg60.iloc[-1])), 2),
            "turned": bool(p.iloc[-1] > p.iloc[-6:-1].max()),
        })
    return sorted(out, key=lambda x: x["drawdown"])


def lines(items: list[dict], limit: int = 10) -> list[str]:
    """Plain-language lines for the briefing."""
    L = []
    for x in items[:limit]:
        h = (f"heavy selling {x['heavy_day'][5:]} ({x['heavy_x']}× volume), {x['since_heavy']:+.1%} since"
             if x["heavy_day"] else "no heavy-volume day in the last 2 weeks")
        vt = "calming" if x["volume_trend"] < 0.8 else "still heavy" if x["volume_trend"] > 1.2 else "steady"
        L.append(f"- **{x['symbol']}** {x['drawdown']:+.0%} from its 60-day high ({x['close']:.2f} vs {x['high_60d']:.2f}); "
                 f"{h}; volume {vt}" + ("; **turned up** (close above the last 5 days)" if x["turned"] else ""))
    return L
