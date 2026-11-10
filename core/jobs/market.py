"""Market snapshot jobs (Phase 2.1b): nightly after features, plus a backfill over the stored feature window."""
from __future__ import annotations

from datetime import date

from core.db import query
from core.market import snapshot
from core.tasks.registry import TaskContext, task


@task("market.snapshot", priority=57, description="Daily market snapshot: breadth, rotation, cross-asset, regime")
def daily(ctx: TaskContext) -> dict:
    day = query("SELECT max(date) d FROM features_daily WHERE symbol='SPY'")[0]["d"]
    snap = snapshot.compute(day)
    from core.market import crash_watch
    snap["crash_watch"] = crash_watch.compute(day)        # big companies far below their recent high (watch only)
    snapshot.store(snap)
    from core.tasks import queue
    queue.enqueue("trading.eod", {}, priority=56, dedupe_key="trading.eod")
    return {"summary": f"market {snap['date']}: {snap['regime']}", "date": snap["date"], "exposure": snap["exposure"]}


@task("market.backfill", priority=35, description="Market snapshots for every stored feature date (resumable)")
def backfill(ctx: TaskContext) -> dict:
    days = [r["date"] for r in query("SELECT DISTINCT date FROM features_daily WHERE symbol='SPY' ORDER BY date")]
    done_until = ctx.progress.get("done_until")
    if done_until:
        days = [d for d in days if d > date.fromisoformat(done_until)]
    if not days:
        return {"summary": "market snapshots: nothing to do"}
    px = snapshot.etf_closes(days[-1], days=(days[-1] - days[0]).days + 420)
    for i, d in enumerate(days, 1):
        snapshot.store(snapshot.compute(d, px))
        if i % 25 == 0 or i == len(days):
            ctx.checkpoint(done_until=str(d))
    return {"summary": f"market snapshots stored for {len(days)} days ({days[0]} → {days[-1]})", "days": len(days)}
