"""Shared HTTP helpers: per-service rate limiting and mapping of HTTP failures onto task outcomes."""
from __future__ import annotations

import fcntl
import threading
import time
from datetime import datetime, timedelta, timezone

import httpx

from core.tasks.errors import Permanent, ResourceLimited, RetryLater


class RateLimiter:
    """Evenly spaces requests across ALL threads and processes (daemon + CLI) via a lock file,
    so together we never exceed a service's limit (e.g. SEC asks for ≤ 10 requests/second)."""

    def __init__(self, per_second: float, name: str = "default"):
        self.interval = 1.0 / per_second
        self.lock = threading.Lock()
        from core.config import ROOT
        (ROOT / "logs").mkdir(exist_ok=True)
        self.path = ROOT / "logs" / f".ratelimit-{name}"
        self.path.touch(exist_ok=True)

    def wait(self) -> None:
        with self.lock, open(self.path, "r+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                raw = f.read().strip()
                nxt = float(raw) if raw else 0.0
                now = time.time()
                delay = nxt - now
                f.seek(0)
                f.truncate()
                f.write(repr(max(now, nxt) + self.interval))
                f.flush()
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
        if delay > 0:
            time.sleep(delay)


def request(client: httpx.Client, limiter: RateLimiter, resource: str, method: str, url: str, **kw) -> httpx.Response:
    """One HTTP call. 429 → pause the resource; 5xx/network → RetryLater; other 4xx → Permanent."""
    limiter.wait()
    try:
        r = client.request(method, url, **kw)
    except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as e:
        raise RetryLater(f"{resource} network error: {type(e).__name__}: {e}")
    if r.status_code == 429 or (r.status_code == 403 and "rate threshold" in r.text.lower()):
        wait = int(r.headers.get("Retry-After", "60") or 60)
        raise ResourceLimited(resource, datetime.now(timezone.utc) + timedelta(seconds=max(wait, 30)), f"{resource} rate limited (429)")
    if r.status_code >= 500:
        raise RetryLater(f"{resource} server error {r.status_code}")
    if r.status_code >= 400:
        raise Permanent(f"{resource} {r.status_code} for {url}: {r.text[:200]}")
    return r
