"""Turns recurring schedules into tasks. If the daemon was down when a job was due, the job still runs on
startup, as long as it's within that schedule's catch-up window (expires_minutes); older runs are skipped."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from core.config import settings
from core.db import execute, query
from core.log import event
from core.tasks import cron, queue

TZ = ZoneInfo(settings()["timezone"])


def sync(definitions: list[dict]) -> None:
    """Upsert schedule definitions from code (core/schedules.py) into the `schedules` table."""
    names = [d["name"] for d in definitions]
    for d in definitions:
        execute(
            """INSERT INTO schedules (name, task_type, payload, cron, priority, resource, expires_minutes, enabled)
               VALUES (%(name)s, %(task_type)s, %(payload)s, %(cron)s, %(priority)s, %(resource)s, %(expires_minutes)s, %(enabled)s)
               ON CONFLICT (name) DO UPDATE SET task_type=EXCLUDED.task_type, payload=EXCLUDED.payload, cron=EXCLUDED.cron,
                 priority=EXCLUDED.priority, resource=EXCLUDED.resource, expires_minutes=EXCLUDED.expires_minutes,
                 enabled=EXCLUDED.enabled""",
            {"payload": json.dumps(d.get("payload", {})), "priority": d.get("priority", 50), "resource": d.get("resource"),
             "expires_minutes": d.get("expires_minutes", 60), "enabled": d.get("enabled", True), **d},
        )
    execute("UPDATE schedules SET enabled=false WHERE NOT (name = ANY(%s))", (names,))


def tick(now: datetime | None = None) -> list[str]:
    """Enqueue every schedule that has come due since it last fired. Safe to call often."""
    now = (now or datetime.now(TZ)).astimezone(TZ)
    fired = []
    for s in query("SELECT * FROM schedules WHERE enabled"):
        window = max(int(s["expires_minutes"] or 60), 1)
        due = cron.last_due(s["cron"], now, window)
        if due is None:
            continue
        last = s["last_fired_at"].astimezone(TZ) if s["last_fired_at"] else None
        if last is not None and last >= due:
            continue
        queue.enqueue(
            s["task_type"], s["payload"], priority=s["priority"], resource=s["resource"],
            dedupe_key=f"sched:{s['name']}:{due.isoformat()}", expires_at=due + timedelta(minutes=window),
        )
        execute("UPDATE schedules SET last_fired_at=%s WHERE name=%s", (due, s["name"]))
        fired.append(s["name"])
    if fired:
        event("scheduler", f"queued: {', '.join(fired)}")
    return fired
