"""Earnings calendar (Alpha Vantage + Finnhub, daily snapshots), earnings history (Alpha Vantage, within its
25-requests/day budget) and analyst rating counts (Finnhub, weekly). Phase 2.1."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from core.db import conn, query
from core.ingest import alphavantage as av
from core.ingest import finnhub
from core.tasks.registry import TaskContext, task

ET = ZoneInfo("America/New_York")
_TIME = {"pre-market": "before_open", "post-market": "after_close", "bmo": "before_open", "amc": "after_close",
         "dmh": "during_market"}


def _num(v):
    try:
        x = float(v)
        return x if x == x else None
    except (TypeError, ValueError):
        return None


def _date(v):
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def _store_calendar(source: str, rows: list[tuple]) -> int:
    with conn() as c, c.cursor() as cur:
        cur.executemany("""INSERT INTO earnings_calendar (source, as_of, symbol, report_date, fiscal_period_end, fiscal_label,
                                                          eps_estimate, revenue_estimate, time_of_day)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                           ON CONFLICT (source, as_of, symbol, report_date) DO UPDATE SET
                             eps_estimate=EXCLUDED.eps_estimate, revenue_estimate=EXCLUDED.revenue_estimate,
                             time_of_day=EXCLUDED.time_of_day, known_at=now()""", rows)
    return len(rows)


@task("earnings.calendar_av", resource="alphavantage", priority=66, description="Alpha Vantage earnings calendar (next 3 months, 1 request)")
def calendar_av(ctx: TaskContext) -> dict:
    today = datetime.now(ET).date()
    rows = []
    for r in av.earnings_calendar("3month"):
        d = _date(r.get("reportDate"))
        if not r.get("symbol") or d is None:
            continue
        rows.append(("alphavantage", today, r["symbol"], d, _date(r.get("fiscalDateEnding")), None,
                     _num(r.get("estimate")), None, _TIME.get(r.get("timeOfTheDay") or "")))
    n = _store_calendar("alphavantage", rows)
    return {"summary": f"Alpha Vantage calendar: {n:,} upcoming reports", "rows": n}


@task("earnings.calendar_finnhub", resource="finnhub", priority=66, description="Finnhub earnings calendar with EPS/revenue estimates (next ~10 weeks)")
def calendar_finnhub(ctx: TaskContext) -> dict:
    today = datetime.now(ET).date()
    rows, seen = [], set()
    for w in range(10):                         # week-sized windows keep each reply under the provider's cap
        a, b = today + timedelta(days=7 * w), today + timedelta(days=7 * w + 6)
        for r in finnhub.earnings_calendar(a.isoformat(), b.isoformat()):
            d = _date(r.get("date"))
            key = (r.get("symbol"), d)
            if not r.get("symbol") or d is None or key in seen:
                continue
            seen.add(key)
            label = f"{r['year']}Q{r['quarter']}" if r.get("year") and r.get("quarter") else None
            rows.append(("finnhub", today, r["symbol"], d, None, label, _num(r.get("epsEstimate")),
                         _num(r.get("revenueEstimate")), _TIME.get(r.get("hour") or "")))
    n = _store_calendar("finnhub", rows)
    return {"summary": f"Finnhub calendar: {n:,} upcoming reports with estimates", "rows": n}


def _history_queue(limit: int) -> list[str]:
    """Who gets today's Alpha Vantage requests: liquid stocks that just reported (refresh) first,
    then liquid stocks never loaded, biggest first."""
    return [r["symbol"] for r in query("""
        WITH liq AS (SELECT l.symbol, l.adv20_dollar FROM liquidity l
                     JOIN stocks s ON s.symbol = l.symbol AND s.is_universe AND s.asset_type = 'common'
                     WHERE l.date = (SELECT max(date) FROM liquidity) AND l.tier = 'liquid'),
             have AS (SELECT symbol, max(known_at) loaded, max(reported_date) last_rep FROM earnings_history GROUP BY symbol),
             reported AS (SELECT symbol, max(accepted_at) acc FROM earnings_events WHERE accepted_at > now() - interval '10 days' GROUP BY symbol)
        SELECT liq.symbol FROM liq
        LEFT JOIN have h ON h.symbol = liq.symbol
        LEFT JOIN reported r ON r.symbol = liq.symbol
        WHERE h.symbol IS NULL OR (r.acc IS NOT NULL AND h.loaded < r.acc + interval '12 hours')
        ORDER BY (h.symbol IS NOT NULL) DESC, liq.adv20_dollar DESC
        LIMIT %s""", (limit,))]


@task("earnings.history_av", resource="alphavantage", priority=30, description="Earnings history (expected vs actual EPS since 1996), within the daily budget")
def history_av(ctx: TaskContext) -> dict:
    remaining = av.daily_budget() - av.used_today() - 1          # keep one request for tomorrow-morning safety
    symbols = _history_queue(max(remaining, 0))
    stored = 0
    for sym in symbols:
        q = av.earnings(sym).get("quarterlyEarnings", [])
        rows = [("alphavantage", sym, _date(x.get("fiscalDateEnding")), _date(x.get("reportedDate")),
                 _TIME.get(x.get("reportTime") or ""), _num(x.get("reportedEPS")), _num(x.get("estimatedEPS")),
                 _num(x.get("surprise")), _num(x.get("surprisePercentage"))) for x in q if _date(x.get("fiscalDateEnding"))]
        with conn() as c, c.cursor() as cur:
            cur.executemany("""INSERT INTO earnings_history (source, symbol, fiscal_period_end, reported_date, report_time,
                                                             reported_eps, estimated_eps, surprise, surprise_pct)
                               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                               ON CONFLICT (source, symbol, fiscal_period_end) DO UPDATE SET
                                 reported_date=EXCLUDED.reported_date, report_time=EXCLUDED.report_time,
                                 reported_eps=EXCLUDED.reported_eps, estimated_eps=EXCLUDED.estimated_eps,
                                 surprise=EXCLUDED.surprise, surprise_pct=EXCLUDED.surprise_pct, known_at=now()""", rows)
        stored += len(rows)
    have = query("SELECT count(DISTINCT symbol) n FROM earnings_history")[0]["n"]
    return {"summary": f"earnings history: {len(symbols)} stocks updated ({stored:,} quarters); {have:,} stocks covered so far",
            "symbols": symbols, "quarters": stored}


@task("analyst.ratings", resource="finnhub", priority=25, description="Analyst buy/hold/sell counts for liquid and thin stocks (weekly, resumable)")
def ratings(ctx: TaskContext) -> dict:
    syms = ctx.payload.get("symbols") or [r["symbol"] for r in query("""
        SELECT l.symbol FROM liquidity l JOIN stocks s ON s.symbol = l.symbol AND s.is_universe AND s.asset_type = 'common'
        WHERE l.date = (SELECT max(date) FROM liquidity) AND l.tier IN ('liquid', 'thin') ORDER BY l.adv20_dollar DESC""")]
    done = ctx.progress.get("done", 0)
    n = ctx.progress.get("rows", 0)
    for i in range(done, len(syms)):
        recs = finnhub.recommendation(syms[i])
        rows = [(syms[i], _date(r.get("period")), r.get("strongBuy"), r.get("buy"), r.get("hold"), r.get("sell"), r.get("strongSell"))
                for r in recs if _date(r.get("period"))]
        if rows:
            with conn() as c, c.cursor() as cur:
                cur.executemany("""INSERT INTO analyst_ratings (symbol, period, strong_buy, buy, hold, sell, strong_sell)
                                   VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (symbol, period) DO UPDATE SET
                                     strong_buy=EXCLUDED.strong_buy, buy=EXCLUDED.buy, hold=EXCLUDED.hold,
                                     sell=EXCLUDED.sell, strong_sell=EXCLUDED.strong_sell, known_at=now()""", rows)
            n += len(rows)
        if (i + 1) % 50 == 0 or i + 1 == len(syms):
            ctx.checkpoint(done=i + 1, rows=n)
    return {"summary": f"analyst ratings: {len(syms):,} stocks, {n:,} monthly rows", "stocks": len(syms), "rows": n}
