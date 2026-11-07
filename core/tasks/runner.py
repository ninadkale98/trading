"""Run one claimed task and translate its outcome into queue state. Never lets an exception escape."""
from __future__ import annotations

import time

from core.db import execute
from core.log import error, event
from core.tasks import queue
from core.tasks.errors import Permanent, ResourceLimited, RetryLater
from core.tasks.registry import HANDLERS, TaskContext


def run(task: dict) -> str:
    handler = HANDLERS.get(task["type"])
    if handler is None:
        # Probably queued by newer code than this daemon is running: wait for a restart instead of failing.
        execute("UPDATE tasks SET status='pending', locked_by=NULL, attempts=GREATEST(attempts-1,0), "
                "next_try_at=now() + interval '5 minutes', last_error=%s WHERE id=%s",
                (f"no handler for '{task['type']}' in this daemon yet; waiting for restart", task["id"]))
        return "waiting"
    ctx = TaskContext(task=task, payload=task.get("payload") or {}, progress=task.get("progress") or {})
    started = time.monotonic()
    try:
        result = handler.fn(ctx) or {}
        secs = round(time.monotonic() - started, 1)
        result.setdefault("seconds", secs)
        queue.complete(task["id"], result)
        summary = result.get("summary")
        if summary:
            event(task["type"], summary, {k: v for k, v in result.items() if k != "summary"}, task_id=task["id"])
        return "done"
    except ResourceLimited as e:
        queue.defer(task, e.resource, e.until, str(e))
        event(task["type"], f"deferred: {e}", level="warn", task_id=task["id"])
        return "deferred"
    except Permanent as e:
        error(e, task["id"], task["type"])
        queue.fail(task["id"], str(e))
        event(task["type"], f"failed permanently: {e}", level="error", task_id=task["id"])
        return "failed"
    except RetryLater as e:
        outcome = queue.retry_later(task, str(e), e.seconds)
        event(task["type"], f"will retry ({task['attempts']}/{task['max_attempts']}): {e}", level="warn", task_id=task["id"])
        return outcome
    except Exception as e:  # unexpected bug or error: log it, retry with backoff, never crash the worker
        error(e, task["id"], task["type"])
        outcome = queue.retry_later(task, f"{type(e).__name__}: {e}")
        event(task["type"], f"error ({task['attempts']}/{task['max_attempts']}): {type(e).__name__}: {e}",
              level="error", task_id=task["id"])
        return outcome
