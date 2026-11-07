"""Tiny cron-expression matcher: "minute hour day-of-month month day-of-week" (0=Sunday … 6=Saturday).
Supports *, numbers, lists (1,2), ranges (1-5) and steps (*/15, 9-16/2)."""
from __future__ import annotations

from datetime import datetime, timedelta
from functools import lru_cache

_RANGES = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 6)]


def _field(spec: str, lo: int, hi: int) -> frozenset[int]:
    out: set[int] = set()
    for part in spec.split(","):
        step = 1
        if "/" in part:
            part, s = part.split("/")
            step = int(s)
        if part == "*":
            a, b = lo, hi
        elif "-" in part:
            a, b = map(int, part.split("-"))
        else:
            a = b = int(part)
        out.update(range(a, b + 1, step))
    return frozenset(v for v in out if lo <= v <= hi)


@lru_cache(maxsize=256)
def parse(expr: str) -> tuple[frozenset[int], ...]:
    parts = expr.split()
    if len(parts) != 5:
        raise ValueError(f"cron needs 5 fields: {expr!r}")
    return tuple(_field(p, lo, hi) for p, (lo, hi) in zip(parts, _RANGES))


def matches(expr: str, dt: datetime) -> bool:
    m, h, dom, mon, dow = parse(expr)
    return (dt.minute in m and dt.hour in h and dt.day in dom and dt.month in mon
            and (dt.isoweekday() % 7) in dow)


def last_due(expr: str, now: datetime, lookback_minutes: int) -> datetime | None:
    """Most recent minute ≤ now (within the lookback) when `expr` was due."""
    t = now.replace(second=0, microsecond=0)
    for _ in range(lookback_minutes + 1):
        if matches(expr, t):
            return t
        t -= timedelta(minutes=1)
    return None


def next_due(expr: str, now: datetime, lookahead_minutes: int = 8 * 24 * 60) -> datetime | None:
    """First minute > now when `expr` is due (within the lookahead)."""
    t = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(lookahead_minutes):
        if matches(expr, t):
            return t
        t += timedelta(minutes=1)
    return None
