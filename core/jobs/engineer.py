"""Weekly engineer task (core/lab/engineer.py): Claude Code builds one system improvement on a branch, fixed checks
run, and the branch waits for review. Nothing is merged automatically."""
from __future__ import annotations

from core.lab import engineer
from core.tasks.registry import TaskContext, task


@task("engineer.weekly", resource="claude:opus", priority=25,
      description="Claude Code (Opus) builds one improvement on a branch; checks run; waits for review")
def weekly(ctx: TaskContext) -> dict:
    return engineer.run_week()
