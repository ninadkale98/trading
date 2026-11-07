"""Daily price bars (architecture §3, build plan 1.5).

Stored: raw OHLCV + adj_factor (split & dividend). Adjusted price = raw × adj_factor.
Backfill covers our universe + delisted company stocks (for honest backtests). A delisted symbol that is
active again today belongs to a different company (ticker reuse), so it's skipped to avoid mixing histories."""
from __future__ import annotations

import io
from datetime import date, datetime, timedelta, timezone

from core.config import settings
from core.db import conn, query
from core.ingest import alpaca
from core.log import event
from core.tasks import queue
from core.tasks.registry import TaskContext, task

CHUNK = 100


def backfill_symbols() -> list[str]:
    rows = query(
        """SELECT DISTINCT symbol FROM stocks WHERE is_universe
           UNION
           SELECT DISTINCT s.symbol FROM stocks s
           WHERE s.status='inactive' AND s.asset_type='common'
             AND NOT EXISTS (SELECT 1 FROM stocks a WHERE a.symbol=s.symbol AND a.status='active')
           ORDER BY 1""")
    return [r["symbol"] for r in rows]


def universe_symbols() -> list[str]:
    return [r["symbol"] for r in query("SELECT DISTINCT symbol FROM stocks WHERE is_universe ORDER BY 1")]


def _fetch(symbols: list[str], start: str) -> list[tuple]:
    """Raw bars + adjustment factor from a second ('all'-adjusted) pass."""
    raw = {(s, b["t"][:10]): b for s, b in alpaca.daily_bars(symbols, start, adjustment="raw")}
    adj = {(s, b["t"][:10]): b["c"] for s, b in alpaca.daily_bars(symbols, start, adjustment="all")}
    rows = []
    for (sym, d), b in raw.items():
        a = adj.get((sym, d))
        factor = (a / b["c"]) if (a and b["c"]) else 1.0
        rows.append((sym, d, b["o"], b["h"], b["l"], b["c"], int(b["v"]), b.get("vw"), b.get("n"), factor))
    return rows


def _upsert(rows: list[tuple]) -> int:
    if not rows:
        return 0
    buf = io.StringIO()
    for r in rows:
        buf.write("\t".join("\\N" if v is None else str(v) for v in r) + "\n")
    buf.seek(0)
    with conn() as c:
        c.execute("CREATE TEMP TABLE _bars (LIKE daily_prices INCLUDING DEFAULTS) ON COMMIT DROP")
        with c.cursor().copy("COPY _bars (symbol, date, open, high, low, close, volume, vwap, trade_count, adj_factor) FROM STDIN") as cp:
            cp.write(buf.getvalue())
        c.execute(
            """INSERT INTO daily_prices (symbol, date, open, high, low, close, volume, vwap, trade_count, adj_factor)
               SELECT symbol, date, open, high, low, close, volume, vwap, trade_count, adj_factor FROM _bars
               ON CONFLICT (symbol, date) DO UPDATE SET open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low,
                 close=EXCLUDED.close, volume=EXCLUDED.volume, vwap=EXCLUDED.vwap, trade_count=EXCLUDED.trade_count,
                 adj_factor=EXCLUDED.adj_factor, known_at=now()
               WHERE (daily_prices.close, daily_prices.volume, daily_prices.adj_factor)
                     IS DISTINCT FROM (EXCLUDED.close, EXCLUDED.volume, EXCLUDED.adj_factor)""")
    return len(rows)


@task("prices.backfill", resource="alpaca", priority=40, description="Load full daily history (resumable)")
def backfill(ctx: TaskContext) -> dict:
    start = ctx.payload.get("start", settings()["data"]["history_start"])
    symbols = ctx.payload.get("symbols") or backfill_symbols()
    done = ctx.progress.get("chunks_done", 0)
    total_rows = ctx.progress.get("rows", 0)
    chunks = [symbols[i:i + CHUNK] for i in range(0, len(symbols), CHUNK)]
    for i in range(done, len(chunks)):
        total_rows += _upsert(_fetch(chunks[i], start))
        ctx.checkpoint(chunks_done=i + 1, rows=total_rows)
        if (i + 1) % 10 == 0:
            ctx.log(f"backfill {i + 1}/{len(chunks)} chunks, {total_rows:,} bars")
    queue.enqueue("liquidity.compute", {}, priority=60, dedupe_key="liquidity.compute")
    return {"summary": f"price history loaded: {len(symbols):,} symbols, {total_rows:,} bars since {start}",
            "symbols": len(symbols), "rows": total_rows}


@task("prices.daily", resource="alpaca", priority=70, description="Nightly price update for the universe")
def daily(ctx: TaskContext) -> dict:
    """Re-pull the last ~10 trading days (catches late corrections) and detect new splits/dividends."""
    start = (date.today() - timedelta(days=15)).isoformat()
    symbols = universe_symbols()
    before = {(r["symbol"], r["date"].isoformat()): r["adj_factor"] for r in query(
        "SELECT symbol, date, adj_factor FROM daily_prices WHERE date >= %s", (start,))}
    rows, done = [], ctx.progress.get("chunks_done", 0)
    chunks = [symbols[i:i + CHUNK] for i in range(0, len(symbols), CHUNK)]
    n = ctx.progress.get("rows", 0)
    changed: set[str] = set(ctx.progress.get("refactor", []))
    for i in range(done, len(chunks)):
        rows = _fetch(chunks[i], start)
        for r in rows:
            old = before.get((r[0], r[1]))
            if old is not None and abs(old - r[9]) > 1e-6:
                changed.add(r[0])       # a new split/dividend changed history → recompute all factors for it
        n += _upsert(rows)
        ctx.checkpoint(chunks_done=i + 1, rows=n, refactor=sorted(changed))
    for sym in changed:
        queue.enqueue("prices.refactor", {"symbol": sym}, priority=55, dedupe_key=f"refactor:{sym}")
    latest = query("SELECT max(date) d FROM daily_prices")[0]["d"]
    queue.enqueue("liquidity.compute", {}, priority=60, dedupe_key="liquidity.compute")
    queue.enqueue("features.daily", {}, priority=58, dedupe_key="features.daily")
    return {"summary": f"prices updated through {latest}: {len(symbols):,} symbols"
                       + (f"; {len(changed)} split/dividend adjustments queued" if changed else ""),
            "symbols": len(symbols), "rows": n, "latest": str(latest), "refactor": len(changed)}


@task("prices.refactor", resource="alpaca", priority=55, description="Recompute adjustment factors after a split/dividend")
def refactor(ctx: TaskContext) -> dict:
    sym = ctx.payload["symbol"]
    _upsert(_fetch([sym], settings()["data"]["history_start"]))
    return {"summary": f"{sym}: history re-adjusted"}


@task("liquidity.compute", priority=60, description="Daily liquidity tier for every stock")
def liquidity(ctx: TaskContext) -> dict:
    from core.config import limits
    L = limits()["liquidity"]
    with conn() as c:
        c.execute(
            """WITH latest AS (SELECT max(date) d FROM daily_prices),
                    w AS (SELECT p.symbol, p.date, p.close, p.close * p.volume AS dv,
                                 row_number() OVER (PARTITION BY p.symbol ORDER BY p.date DESC) rn
                          FROM daily_prices p, latest WHERE p.date > latest.d - 40),
                    agg AS (SELECT symbol, max(date) FILTER (WHERE rn = 1) date, max(close) FILTER (WHERE rn = 1) price,
                                   avg(dv) FILTER (WHERE rn <= 20) adv FROM w GROUP BY symbol)
               INSERT INTO liquidity (symbol, date, price, adv20_dollar, tier)
               SELECT symbol, date, price, adv,
                      CASE WHEN price < %(minp)s THEN 'emerging'
                           WHEN adv >= %(liq)s THEN 'liquid' WHEN adv >= %(thin)s THEN 'thin' ELSE 'emerging' END
               FROM agg, latest WHERE agg.date >= latest.d - 5
               ON CONFLICT (symbol, date) DO UPDATE SET price=EXCLUDED.price, adv20_dollar=EXCLUDED.adv20_dollar, tier=EXCLUDED.tier""",
            {"minp": L["min_price"], "liq": L["liquid_min_adv"], "thin": L["thin_min_adv"]})
    tiers = query("""SELECT tier, count(*) n FROM liquidity l JOIN stocks s ON s.symbol=l.symbol AND s.is_universe
                     WHERE l.date=(SELECT max(date) FROM liquidity) GROUP BY tier ORDER BY tier""")
    counts = {r["tier"]: r["n"] for r in tiers}
    return {"summary": "liquidity: " + ", ".join(f"{k} {v:,}" for k, v in counts.items()), "tiers": counts}
