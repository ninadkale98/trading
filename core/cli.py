"""`tradebot` command line.

  tradebot migrate                     apply database migrations
  tradebot status                      daemon heartbeat, queue counts, pauses, recent failures
  tradebot tasks [--status S] [-n N]   list recent tasks
  tradebot enqueue TYPE [JSON]         queue a task
  tradebot run TYPE [JSON]             run a task right now in this terminal (still recorded in the queue)
  tradebot retry ID                    retry a failed/deferred task now
  tradebot pause RESOURCE MINUTES      pause a resource (e.g. claude:opus, alpaca)
  tradebot resume RESOURCE             un-pause it
  tradebot events [-n N]               recent timeline
  tradebot daemon                      run the background service (normally started by launchd)
  tradebot dashboard                   run the dashboard web server on localhost:8090 (normally started by launchd)
  tradebot approvals                   list trades waiting for the user's approval
  tradebot approve ID [--size 0.5] [--comment ...]    approve (optionally smaller)
  tradebot reject ID [--comment ...]   reject (safe default)
  tradebot plan                        show tomorrow's trade plan
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone


def _fmt_age(ts) -> str:
    if ts is None:
        return "never"
    secs = (datetime.now(timezone.utc) - ts).total_seconds()
    return f"{int(secs)}s ago" if secs < 120 else f"{int(secs // 60)}m ago" if secs < 7200 else f"{secs / 3600:.1f}h ago"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="tradebot")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate")
    sub.add_parser("status")
    t = sub.add_parser("tasks"); t.add_argument("--status"); t.add_argument("-n", type=int, default=20)
    e = sub.add_parser("enqueue"); e.add_argument("type"); e.add_argument("payload", nargs="?", default="{}")
    e.add_argument("--priority", type=int); e.add_argument("--resource")
    r = sub.add_parser("run"); r.add_argument("type"); r.add_argument("payload", nargs="?", default="{}")
    rt = sub.add_parser("retry"); rt.add_argument("id", type=int)
    pa = sub.add_parser("pause"); pa.add_argument("resource"); pa.add_argument("minutes", type=float)
    re_ = sub.add_parser("resume"); re_.add_argument("resource")
    ev = sub.add_parser("events"); ev.add_argument("-n", type=int, default=25)
    sub.add_parser("daemon")
    sub.add_parser("dashboard")
    sub.add_parser("approvals")
    sub.add_parser("plan")
    ap_ = sub.add_parser("approve"); ap_.add_argument("id", type=int); ap_.add_argument("--size", type=float, default=1.0)
    ap_.add_argument("--comment")
    rj = sub.add_parser("reject"); rj.add_argument("id", type=int); rj.add_argument("--comment")
    a = p.parse_args(argv)

    if a.cmd in ("approvals", "approve", "reject"):
        from core.planner import approvals
        if a.cmd == "approvals":
            rows = approvals.pending()
            for r in rows:
                print(f"#{r['id']} [{r['kind']}] {r['title']} · deadline {r['deadline']:%a %H:%M} · "
                      f"risk ${r['risk_dollars'] or 0:,.0f}\n    for: {r['case_for'] or ''}\n    against: {r['case_against'] or ''}")
            print(f"{len(rows)} pending")
        elif a.cmd == "approve":
            print(approvals.decide(a.id, True, a.size, a.comment))
        else:
            print(approvals.decide(a.id, False, comment=a.comment))
        return 0
    if a.cmd == "plan":
        from core.db import query as q
        for r in q("""SELECT trade_date, mode, side, strategy, symbol, shares, limit_price, stop, position_value, status FROM trade_plans
                      WHERE trade_date >= current_date - 1 ORDER BY trade_date, side DESC, strategy"""):
            print(f"{r['trade_date']} {r['mode']:<7} {r['side']:<4} {r['symbol']:<6} {r['shares']:>5} @ ≤{r['limit_price'] or 0:>8.2f} "
                  f"stop {r['stop'] or 0:>8.2f} ${r['position_value'] or 0:>9,.0f}  {r['strategy']:<22} {r['status']}")
        return 0

    if a.cmd == "dashboard":
        from dashboard.app import serve
        serve()
        return 0

    from core.db import migrate, query
    from core.tasks import queue

    if a.cmd == "migrate":
        print("applied:", migrate() or "nothing new")
    elif a.cmd == "daemon":
        from core.daemon import main as daemon_main
        daemon_main()
    elif a.cmd == "status":
        hb = query("SELECT ts, info FROM heartbeats WHERE component='daemon'")
        print(f"daemon heartbeat: {_fmt_age(hb[0]['ts']) if hb else 'never'}")
        for row in query("SELECT status, count(*) n FROM tasks GROUP BY status ORDER BY status"):
            print(f"  {row['status']:<10} {row['n']}")
        for row in query("SELECT resource, paused_until, reason FROM resource_pauses WHERE paused_until > now()"):
            print(f"  PAUSED {row['resource']} until {row['paused_until']:%Y-%m-%d %H:%M} ({row['reason']})")
        fails = query("SELECT id, type, last_error, finished_at FROM tasks WHERE status='failed' ORDER BY finished_at DESC LIMIT 5")
        if fails:
            print("recent failures:")
            for f in fails:
                print(f"  #{f['id']} {f['type']}: {(f['last_error'] or '')[:100]}")
    elif a.cmd == "tasks":
        rows = query(
            "SELECT id, type, status, priority, attempts, max_attempts, next_try_at, created_at, last_error FROM tasks "
            "WHERE (%s::text IS NULL OR status=%s) ORDER BY id DESC LIMIT %s", (a.status, a.status, a.n))
        for r_ in rows:
            err = f"  ⚠ {r_['last_error'][:70]}" if r_["last_error"] else ""
            print(f"#{r_['id']:<6} {r_['type']:<28} {r_['status']:<9} p{r_['priority']:<3} try {r_['attempts']}/{r_['max_attempts']}{err}")
    elif a.cmd == "enqueue":
        from core.tasks.registry import HANDLERS, load_all
        load_all()
        h = HANDLERS.get(a.type)
        tid = queue.enqueue(a.type, json.loads(a.payload), priority=a.priority or (h.priority if h else 50),
                            resource=a.resource or (h.resource if h else None))
        print(f"queued #{tid}" if tid else "already queued")
    elif a.cmd == "run":
        from core.tasks import runner
        from core.tasks.registry import HANDLERS, load_all
        load_all()
        h = HANDLERS.get(a.type)
        if h is None:
            print(f"unknown task type {a.type}; known: {', '.join(sorted(HANDLERS))}")
            return 1
        tid = queue.enqueue(a.type, json.loads(a.payload), priority=1000, resource=h.resource)
        task = query("UPDATE tasks SET status='running', locked_by='cli', locked_at=now(), started_at=now(), attempts=attempts+1 "
                     "WHERE id=%s RETURNING *", (tid,))[0]
        outcome = runner.run(task)
        row = query("SELECT status, result, last_error FROM tasks WHERE id=%s", (tid,))[0]
        print(f"#{tid} {outcome}: {json.dumps(row['result'], default=str) if row['result'] else row['last_error']}")
        return 0 if outcome == "done" else 2
    elif a.cmd == "retry":
        queue.retry_now(a.id); print(f"#{a.id} re-queued")
    elif a.cmd == "pause":
        queue.pause(a.resource, a.minutes); print(f"{a.resource} paused for {a.minutes} min")
    elif a.cmd == "resume":
        queue.resume(a.resource); print(f"{a.resource} resumed")
    elif a.cmd == "events":
        for r_ in reversed(query("SELECT ts, level, kind, message FROM events ORDER BY id DESC LIMIT %s", (a.n,))):
            print(f"{r_['ts']:%m-%d %H:%M:%S} {r_['level']:<5} [{r_['kind']}] {r_['message']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
