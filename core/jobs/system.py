"""Housekeeping and self-test tasks."""
from __future__ import annotations

import random
import time
from datetime import datetime, timedelta, timezone

from core.tasks.errors import Permanent, ResourceLimited, RetryLater
from core.tasks.registry import TaskContext, task


@task("system.noop", description="Does nothing; checks the queue works")
def noop(ctx: TaskContext) -> dict:
    return {"summary": "noop ok"}


@task("system.selftest", description="Simulates failure modes to prove the queue survives them")
def selftest(ctx: TaskContext) -> dict:
    mode = ctx.payload.get("mode", "ok")
    if mode == "crash":
        raise ValueError("simulated bug")
    if mode == "flaky":
        if ctx.task["attempts"] < 2:
            raise RetryLater("simulated network blip", seconds=1)
        return {"summary": f"flaky task succeeded on attempt {ctx.task['attempts']}"}
    if mode == "limited":
        raise ResourceLimited(ctx.task.get("resource") or "test:resource",
                              datetime.now(timezone.utc) + timedelta(seconds=ctx.payload.get("pause_seconds", 5)),
                              "simulated usage limit")
    if mode == "permanent":
        raise Permanent("simulated bad input")
    if mode == "resume":
        done = ctx.progress.get("done", 0)
        for i in range(done, 5):
            if i == 3 and ctx.task["attempts"] == 1:
                raise RetryLater("simulated failure mid-way", seconds=1)
            ctx.checkpoint(done=i + 1)
        return {"summary": f"resumed from step {done}, finished all 5"}
    time.sleep(random.uniform(0, 0.2))
    return {"summary": "selftest ok"}
