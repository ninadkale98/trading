"""Alpaca market data + asset list. Free plan rules (architecture §3):
SIP (full-market) requests must end ≥ 15 minutes in the past; IEX volume is one exchange only, so we use SIP."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterator

import httpx

from core.config import secret, settings
from core.ingest.http import RateLimiter, request

_cfg = settings()["alpaca"]
_limiter = RateLimiter(_cfg["requests_per_minute"] / 60.0, "alpaca")
_client: httpx.Client | None = None
RESOURCE = "alpaca"


def client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(
            timeout=httpx.Timeout(60.0, connect=15.0),
            headers={"APCA-API-KEY-ID": secret("ALPACA_KEY_ID"), "APCA-API-SECRET-KEY": secret("ALPACA_SECRET_KEY"),
                     "Accept": "application/json"},
        )
    return _client


def get(url: str, params: dict | None = None) -> dict | list:
    return request(client(), _limiter, RESOURCE, "GET", url, params=params).json()


def sip_end() -> datetime:
    """Latest end time the free plan allows for SIP data."""
    return datetime.now(timezone.utc) - timedelta(minutes=_cfg["sip_delay_minutes"])


def _iso(dt: datetime) -> str:
    """API timestamps must be UTC. Database datetimes come back in the session timezone, so convert first."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def trading(path: str, params: dict | None = None) -> dict | list:
    """Read-only GET on the paper trading API (account, positions, orders, portfolio history)."""
    return get(f"{_cfg['trading_url']}{path}", params)


def assets(status: str) -> list[dict]:
    return get(f"{_cfg['trading_url']}/v2/assets", {"status": status, "asset_class": "us_equity"})


def daily_bars(symbols: list[str], start: str, end: datetime | None = None, adjustment: str = "raw") -> Iterator[tuple[str, dict]]:
    """Yield (symbol, bar) for many symbols at once, following pagination."""
    params = {
        "symbols": ",".join(symbols), "timeframe": "1Day", "start": start,
        "end": _iso(end or sip_end()), "feed": "sip",
        "adjustment": adjustment, "limit": 10000, "sort": "asc",
    }
    while True:
        j = get(f"{_cfg['data_url']}/v2/stocks/bars", params)
        for sym, bars in (j.get("bars") or {}).items():
            for b in bars:
                yield sym, b
        token = j.get("next_page_token")
        if not token:
            return
        params["page_token"] = token


def news(start: datetime, end: datetime | None = None, symbols: list[str] | None = None,
         include_content: bool = True) -> Iterator[dict]:
    """All news in [start, end], oldest first, following pagination."""
    params = {"start": _iso(start), "limit": 50, "sort": "asc",
              "include_content": str(include_content).lower(), "exclude_contentless": "false"}
    if end:
        params["end"] = _iso(end)
    if symbols:
        params["symbols"] = ",".join(symbols)
    while True:
        j = get(f"{_cfg['data_url']}/v1beta1/news", params)
        yield from j.get("news") or []
        token = j.get("next_page_token")
        if not token:
            return
        params["page_token"] = token
