"""FRED (St. Louis Fed, free key): economic data. ≤ 120 requests/minute; we use 60.
`output_type=4` returns each value as FIRST published, with the date it was published (point-in-time)."""
from __future__ import annotations

import httpx

from core.config import secret
from core.ingest.http import RateLimiter, request

BASE = "https://api.stlouisfed.org/fred"
RESOURCE = "fred"
_limiter = RateLimiter(1.0, "fred")
_client: httpx.Client | None = None


def get(path: str, **params) -> dict:
    global _client
    if _client is None:
        _client = httpx.Client(timeout=httpx.Timeout(60.0, connect=15.0))
    return request(_client, _limiter, RESOURCE, "GET", BASE + path,
                   params={**params, "api_key": secret("FRED_API_KEY"), "file_type": "json"}).json()


def series_info(series_id: str) -> dict:
    return get("/series", series_id=series_id)["seriess"][0]


def observations(series_id: str, start: str, first_release: bool = False) -> list[dict]:
    p = {"series_id": series_id, "observation_start": start}
    if first_release:
        p.update(output_type=4, realtime_start="1776-07-04", realtime_end="9999-12-31")
    return get("/series/observations", **p)["observations"]
