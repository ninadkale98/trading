"""Trade journal for learning: the context of every entry and exit, and how far each trade went for/against us."""
from __future__ import annotations

import json

from core.db import query

FEATURES = ["close", "ret_5d", "ret_20d", "ret_60d", "dist_sma50", "dist_sma200", "rsi14", "atr_pct", "rvol", "accum_50",
            "dist_52w_high", "rs_rank", "rs_sector_60", "beta_250", "trend_score", "days_since_earnings",
            "earnings_reaction", "days_to_earnings_est", "market_cap", "rev_growth_yoy", "op_margin", "pe",
            "insider_buyers_90d", "news_count_5d", "news_score_5d", "news_major_5d"]


def _features(symbol: str, day) -> dict:
    r = query(f"SELECT {', '.join(FEATURES)} FROM features_daily WHERE symbol=%s AND date<=%s ORDER BY date DESC LIMIT 1",
              (symbol, day))
    if not r:
        return {}
    return {k: (round(float(v), 4) if isinstance(v, float) else v) for k, v in r[0].items() if v is not None}


def _market(day) -> dict:
    r = query("""SELECT date, regime, exposure, (data->'breadth'->>'pct_above_200d')::float a200 FROM market_snapshot
                 WHERE date<=%s ORDER BY date DESC LIMIT 1""", (day,))
    return {"date": str(r[0]["date"]), "regime": r[0]["regime"], "exposure": r[0]["exposure"], "pct_above_200d": r[0]["a200"]} if r else {}


def entry_context(plan: dict) -> str:
    news = query("""SELECT e.created_at::date d, e.event_type, e.direction, e.importance, left(n.headline, 160) headline
                    FROM news_events e JOIN news n ON n.id = e.news_id
                    WHERE e.symbol=%s AND e.created_at > %s::date - 7 AND e.created_at < %s::date + 1
                    ORDER BY e.importance DESC, e.created_at DESC LIMIT 5""", (plan["symbol"], plan["signal_date"], plan["signal_date"]))
    sector = query("SELECT sector FROM stocks WHERE symbol=%s AND sector IS NOT NULL LIMIT 1", (plan["symbol"],))
    return json.dumps({"strategy": plan["strategy"], "reason": plan.get("reason"), "signal_date": str(plan["signal_date"]),
                       "sector": sector[0]["sector"] if sector else None, "features": _features(plan["symbol"], plan["signal_date"]),
                       "market": _market(plan["signal_date"]),
                       "news": [{**n, "d": str(n["d"])} for n in news]}, default=str)


def exit_context(symbol: str, day, reason: str) -> str:
    return json.dumps({"reason": reason, "features": _features(symbol, day), "market": _market(day)}, default=str)


def update_excursions(mode: str, day) -> int:
    """Best (MFE) and worst (MAE) point of every open position since entry, as % from the entry price."""
    return len(query("""UPDATE positions_book b SET
                            mfe = x.hi / b.entry_price - 1, mae = x.lo / b.entry_price - 1
                        FROM (SELECT b2.id, max(p.high) hi, min(p.low) lo FROM positions_book b2
                              JOIN daily_prices p ON p.symbol = b2.symbol AND p.date BETWEEN b2.entry_date AND %s
                              WHERE b2.mode=%s AND b2.status='open' GROUP BY b2.id) x
                        WHERE b.id = x.id RETURNING b.id""", (day, mode)))
