"""Trading jobs (build plan 2.4–2.6). Evening chain: market.snapshot → trading.eod → strategies.plan.
Morning: trading.open at 9:20 ET. Paper mode only: trading.sync every 15 minutes in market hours."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from core.db import query
from core.execution import run as ex
from core.planner.plan import plan_day
from core.tasks import queue
from core.tasks.registry import TaskContext, task

ET = ZoneInfo("America/New_York")


@task("trading.eod", priority=56, description="Settle today's session: simulate dry-run fills/stops or sync the paper account")
def eod(ctx: TaskContext) -> dict:
    day = query("SELECT max(date) d FROM daily_prices WHERE symbol='SPY'")[0]["d"]
    r = ex.simulate_session(day) if ex.mode() == "dry_run" else ex.sync_paper(day)
    from core.execution.journal import update_excursions
    r["excursions_updated"] = update_excursions(ex.mode(), day)
    queue.enqueue("strategies.plan", {}, priority=55, dedupe_key="strategies.plan")
    return {"summary": f"session {day} settled ({ex.mode()}): {r}", **r}


@task("strategies.plan", priority=55, description="Strategies pick candidates; planner sizes tomorrow's trades")
def plan(ctx: TaskContext) -> dict:
    return plan_day()


@task("trading.open", priority=90, description="Before the open: expire unanswered approvals; send paper orders")
def open_(ctx: TaskContext) -> dict:
    expired = ex.expire_approvals()
    today = datetime.now(ET).date()
    if ex.mode() != "paper":
        return {"summary": f"dry run: no orders sent ({expired} approvals expired)", "expired": expired}
    r = ex.submit_paper(today)
    return {"summary": f"paper orders sent: {r['sent']}" + (f"; {len(r['errors'])} failed" if r["errors"] else "")
                       + f"; {expired} approvals expired", **r}


@task("trading.sync", priority=85, description="Paper account: record fills, closes and raise trailing stops")
def sync(ctx: TaskContext) -> dict:
    if ex.mode() != "paper":
        return {"summary": "dry run: nothing to sync"}
    r = ex.sync_paper(datetime.now(ET).date())
    return {"summary": f"paper sync: {r}", **r}
