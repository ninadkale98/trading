"""SEC EDGAR client. Free, no account; requires a name + email header (SEC_USER_AGENT in .env)
and ≤ 10 requests/second."""
from __future__ import annotations

import httpx

from core.config import secret, settings
from core.ingest.http import RateLimiter, request

_limiter = RateLimiter(settings()["sec"]["requests_per_second"], "sec")
_client: httpx.Client | None = None
RESOURCE = "sec"


def client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(timeout=httpx.Timeout(60.0, connect=15.0),
                               headers={"User-Agent": secret("SEC_USER_AGENT"), "Accept-Encoding": "gzip, deflate"})
    return _client


def get_json(url: str) -> dict:
    return request(client(), _limiter, RESOURCE, "GET", url).json()


def get_text(url: str) -> str:
    return request(client(), _limiter, RESOURCE, "GET", url).text


def company_tickers() -> list[dict]:
    d = get_json("https://www.sec.gov/files/company_tickers_exchange.json")
    return [dict(zip(d["fields"], row)) for row in d["data"]]


def submissions(cik: int) -> dict:
    return get_json(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")


def company_facts(cik: int) -> dict:
    return get_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json")
