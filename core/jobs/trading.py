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
    from core.execution.journal import update_excursions
    day = query("SELECT max(date) d FROM daily_prices WHERE symbol='SPY'")[0]["d"]
    out, parts = {}, []
    for md in ex.books():                  # paper mode: the shadow dry-run book is settled too
        r = ex.simulate_session(day) if md == "dry_run" else ex.sync_paper(day)
        r["excursions_updated"] = update_excursions(md, day)
        out[md] = r
        parts.append(f"{md}: {r}")
    queue.enqueue("strategies.plan", {}, priority=55, dedupe_key="strategies.plan")
    return {"summary": f"session {day} settled ({'; '.join(parts)})", **out[ex.mode()], "books": out}


@task("strategies.plan", priority=55, description="Strategies pick candidates; planner sizes tomorrow's trades")
def plan(ctx: TaskContext) -> dict:
    res = [plan_day(md=md) for md in ex.books()]
    if len(res) == 1:
        return res[0]
    return {**res[0], "summary": res[0]["summary"] + f" | shadow {res[1]['summary']}", "shadow": res[1]}


@task("trading.open", priority=90, description="Before the open: expire unanswered approvals; send paper orders")
def open_(ctx: TaskContext) -> dict:
    expired = ex.expire_approvals()
    today = datetime.now(ET).date()
    nc = ex.news_check(today)          # major bad news since the plan → that buy is skipped
    for md in ex.books()[1:]:          # the shadow dry-run book gets the same check, so the two books stay comparable
        ex.news_check(today, md)
    note = (f"; skipped for bad news: {', '.join(nc['news_skipped'])}" if nc["news_skipped"] else "") + \
           (f"; held with bad news: {', '.join(nc['news_flagged'])}" if nc["news_flagged"] else "")
    if ex.mode() != "paper":
        return {"summary": f"dry run: no orders sent ({expired} approvals expired){note}", "expired": expired, **nc}
    r = ex.submit_paper(today)
    return {"summary": f"paper orders sent: {r['sent']}" + (f"; {len(r['errors'])} failed" if r["errors"] else "")
                       + f"; {expired} approvals expired{note}", **r, **nc}


@task("trading.sync", priority=85, description="Paper account: record fills, closes and raise trailing stops")
def sync(ctx: TaskContext) -> dict:
    if ex.mode() != "paper":
        return {"summary": "dry run: nothing to sync"}
    r = ex.sync_paper(datetime.now(ET).date())
    return {"summary": f"paper sync: {r}", **r}
