"""Daily market snapshot: breadth, rotation, style, cross-asset, global, leaders, regime (architecture §5.6, §10.3).

Pure numbers, computed after the daily features. Opus reads it (Phase 3); the planner uses `regime` and `exposure`
for the market exposure dial (Phase 2.3); the dashboard's Market page shows it.
"""
from __future__ import annotations

import json
from datetime import date, timedelta

import numpy as np
import pandas as pd

from core.db import conn, query
from core.market.groups import ALL, GROUPS, NAME

MIN_ADV_BREADTH = 1_000_000   # breadth counts stocks trading ≥ $1M/day (skips the tiniest, noisiest names)


def etf_closes(end: date, days: int = 420) -> pd.DataFrame:
    rows = query("""SELECT symbol, date, close * adj_factor AS c FROM daily_prices
                    WHERE symbol = ANY(%s) AND date BETWEEN %s AND %s""", (ALL, end - timedelta(days=days), end))
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).pivot(index="date", columns="symbol", values="c").sort_index()
    return df.astype(float)


def _ret(s: pd.Series, n: int) -> float | None:
    s = s.dropna()
    if len(s) <= n:
        return None
    return float(s.iloc[-1] / s.iloc[-1 - n] - 1)


def _r(x, nd=4):
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else round(float(x), nd)


def _quadrant(strength, momentum) -> str | None:
    if strength is None or momentum is None:
        return None
    if strength >= 0:
        return "leading" if momentum >= 0 else "weakening"
    return "improving" if momentum >= 0 else "lagging"


def groups_table(px: pd.DataFrame) -> dict[str, list[dict]]:
    spy = px["SPY"]
    s20, s60 = _ret(spy, 20), _ret(spy, 60)
    out = {}
    for g, members in GROUPS.items():
        rows = []
        for sym in members:
            if sym not in px:
                continue
            s = px[sym].dropna()
            if len(s) < 2:
                continue
            r = {n: _ret(s, n) for n in (1, 5, 20, 60, 120, 250)}
            rel20 = None if r[20] is None or s20 is None else r[20] - s20
            rel60 = None if r[60] is None or s60 is None else r[60] - s60
            sma200 = s.iloc[-200:].mean() if len(s) >= 200 else None
            rows.append({"symbol": sym, "name": NAME[sym], "close": _r(s.iloc[-1], 2),
                         **{f"ret_{n}d": _r(v) for n, v in r.items()},
                         "rel_20d": _r(rel20), "rel_60d": _r(rel60),
                         "quadrant": _quadrant(rel60, rel20) if sym != "SPY" else None,
                         "above_200d": None if sma200 is None else bool(s.iloc[-1] > sma200)})
        out[g] = rows
    return out


def breadth(day: date) -> dict:
    r = query("""SELECT count(*) n,
                    avg((f.dist_sma50 > 0)::int)  above_50,
                    avg((f.dist_sma200 > 0)::int) above_200,
                    sum((f.dist_52w_high >= -0.01)::int) near_high,
                    sum((f.dist_52w_low <= 0.01)::int)   near_low,
                    sum((f.ret_1d > 0)::int) up, sum((f.ret_1d < 0)::int) down,
                    percentile_cont(0.5) WITHIN GROUP (ORDER BY f.ret_1d)  med_1d,
                    percentile_cont(0.5) WITHIN GROUP (ORDER BY f.ret_20d) med_20d,
                    avg((f.trend_score >= 4)::int) uptrend
                 FROM features_daily f JOIN stocks s ON s.symbol = f.symbol AND s.is_universe AND s.asset_type = 'common'
                 WHERE f.date = %s AND f.adv20 >= %s""", (day, MIN_ADV_BREADTH))[0]
    if not r["n"]:
        return {}
    return {"stocks": r["n"], "pct_above_50d": _r(r["above_50"], 3), "pct_above_200d": _r(r["above_200"], 3),
            "near_52w_high": r["near_high"], "near_52w_low": r["near_low"], "advancers": r["up"], "decliners": r["down"],
            "median_ret_1d": _r(r["med_1d"]), "median_ret_20d": _r(r["med_20d"]), "pct_uptrend": _r(r["uptrend"], 3)}


def sectors(day: date) -> list[dict]:
    rows = query("""SELECT s.sector, count(*) n, percentile_cont(0.5) WITHIN GROUP (ORDER BY f.ret_20d) med_20d,
                           percentile_cont(0.5) WITHIN GROUP (ORDER BY f.ret_60d) med_60d,
                           avg((f.dist_sma50 > 0)::int) above_50, avg(f.rs_rank) avg_rs
                    FROM features_daily f JOIN stocks s ON s.symbol = f.symbol AND s.is_universe AND s.asset_type = 'common'
                    WHERE f.date = %s AND f.adv20 >= %s AND s.sector IS NOT NULL
                    GROUP BY s.sector ORDER BY med_20d DESC NULLS LAST""", (day, MIN_ADV_BREADTH))
    return [{"sector": r["sector"], "stocks": r["n"], "median_ret_20d": _r(r["med_20d"]), "median_ret_60d": _r(r["med_60d"]),
             "pct_above_50d": _r(r["above_50"], 3), "avg_rs_rank": _r(r["avg_rs"], 1)} for r in rows]


def stock_lists(day: date) -> dict:
    base = """FROM features_daily f JOIN stocks s ON s.symbol = f.symbol AND s.is_universe AND s.asset_type = 'common'
              WHERE f.date = %s AND f.adv20 >= 5000000"""
    cols = "f.symbol, s.sector, f.close, f.ret_1d, f.ret_20d, f.ret_60d, f.rs_rank, f.rvol, f.dist_52w_high, f.days_since_earnings"
    leaders = query(f"SELECT {cols} {base} AND f.trend_score >= 4 AND f.dist_52w_high >= -0.05 "
                    "ORDER BY f.rs_rank DESC NULLS LAST, f.ret_60d DESC LIMIT 20", (day,))
    up = query(f"SELECT {cols} {base} AND f.ret_1d IS NOT NULL ORDER BY f.ret_1d DESC LIMIT 12", (day,))
    down = query(f"SELECT {cols} {base} AND f.ret_1d IS NOT NULL ORDER BY f.ret_1d ASC LIMIT 12", (day,))
    clean = lambda rs: [{k: (_r(v) if isinstance(v, float) else v) for k, v in r.items()} for r in rs]  # noqa: E731
    return {"leaders": clean(leaders), "top_gainers": clean(up), "top_losers": clean(down)}


def signals(px: pd.DataFrame) -> dict:
    """Spreads that say whether investors are taking risk (positive) or hiding (negative), over ~1 month."""
    r20 = {s: _ret(px[s], 20) for s in px}
    r60 = {s: _ret(px[s], 60) for s in px}
    r5 = {s: _ret(px[s], 5) for s in px}

    def diff(a, b, r=r20):
        return None if r.get(a) is None or r.get(b) is None else r[a] - r[b]

    cyc = [r20.get(s) for s in ("XLY", "XLK")]
    dfn = [r20.get(s) for s in ("XLP", "XLU")]
    cyc_def = None if None in cyc + dfn else (sum(cyc) - sum(dfn)) / 2
    return {
        "credit_hy_vs_treasuries_20d": _r(diff("HYG", "IEF")),
        "small_vs_large_20d": _r(diff("IWM", "SPY")),
        "cyclical_vs_defensive_20d": _r(cyc_def),
        "equal_vs_capweight_60d": _r(diff("RSP", "SPY", r60)),
        "growth_vs_value_20d": _r(diff("IWF", "IWD")),
        "long_bonds_20d": _r(r20.get("TLT")), "dollar_20d": _r(r20.get("UUP")), "gold_20d": _r(r20.get("GLD")),
        "oil_20d": _r(r20.get("USO")), "bitcoin_20d": _r(r20.get("IBIT")), "fear_vixy_5d": _r(r5.get("VIXY")),
    }


def regime(px: pd.DataFrame, br: dict, sig: dict) -> tuple[str, float, dict]:
    """Rule-based market condition → exposure dial level (architecture §10.3). Kept deliberately simple and explainable."""
    spy = px["SPY"].dropna()
    sma200 = spy.iloc[-200:].mean() if len(spy) >= 200 else np.nan
    sma200_prev = spy.iloc[-220:-20].mean() if len(spy) >= 220 else np.nan
    above, rising = bool(spy.iloc[-1] > sma200), bool(sma200 > sma200_prev)
    trend = "uptrend" if above and rising else "downtrend" if (not above and not rising) else "mixed"
    p200 = br.get("pct_above_200d")
    participation = None if p200 is None else ("broad" if p200 >= 0.6 else "weak" if p200 <= 0.4 else "middling")
    votes = [sig.get("credit_hy_vs_treasuries_20d"), sig.get("small_vs_large_20d"), sig.get("cyclical_vs_defensive_20d")]
    votes = [v for v in votes if v is not None]
    fear = sig.get("fear_vixy_5d")
    score = sum(v > 0 for v in votes) + (1 if fear is not None and fear < 0 else 0)
    n = len(votes) + (fear is not None)
    appetite = None if not n else ("risk-on" if score >= 0.75 * n else "risk-off" if score <= 0.25 * n else "neutral")

    if trend == "uptrend" and participation != "weak" and appetite != "risk-off":
        exposure, level = 0.95, "healthy"
    elif trend == "downtrend" or (trend == "mixed" and appetite == "risk-off"):
        exposure, level = 0.25, "defensive"
    else:
        exposure, level = 0.5, "mixed"
    words = {"healthy": "Healthy", "mixed": "Mixed", "defensive": "Defensive"}[level]
    label = f"{words}: S&P 500 {trend}"
    if p200 is not None:
        label += f", {participation} participation ({p200:.0%} of stocks above their 200-day average)"
    if appetite:
        label += f", {appetite}"
    detail = {"level": level, "trend": trend, "spy_above_200d": above, "spy_200d_rising": rising,
              "participation": participation, "risk_appetite": appetite, "appetite_votes": f"{score}/{n}"}
    return label, exposure, detail


def compute(day: date, px: pd.DataFrame | None = None) -> dict:
    px = etf_closes(day) if px is None else px[px.index <= day]
    if px.empty or "SPY" not in px:
        raise RuntimeError(f"no ETF prices for {day}")
    day = px.index[-1]
    br = breadth(day)
    sig = signals(px)
    label, exposure, detail = regime(px, br, sig)
    return {"date": str(day), "regime": label, "exposure": exposure, "regime_detail": detail, "breadth": br,
            "signals": sig, "groups": groups_table(px), "sectors": sectors(day), **stock_lists(day)}


def store(snap: dict) -> None:
    with conn() as c:
        c.execute("""INSERT INTO market_snapshot (date, regime, exposure, data) VALUES (%s, %s, %s, %s)
                     ON CONFLICT (date) DO UPDATE SET regime=EXCLUDED.regime, exposure=EXCLUDED.exposure,
                       data=EXCLUDED.data, computed_at=now()""",
                  (snap["date"], snap["regime"], snap["exposure"], json.dumps(snap)))
