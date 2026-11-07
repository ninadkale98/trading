"""Daily features for every stock (Phase 2.1). Nightly after prices; backfill for the stored window."""
from __future__ import annotations

from datetime import date, timedelta

from core.config import settings
from core.db import query
from core.features.build import build_range
from core.tasks import queue
from core.tasks.registry import TaskContext, task


def _store_from() -> date:
    return date.fromisoformat(str(settings().get("features", {}).get("store_from", "2024-01-01")))


@task("features.daily", priority=58, description="Compute today's features for every stock (after the price update)")
def daily(ctx: TaskContext) -> dict:
    latest = query("SELECT max(date) d FROM daily_prices WHERE symbol='SPY'")[0]["d"]
    # recompute the last ~2 weeks so late price corrections and new splits flow through
    n = build_range(latest - timedelta(days=14), latest)
    queue.enqueue("market.snapshot", {}, priority=57, dedupe_key="market.snapshot")
    return {"summary": f"features through {latest}: {n:,} rows (last 2 weeks refreshed)", "rows": n, "latest": str(latest)}


@task("features.backfill", priority=40, description="Compute and store features for the stored history window (resumable by year)")
def backfill(ctx: TaskContext) -> dict:
    start = date.fromisoformat(ctx.payload["from"]) if ctx.payload.get("from") else _store_from()
    today = date.today()
    years = list(range(start.year, today.year + 1))
    done = set(ctx.progress.get("years", []))
    total = ctx.progress.get("rows", 0)
    for y in years:
        if y in done:
            continue
        a = max(start, date(y, 1, 1))
        b = min(today, date(y, 12, 31))
        n = build_range(a, b)
        total += n
        done.add(y)
        ctx.checkpoint(years=sorted(done), rows=total)
        ctx.log(f"features {y}: {n:,} rows")
    queue.enqueue("market.backfill", {}, priority=35, dedupe_key="market.backfill")
    return {"summary": f"features stored from {start}: {total:,} rows", "rows": total}
