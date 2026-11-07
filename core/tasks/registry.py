"""Task handlers register themselves here by type name."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from core.log import event
from core.tasks import queue


@dataclass
class TaskContext:
    task: dict
    payload: dict = field(default_factory=dict)
    progress: dict = field(default_factory=dict)

    @property
    def id(self) -> int:
        return self.task["id"]

    def checkpoint(self, **progress) -> None:
        """Save progress so a retry resumes here instead of starting over."""
        self.progress.update(progress)
        queue.save_progress(self.id, self.progress)

    def log(self, message: str, data: dict | None = None, level: str = "info") -> None:
        event(self.task["type"], message, data, level=level, task_id=self.id)


@dataclass
class Handler:
    fn: Callable[[TaskContext], dict | None]
    resource: str | None = None
    priority: int = 50
    description: str = ""


HANDLERS: dict[str, Handler] = {}


def task(name: str, *, resource: str | None = None, priority: int = 50, description: str = ""):
    def deco(fn):
        HANDLERS[name] = Handler(fn, resource, priority, description or (fn.__doc__ or "").strip().split("\n")[0])
        return fn
    return deco


def load_all() -> None:
    """Import every module that defines task handlers."""
    import core.jobs  # noqa: F401  (registers handlers on import)
