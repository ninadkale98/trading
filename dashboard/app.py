"""Dashboard: a small FastAPI app on the always-on Mac (architecture §16).

JSON endpoints under /api feed a single light-theme page (static/index.html). It reads the same PostgreSQL as the
daemon and only *requests* changes the queue already supports (retry, pause, resume, run a schedule now).
It never places orders. Bound to 127.0.0.1; reached through VS Code port forwarding.
"""
from __future__ import annotations

import shutil
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from core.config import ROOT, settings
from core.db import query
from core.tasks import cron, queue

ET = ZoneInfo("America/New_York")
STATIC = Path(__file__).parent / "static"
app = FastAPI(title="tradebot dashboard", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.middleware("http")
async def no_stale_files(request, call_next):
    """Always revalidate the page and its scripts, so an update shows up on the next refresh."""
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-cache"
    return response


# ── small helpers ─────────────────────────────────────────────────────────────────────────────────────────
_cache: dict[str, tuple[float, object]] = {}
_cache_lock = threading.Lock()


def cached(key: str, seconds: float, fn):
    """Cache slow or rate-limited lookups (Alpaca, big counts) for a few seconds."""
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < seconds:
            return hit[1]
    val = fn()
    with _cache_lock:
        _cache[key] = (now, val)
    return val


def _alpaca_safe(fn, default=None):
    """Alpaca problems must never break a page: return the error text instead."""
    try:
        return fn(), None
    except Exception as e:  # noqa: BLE001 - shown to the user, not swallowed
        return default, f"{type(e).__name__}: {str(e)[:200]}"


def trading_days(start: date, end: date) -> list[date]:
    def load():
        from core.ingest import alpaca
        rows = alpaca.trading("/v2/calendar", {"start": start.isoformat(), "end": end.isoformat()})
        return [date.fromisoformat(r["date"]) for r in rows]
    days, _err = _alpaca_safe(lambda: cached(f"cal:{start}:{end}", 6 * 3600, load), [])
    if not days:  # fallback: weekdays
        days = [start + timedelta(d) for d in range((end - start).days + 1) if (start + timedelta(d)).weekday() < 5]
    return days


def expected_price_date(now_et: datetime) -> date:
    """Latest trading day whose daily bars should already be stored (they load at 4:40 pm ET)."""
    days = trading_days(now_et.date() - timedelta(days=10), now_et.date())
    ready = [d for d in days if d < now_et.date() or (d == now_et.date() and now_et.hour * 60 + now_et.minute >= 17 * 60 + 15)]
    return ready[-1] if ready else now_et.date()


def heartbeat() -> dict:
    hb = query("SELECT ts, info FROM heartbeats WHERE component='daemon'")
    if not hb:
        return {"ok": False, "age_s": None, "info": None}
    age = (datetime.now(timezone.utc) - hb[0]["ts"]).total_seconds()
    return {"ok": age < 180, "age_s": int(age), "ts": hb[0]["ts"], "info": hb[0]["info"]}


def freshness() -> list[dict]:
    """Each dataset: newest data we hold, and whether that's as fresh as it should be."""
    now_et = datetime.now(ET)
    exp = expected_price_date(now_et)
    r = query("""SELECT
        (SELECT max(date) FROM daily_prices WHERE symbol='SPY')                      AS prices,
        (SELECT max(date) FROM liquidity)                                              AS liquidity,
        (SELECT max(created_at) FROM news)                                             AS news,
        (SELECT max(filed_at) FROM filings)                                            AS filings,
        (SELECT max(filed_at) FROM insider_trades)                                     AS insider,
        (SELECT max(finished_at) FROM tasks WHERE type='system.backup' AND status='done') AS backup""")[0]
    now = datetime.now(timezone.utc)
    prev_day = trading_days(exp - timedelta(days=10), exp)[-2] if exp else exp

    def row(name, value, ok, expect, note=""):
        return {"name": name, "latest": value, "ok": ok, "expected": expect, "note": note}

    out = [
        row("Daily prices", r["prices"], r["prices"] is not None and r["prices"] >= exp, f"{exp}",
            "loads 4:40 pm ET on trading days"),
        row("Liquidity tiers", r["liquidity"], r["liquidity"] is not None and r["liquidity"] >= exp, f"{exp}",
            "after the price load"),
        row("News", r["news"], r["news"] is not None and (now - r["news"]).total_seconds() < 3 * 3600,
            "within 3 hours", "polled every 15 min"),
        row("SEC filings", r["filings"], r["filings"] is not None and r["filings"] >= prev_day, f"{prev_day}",
            "nightly 10:15 pm ET"),
        row("Insider trades", r["insider"], r["insider"] is not None and (now_et.date() - r["insider"]).days <= 7,
            "within 7 days", "nightly 11 pm ET"),
        row("Database backup", r["backup"], r["backup"] is not None and (now - r["backup"]).total_seconds() < 30 * 3600,
            "within 30 hours", "nightly 2 am"),
    ]
    return out


def attention() -> list[dict]:
    """Plain-language list of things the user should know about right now."""
    items = []
    hb = heartbeat()
    if not hb["ok"]:
        items.append({"level": "error", "text": "The background service isn't running (no heartbeat for "
                      f"{hb['age_s'] // 60 if hb['age_s'] else '?'} min). Restart: launchctl kickstart -k gui/$(id -u)/com.ninad.tradebot"})
    elif (hb["info"] or {}).get("scheduler_age_s") is None or hb["info"]["scheduler_age_s"] > 300:
        items.append({"level": "error", "text": "The scheduler hasn't completed a pass in over 5 minutes, so scheduled jobs "
                      "aren't being queued. Check Health → recent errors."})
    for f in freshness():
        if not f["ok"]:
            items.append({"level": "warn", "text": f"{f['name']} is behind: newest is {f['latest'] or 'none'}, expected {f['expected']}."})
    n_failed = query("SELECT count(*) n FROM tasks WHERE status='failed' AND finished_at > now() - interval '7 days'")[0]["n"]
    if n_failed:
        items.append({"level": "error", "text": f"{n_failed} task(s) failed in the last 7 days. See Health."})
    for p in query("SELECT resource, paused_until, reason FROM resource_pauses WHERE paused_until > now()"):
        items.append({"level": "info", "text": f"{p['resource']} is paused until {p['paused_until']:%H:%M} ({p['reason']})."})
    du = shutil.disk_usage(ROOT)
    if du.free < 40e9:
        items.append({"level": "warn", "text": f"Only {du.free / 1e9:.0f} GB disk free (keep ≥ 40 GB)."})
    return items


# ── pages ─────────────────────────────────────────────────────────────────────────────────────────────────
@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/overview")
def overview():
    counts = {r["status"]: r["n"] for r in query("SELECT status, count(*) n FROM tasks GROUP BY status")}
    running = query("SELECT id, type, started_at, progress FROM tasks WHERE status='running' ORDER BY started_at")
    return {"now": datetime.now(timezone.utc), "heartbeat": heartbeat(), "counts": counts, "running": running,
            "attention": attention()}


@app.get("/api/review")
def review():
    reports = sorted((ROOT / "reports" / "daily").glob("*.md")) if (ROOT / "reports" / "daily").exists() else []
    latest = reports[-1] if reports else None
    done_today = query("""SELECT type, count(*) n, max(finished_at) last, (array_agg(result->>'summary' ORDER BY finished_at DESC))[1] summary
                          FROM tasks WHERE status='done' AND finished_at > now() - interval '24 hours'
                          GROUP BY type ORDER BY max(finished_at) DESC""")
    return {"attention": attention(),
            "briefing": {"date": latest.stem, "markdown": latest.read_text()} if latest else None,
            "approvals": [],  # Phase 2.6
            "last24h": done_today}


@app.get("/api/live")
def live():
    now = datetime.now(timezone.utc)
    running = query("""SELECT id, type, resource, attempts, max_attempts, started_at, locked_by, progress
                       FROM tasks WHERE status='running' ORDER BY started_at""")
    waiting = query("""SELECT id, type, status, priority, resource, attempts, max_attempts, next_try_at, expires_at, last_error
                       FROM tasks WHERE status IN ('pending','deferred')
                       ORDER BY (last_error IS NULL), next_try_at, priority DESC LIMIT 200""")
    now_et = now.astimezone(ET).replace(tzinfo=None)
    scheds = []
    for s in query("SELECT * FROM schedules ORDER BY name"):
        nxt = cron.next_due(s["cron"], now_et) if s["enabled"] else None
        last = query("""SELECT status, finished_at, result->>'summary' summary, last_error FROM tasks
                        WHERE dedupe_key LIKE %s ORDER BY id DESC LIMIT 1""", (f"sched:{s['name']}:%",))
        scheds.append({"name": s["name"], "task_type": s["task_type"], "cron": s["cron"], "enabled": s["enabled"],
                       "next_run": nxt.replace(tzinfo=ET) if nxt else None, "last_fired_at": s["last_fired_at"],
                       "last": last[0] if last else None})
    scheds.sort(key=lambda s: s["next_run"] or datetime.max.replace(tzinfo=ET))
    pauses = query("SELECT resource, paused_until, reason FROM resource_pauses WHERE paused_until > now()")
    totals = {r["type"]: r["n"] for r in query(
        "SELECT type, count(*) n FROM tasks WHERE status IN ('pending','deferred') GROUP BY type")}
    return {"now": now, "heartbeat": heartbeat(), "running": running, "waiting": waiting, "waiting_totals": totals,
            "schedules": scheds,
            "pauses": pauses, "resources": ["alpaca", "sec", "claude:haiku", "claude:sonnet", "claude:opus"]}


@app.get("/api/today")
def today(day: str | None = None):
    d = date.fromisoformat(day) if day else datetime.now().date()
    events = query("""SELECT ts, level, kind, message FROM events
                      WHERE ts >= %s::date AND ts < %s::date + 1 ORDER BY ts DESC LIMIT 500""", (d, d))
    tasks = query("""SELECT type, count(*) n, count(*) FILTER (WHERE status='failed') failed,
                            min(finished_at) first, max(finished_at) last,
                            (array_agg(result->>'summary' ORDER BY finished_at DESC) FILTER (WHERE result->>'summary' IS NOT NULL))[1] summary,
                            (array_agg(id ORDER BY finished_at DESC))[1] last_id
                     FROM tasks WHERE finished_at >= %s::date AND finished_at < %s::date + 1
                       AND status IN ('done','failed') AND type <> 'news.poll'
                     GROUP BY type ORDER BY max(finished_at) DESC""", (d, d))
    polls = query("""SELECT count(*) n, sum(coalesce((result->>'items')::int, 0)) items FROM tasks
                     WHERE type='news.poll' AND status='done' AND finished_at >= %s::date AND finished_at < %s::date + 1""", (d, d))[0]
    return {"date": d, "events": events, "tasks": tasks, "news_polls": polls}


@app.get("/api/health")
def health():
    failed = query("""SELECT id, type, attempts, finished_at, last_error FROM tasks
                      WHERE status='failed' AND finished_at > now() - interval '14 days' ORDER BY finished_at DESC LIMIT 50""")
    deferred = query("""SELECT id, type, resource, attempts, max_attempts, next_try_at, last_error FROM tasks
                        WHERE status='deferred' OR (status='pending' AND attempts > 0) ORDER BY next_try_at LIMIT 50""")
    errors = query("SELECT id, ts, task_id, task_type, error_type, message FROM errors ORDER BY id DESC LIMIT 30")
    last_ok = query("""SELECT DISTINCT ON (type) type, finished_at, result->>'summary' summary FROM tasks
                       WHERE status='done' ORDER BY type, finished_at DESC""")
    du = shutil.disk_usage(ROOT)
    db = query("SELECT pg_database_size(current_database()) b")[0]["b"]
    return {"heartbeat": heartbeat(), "freshness": freshness(), "failed": failed, "deferred": deferred, "errors": errors,
            "last_ok": last_ok, "disk": {"free_gb": round(du.free / 1e9, 1), "total_gb": round(du.total / 1e9, 1)},
            "db_gb": round(db / 1e9, 2)}


@app.get("/api/data")
def data():
    def load():
        est = {r["relname"]: int(r["n"]) for r in query(
            "SELECT relname, reltuples::bigint n FROM pg_class WHERE relname IN "
            "('daily_prices','news','filings','financials','insider_trades','liquidity','stocks')")}
        u = query("""SELECT count(*) FILTER (WHERE is_universe AND asset_type='common') stocks,
                            count(*) FILTER (WHERE is_universe AND asset_type='etf') etfs,
                            count(*) FILTER (WHERE is_universe AND sector IS NOT NULL) with_sector,
                            count(*) FILTER (WHERE asset_type='common' AND delisted_seen IS NOT NULL) delisted
                     FROM stocks""")[0]
        tiers = query("SELECT tier, count(*) n FROM liquidity WHERE date=(SELECT max(date) FROM liquidity) GROUP BY tier ORDER BY tier")
        sectors = query("""SELECT coalesce(sector,'(not yet known)') sector, count(*) n FROM stocks
                           WHERE is_universe AND asset_type='common' GROUP BY 1 ORDER BY n DESC""")
        span = query("""SELECT (SELECT min(date) FROM daily_prices WHERE symbol='SPY') p0, (SELECT min(created_at) FROM news) n0,
                               (SELECT min(filed_at) FROM insider_trades) i0""")[0]
        return {"rows": est, "universe": u, "tiers": tiers, "sectors": sectors, "since": span,
                "db_gb": round(query("SELECT pg_database_size(current_database()) b")[0]["b"] / 1e9, 2)}
    return cached("data", 120, load)


@app.get("/api/portfolio")
def portfolio():
    from core.ingest import alpaca

    def load():
        acct, err = _alpaca_safe(lambda: alpaca.trading("/v2/account"))
        if err:
            return {"error": err}
        positions, _ = _alpaca_safe(lambda: alpaca.trading("/v2/positions"), [])
        orders, _ = _alpaca_safe(lambda: alpaca.trading("/v2/orders", {"status": "open", "limit": 100}), [])
        hist, _ = _alpaca_safe(lambda: alpaca.trading("/v2/account/portfolio/history", {"period": "3M", "timeframe": "1D"}), None)
        keep = ("equity", "last_equity", "cash", "buying_power", "long_market_value", "status", "currency", "account_number")
        a = {k: acct.get(k) for k in keep}
        a["account_number"] = ("••••" + str(a["account_number"])[-4:]) if a.get("account_number") else None
        curve = []
        if hist and hist.get("timestamp"):
            curve = [{"date": datetime.fromtimestamp(t, timezone.utc).date().isoformat(), "equity": e}
                     for t, e in zip(hist["timestamp"], hist["equity"]) if e]
        spy = []
        if curve:
            spy = query("SELECT date, close * adj_factor AS close FROM daily_prices WHERE symbol='SPY' AND date >= %s ORDER BY date",
                        (curve[0]["date"],))
        return {"account": a, "positions": positions, "orders": orders, "curve": curve, "spy": spy, "paper": True}
    return cached("portfolio", 30, load)


# ── actions (only what the queue already allows; never orders) ──────────────────────────────────────────
@app.post("/api/tasks/{task_id}/retry")
def retry(task_id: int):
    if not query("SELECT 1 FROM tasks WHERE id=%s", (task_id,)):
        raise HTTPException(404, "no such task")
    queue.retry_now(task_id)
    return {"ok": True, "message": f"task #{task_id} re-queued"}


@app.post("/api/resources/{resource}/pause")
def pause(resource: str, minutes: float = Body(60, embed=True)):
    if not 1 <= minutes <= 7 * 24 * 60:
        raise HTTPException(400, "minutes must be between 1 and 10080")
    queue.pause(resource, minutes, reason="paused from dashboard")
    return {"ok": True, "message": f"{resource} paused for {minutes:g} min"}


@app.post("/api/resources/{resource}/resume")
def resume(resource: str):
    queue.resume(resource)
    return {"ok": True, "message": f"{resource} resumed"}


@app.post("/api/schedules/{name}/run")
def run_schedule(name: str):
    s = query("SELECT * FROM schedules WHERE name=%s", (name,))
    if not s:
        raise HTTPException(404, "no such schedule")
    s = s[0]
    tid = queue.enqueue(s["task_type"], s["payload"], priority=max(s["priority"], 90), resource=s["resource"],
                        dedupe_key=f"manual:{name}")
    return {"ok": True, "message": f"queued #{tid}" if tid else "already queued"}


def serve() -> None:
    import uvicorn
    cfg = settings().get("dashboard", {})
    uvicorn.run(app, host=cfg.get("host", "127.0.0.1"), port=int(cfg.get("port", 8090)), log_level="warning",
                access_log=False)
