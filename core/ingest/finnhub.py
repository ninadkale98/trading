"""Finnhub (free key): earnings calendar with estimates, recent surprises, analyst rating counts, peers, company news.
Free plan: 60 requests/minute; we use 50. The key goes in a header so it never appears in URLs or logs."""
from __future__ import annotations

import httpx

from core.config import secret
from core.ingest.http import RateLimiter, request

BASE = "https://finnhub.io/api/v1"
RESOURCE = "finnhub"
_limiter = RateLimiter(50 / 60, "finnhub")
_client: httpx.Client | None = None


def client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(timeout=httpx.Timeout(60.0, connect=15.0), headers={"X-Finnhub-Token": secret("FINNHUB_API_KEY")})
    return _client


def get(path: str, **params):
    return request(client(), _limiter, RESOURCE, "GET", BASE + path, params=params).json()


def earnings_calendar(start: str, end: str) -> list[dict]:
    return get("/calendar/earnings", **{"from": start, "to": end}).get("earningsCalendar", [])


def recommendation(symbol: str) -> list[dict]:
    return get("/stock/recommendation", symbol=symbol)


def company_news(symbol: str, start: str, end: str) -> list[dict]:
    return get("/company-news", symbol=symbol, **{"from": start, "to": end})
