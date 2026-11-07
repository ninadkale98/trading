"""News from Alpaca (Benzinga + others). Architecture §3.
Full article text is kept only for stock-focused items (≤ 3 tagged symbols); market-wide stories keep
headline + summary. Polled every 15 minutes; backfill covers the last ~2 years."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from core.config import settings
from core.db import conn, query
from core.ingest import alpaca
from core.tasks.registry import TaskContext, task

FOCUSED_MAX_SYMBOLS = 3


def _store(items: list[dict]) -> int:
    if not items:
        return 0
    rows = []
    for n in items:
        syms = n.get("symbols") or []
        rows.append((n["id"], n["created_at"], n.get("updated_at"), (n.get("headline") or "")[:2000],
                     n.get("summary") or None, (n.get("content") or None) if len(syms) <= FOCUSED_MAX_SYMBOLS else None,
                     n.get("author"), n.get("source"), n.get("url"), syms))
    with conn() as c:
        with c.cursor() as cur:
            cur.executemany(
                """INSERT INTO news (id, created_at, updated_at, headline, summary, content, author, source, url, symbols)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (id) DO UPDATE SET updated_at=EXCLUDED.updated_at, headline=EXCLUDED.headline,
                     summary=EXCLUDED.summary, content=COALESCE(EXCLUDED.content, news.content), symbols=EXCLUDED.symbols
                   WHERE news.updated_at IS DISTINCT FROM EXCLUDED.updated_at""", rows)
    return len(rows)


def _pull(start: datetime, end: datetime | None, ctx: TaskContext | None = None, batch: int = 500) -> int:
    buf, n = [], 0
    for item in alpaca.news(start, end):
        buf.append(item)
        if len(buf) >= batch:
            n += _store(buf)
            if ctx:
                ctx.checkpoint(cursor=buf[-1]["created_at"], stored=n + ctx.progress.get("stored_before", 0))
            buf = []
    return n + _store(buf)


@task("news.poll", resource="alpaca", priority=75, description="Fetch new news since the last stored item")
def poll(ctx: TaskContext) -> dict:
    last = query("SELECT max(created_at) t FROM news")[0]["t"]
    start = (last - timedelta(minutes=5)) if last else datetime.now(timezone.utc) - timedelta(hours=6)
    n = _pull(start, None)
    focused = query("SELECT count(*) c FROM news WHERE created_at >= %s AND n_symbols BETWEEN 1 AND 3", (start,))[0]["c"]
    return {"summary": f"news: {n} items ({focused} stock-focused)" if n else None, "items": n}


@task("news.backfill", resource="alpaca", priority=20, description="Load ~2 years of past news (resumable, low priority)")
def backfill(ctx: TaskContext) -> dict:
    days = ctx.payload.get("days", settings()["data"]["news_backfill_days"])
    end = datetime.fromisoformat(ctx.payload["end"]) if ctx.payload.get("end") else datetime.now(timezone.utc)
    start = datetime.fromisoformat(ctx.progress["cursor"].replace("Z", "+00:00")) if ctx.progress.get("cursor") \
        else end - timedelta(days=days)
    ctx.progress.setdefault("stored_before", ctx.progress.get("stored", 0))
    n = _pull(start, end, ctx)
    total = query("SELECT count(*) c, min(created_at) a FROM news")[0]
    return {"summary": f"news backfill done: {total['c']:,} items stored since {total['a']:%Y-%m-%d}", "items": n}
