"""Weekly trade review by Opus (architecture §9 lab notebook, §13 Saturday review). Reads every trade closed this week
and every open position, with entry/exit context and best/worst points, and writes lessons that feed the idea lab."""
from __future__ import annotations

import json
from datetime import date, timedelta

from core.ai import claude
from core.config import ROOT
from core.db import execute, query
from core.execution.run import mode
from core.tasks.registry import TaskContext, task

SYSTEM = """You review the past week's trades of a personal research system (multi-week holds, US stocks, currently
experimental strategies at small size). The reader is learning investing: plain language, explain terms briefly.
For each strategy: what happened, whether results look like skill, luck or noise (be honest: a few trades prove
nothing), and what the entry context suggests (market regime, trend, news, earnings timing). Look for patterns across
trades: e.g. losers entered when breadth was weak, winners had positive news, stops too tight (mae just past the
stop then mfe large). Lessons must be concrete and testable, each with a suggested backtest. No buy/sell advice."""

SCHEMA = {"type": "object", "properties": {
    "review_markdown": {"type": "string"},
    "lessons": {"type": "array", "items": {"type": "object", "properties": {
        "lesson": {"type": "string"}, "evidence": {"type": "string"}, "suggested_test": {"type": "string"}},
        "required": ["lesson", "evidence", "suggested_test"]}}},
    "required": ["review_markdown", "lessons"]}


def _trades(since: date, md: str) -> tuple[list, list]:
    cols = """symbol, strategy, entry_date, entry_price, exit_date, exit_price, exit_reason, shares, pnl, mfe, mae,
              stop, target, trail_pct, spy_entry, spy_exit, entry_context, exit_context"""
    closed = query(f"SELECT {cols} FROM positions_book WHERE mode=%s AND status='closed' AND exit_date >= %s ORDER BY exit_date",
                   (md, since))
    opened = query(f"SELECT {cols} FROM positions_book WHERE mode=%s AND status='open' ORDER BY entry_date", (md,))
    return closed, opened


@task("review.weekly_trades", resource="claude:opus", priority=40, description="Opus reviews the week's trades and writes lessons")
def weekly(ctx: TaskContext) -> dict:
    today = date.today()
    week_start = today - timedelta(days=today.weekday())          # Monday of this week
    md = mode()
    closed, opened = _trades(week_start, md)
    if not closed and not opened:
        return {"summary": "trade review: no trades this week"}
    stats = query("""SELECT strategy, count(*) n, avg((pnl > 0)::int) win, avg(exit_price / entry_price - 1) avg_ret,
                            avg((exit_price / entry_price - 1) - (spy_exit / NULLIF(spy_entry, 0) - 1)) avg_vs_spy
                     FROM positions_book WHERE mode=%s AND status='closed' GROUP BY strategy""", (md,))
    lessons_so_far = query("SELECT week_start, lessons FROM trade_reviews ORDER BY week_start DESC LIMIT 4")
    pack = json.dumps({"mode": md, "week_start": str(week_start), "closed_this_week": closed, "open_positions": opened,
                       "all_time_by_strategy": stats, "recent_lessons": lessons_so_far}, default=str)
    ans = claude.ask(f"Trades to review (JSON):\n{pack}\n\nWrite this week's trade review.", model="opus",
                     purpose="review.weekly_trades", schema=SCHEMA, system=SYSTEM, timeout=1200, task_id=ctx.id)
    d = ans.data
    execute("""INSERT INTO trade_reviews (week_start, model, review_md, lessons) VALUES (%s, 'opus', %s, %s)
               ON CONFLICT (week_start) DO UPDATE SET review_md=EXCLUDED.review_md, lessons=EXCLUDED.lessons, created_at=now()""",
            (week_start, d["review_markdown"], json.dumps(d["lessons"])))
    path = ROOT / "reports" / "weekly" / f"{week_start}-trades.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# Trade review: week of {week_start} ({md})\n\n{d['review_markdown']}\n\n## Lessons\n"
                    + "".join(f"- **{x['lesson']}**. Evidence: {x['evidence']}. Test: {x['suggested_test']}\n" for x in d["lessons"]))
    nb = ROOT / "lab" / "notebook.md"
    if not nb.exists():
        nb.write_text("# Lab notebook\n\nLessons from trade reviews and experiments, newest last. The idea lab reads this "
                      "before proposing new tests, so failures are never repeated blindly.\n")
    with nb.open("a") as f:
        f.write(f"\n## Week of {week_start}: trade review\n" + "".join(
            f"- {x['lesson']} *(evidence: {x['evidence']}; test: {x['suggested_test']})*\n" for x in d["lessons"]))
    return {"summary": f"trade review for week of {week_start}: {len(closed)} closed, {len(opened)} open, "
                       f"{len(d['lessons'])} lessons", "lessons": len(d["lessons"])}
