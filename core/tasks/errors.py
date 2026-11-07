"""Exceptions a task can raise to tell the queue what to do next."""
from __future__ import annotations

from datetime import datetime


class RetryLater(Exception):
    """Temporary problem (network blip, 5xx). Counts as an attempt; retried after a growing wait."""

    def __init__(self, message: str, seconds: int | None = None):
        super().__init__(message)
        self.seconds = seconds


class ResourceLimited(Exception):
    """A usage/rate limit was hit (e.g. a Claude model, an API). Doesn't count as an attempt:
    the task is deferred and the whole resource is paused until `until`."""

    def __init__(self, resource: str, until: datetime, message: str = ""):
        super().__init__(message or f"{resource} limited until {until.isoformat()}")
        self.resource = resource
        self.until = until


class Permanent(Exception):
    """Can't succeed by retrying (bad input, missing symbol). Fails immediately."""
