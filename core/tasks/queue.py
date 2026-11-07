"""The task queue (docs/architecture.md §14). Every unit of work is a row in `tasks`.

Lifecycle: pending → running → done
                             ↘ pending again (temporary error, growing wait)    ← RetryLater / any exception
                             ↘ deferred      (resource limited; no attempt used) ← ResourceLimited
                             ↘ failed        (Permanent, or out of attempts)
           pending/deferred → expired (past expires_at)
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from core.config import settings
from core.db import conn, execute, query

OPEN = ("pending", "running", "deferred")


def enqueue(type: str, payload: dict | None = None, *, priority: int = 50, resource: str | None = None,
            dedupe_key: str | None = None, run_at: datetime | None = None, expires_at: datetime | None = None,
            max_attempts: int | None = None) -> int | None:
    """Queue a task. Returns its id, or None if an open task with the same dedupe_key already exists."""
    rows = query(
        """
        INSERT INTO tasks (type, payload, priority, resource, dedupe_key, next_try_at, expires_at, max_attempts)
        VALUES (%s, %s, %s, %s, %s, COALESCE(%s, now()), %s, %s)
        ON CONFLICT (dedupe_key) WHERE dedupe_key IS NOT NULL AND status IN ('pending','running','deferred')
        DO NOTHING
        RETURNING id
        """,
        (type, json.dumps(payload or {}), priority, resource, dedupe_key, run_at, expires_at,
         max_attempts or settings()["retry"]["max_attempts"]),
    )
    return rows[0]["id"] if rows else None


def claim(worker: str) -> dict | None:
    """Atomically take the highest-priority ready task (skipping paused resources)."""
    rows = query(
        """
        UPDATE tasks SET status = 'running', locked_by = %s, locked_at = now(),
                         started_at = COALESCE(started_at, now()), attempts = attempts + 1
        WHERE id = (
            SELECT t.id FROM tasks t
            WHERE t.status IN ('pending','deferred') AND t.next_try_at <= now()
              AND (t.expires_at IS NULL OR t.expires_at > now())
              AND (t.resource IS NULL OR NOT EXISTS (
                    SELECT 1 FROM resource_pauses p WHERE p.resource = t.resource AND p.paused_until > now()))
            ORDER BY t.priority DESC, t.next_try_at
            LIMIT 1
            FOR UPDATE SKIP LOCKED)
        RETURNING *
        """,
        (worker,),
    )
    return rows[0] if rows else None


def complete(task_id: int, result: dict | None = None) -> None:
    execute(
        "UPDATE tasks SET status='done', finished_at=now(), result=%s, locked_by=NULL, last_error=NULL WHERE id=%s",
        (json.dumps(result, default=str) if result is not None else None, task_id),
    )


def retry_later(task: dict, message: str, seconds: int | None = None) -> str:
    """Temporary failure: try again after a growing wait, or give up after max_attempts."""
    if task["attempts"] >= task["max_attempts"]:
        fail(task["id"], f"gave up after {task['attempts']} attempts: {message}")
        return "failed"
    ladder = settings()["retry"]["backoff_seconds"]
    wait = seconds if seconds is not None else ladder[min(task["attempts"] - 1, len(ladder) - 1)]
    execute(
        "UPDATE tasks SET status='pending', locked_by=NULL, last_error=%s, next_try_at=now() + make_interval(secs => %s) WHERE id=%s",
        (message[:2000], wait, task["id"]),
    )
    return "retry"


def defer(task: dict, resource: str, until: datetime, message: str) -> None:
    """Limit hit: park the task (attempt not counted) and pause the whole resource until `until`."""
    with conn() as c:
        c.execute(
            "UPDATE tasks SET status='deferred', locked_by=NULL, attempts=GREATEST(attempts-1,0), last_error=%s, next_try_at=%s WHERE id=%s",
            (message[:2000], until, task["id"]),
        )
        c.execute(
            """INSERT INTO resource_pauses (resource, paused_until, reason) VALUES (%s, %s, %s)
               ON CONFLICT (resource) DO UPDATE SET paused_until = GREATEST(resource_pauses.paused_until, EXCLUDED.paused_until),
                                                    reason = EXCLUDED.reason, updated_at = now()""",
            (resource, until, message[:500]),
        )


def fail(task_id: int, message: str) -> None:
    execute(
        "UPDATE tasks SET status='failed', finished_at=now(), locked_by=NULL, last_error=%s WHERE id=%s",
        (message[:2000], task_id),
    )


def save_progress(task_id: int, progress: dict) -> None:
    """Checkpoint so a retried task continues where it stopped."""
    execute("UPDATE tasks SET progress=%s WHERE id=%s", (json.dumps(progress, default=str), task_id))


def expire_stale() -> int:
    return execute(
        "UPDATE tasks SET status='expired', finished_at=now() WHERE status IN ('pending','deferred') AND expires_at IS NOT NULL AND expires_at <= now()"
    )


def recover_running(older_than: timedelta | None = None, worker_prefix: str | None = None) -> int:
    """Put tasks left 'running' by a crashed process back in the queue (attempt not counted)."""
    if older_than is not None:
        return execute(
            "UPDATE tasks SET status='pending', locked_by=NULL, attempts=GREATEST(attempts-1,0), last_error='recovered after worker stopped' "
            "WHERE status='running' AND locked_at < now() - %s",
            (older_than,),
        )
    return execute(
        "UPDATE tasks SET status='pending', locked_by=NULL, attempts=GREATEST(attempts-1,0), last_error='recovered after worker restart' "
        "WHERE status='running' AND (%s::text IS NULL OR locked_by LIKE %s)",
        (worker_prefix, (worker_prefix or "") + "%"),
    )


def pause(resource: str, minutes: float, reason: str = "manual pause") -> None:
    until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    execute(
        """INSERT INTO resource_pauses (resource, paused_until, reason) VALUES (%s, %s, %s)
           ON CONFLICT (resource) DO UPDATE SET paused_until = EXCLUDED.paused_until, reason = EXCLUDED.reason, updated_at = now()""",
        (resource, until, reason),
    )


def resume(resource: str) -> None:
    execute("DELETE FROM resource_pauses WHERE resource=%s", (resource,))


def retry_now(task_id: int) -> None:
    execute(
        "UPDATE tasks SET status='pending', next_try_at=now(), attempts=0, finished_at=NULL, locked_by=NULL WHERE id=%s AND status IN ('failed','deferred','pending','expired')",
        (task_id,),
    )
