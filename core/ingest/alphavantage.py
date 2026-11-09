"""Alpha Vantage (free key): 25 requests per DAY, so every call is counted in `api_usage` and the daily budget is
enforced here. The daily-limit reply is a 200 with an "Information"/"Note" message, mapped to ResourceLimited."""
from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx

from core.config import secret, settings
from core.db import execute, query
from core.ingest.http import RateLimiter, request
from core.tasks.errors import Permanent, ResourceLimited

BASE = "https://www.alphavantage.co/query"
RESOURCE = "alphavantage"
ET = ZoneInfo("America/New_York")
_limiter = RateLimiter(1 / 3, "alphavantage")      # a short gap between calls
_client: httpx.Client | None = None


def daily_budget() -> int:
    return int(settings().get("alphavantage", {}).get("requests_per_day", 25))


def used_today() -> int:
    r = query("SELECT n FROM api_usage WHERE source=%s AND day=%s", (RESOURCE, datetime.now(ET).date()))
    return r[0]["n"] if r else 0


def _next_reset() -> datetime:
    tomorrow = datetime.now(ET).date() + timedelta(days=1)
    return datetime(tomorrow.year, tomorrow.month, tomorrow.day, 0, 5, tzinfo=ET).astimezone(timezone.utc)


def _call(**params) -> httpx.Response:
    if used_today() >= daily_budget():
        raise ResourceLimited(RESOURCE, _next_reset(), f"Alpha Vantage daily budget ({daily_budget()}) used")
    global _client
    if _client is None:
        _client = httpx.Client(timeout=httpx.Timeout(60.0, connect=15.0))
    r = request(_client, _limiter, RESOURCE, "GET", BASE, params={**params, "apikey": secret("ALPHA_VANTAGE_API_KEY")})
    execute("""INSERT INTO api_usage (source, day, n) VALUES (%s, %s, 1)
               ON CONFLICT (source, day) DO UPDATE SET n = api_usage.n + 1, updated_at = now()""",
            (RESOURCE, datetime.now(ET).date()))
    head = r.text[:400]
    if '"Information"' in head or '"Note"' in head:
        # only "this is a premium endpoint" is permanent; rate-limit notes also mention "premium plans"
        if "premium endpoint" in head.lower():
            raise Permanent(f"Alpha Vantage: premium-only endpoint ({params.get('function')})")
        raise ResourceLimited(RESOURCE, _next_reset(), "Alpha Vantage limit reached")
    if '"Error Message"' in head:
        raise Permanent(f"Alpha Vantage error for {params.get('function')} {params.get('symbol', '')}")
    return r


def earnings_calendar(horizon: str = "3month") -> list[dict]:
    return list(csv.DictReader(io.StringIO(_call(function="EARNINGS_CALENDAR", horizon=horizon).text)))


def earnings(symbol: str) -> dict:
    return _call(function="EARNINGS", symbol=symbol).json()
