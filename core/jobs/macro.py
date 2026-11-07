"""Macro data from FRED (Phase 2.1b): rates, credit, inflation, jobs, growth, housing, dollar/oil, financial conditions.
Release-based series keep the value as FIRST published and the day it was published (point-in-time), plus the
latest revised value. Market series (daily yields, spreads) aren't revised, so they're stored as-is."""
from __future__ import annotations

from datetime import date, timedelta

from core.db import conn, execute
from core.ingest import fred
from core.tasks.registry import TaskContext, task

START = "2015-01-01"

# series id → (group, revised by later releases?)
SERIES: dict[str, tuple[str, bool]] = {
    "DFF": ("rates", False), "DGS2": ("rates", False), "DGS10": ("rates", False), "T10Y2Y": ("rates", False),
    "T10Y3M": ("rates", False), "DFII10": ("rates", False),
    "BAMLH0A0HYM2": ("credit", False), "BAMLC0A0CM": ("credit", False),
    "CPIAUCSL": ("inflation", True), "CPILFESL": ("inflation", True), "PCEPILFE": ("inflation", True), "T10YIE": ("inflation", False),
    "PAYEMS": ("jobs", True), "UNRATE": ("jobs", True), "ICSA": ("jobs", True),
    "INDPRO": ("growth", True), "RSAFS": ("growth", True), "UMCSENT": ("growth", True), "GDPC1": ("growth", True),
    "HOUST": ("housing", True), "DTWEXBGS": ("dollar_oil", False), "DCOILWTICO": ("dollar_oil", False),
    "NFCI": ("conditions", True),
}


def _v(x: str):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None          # FRED uses "." for missing


def load_series(sid: str, grp: str, revised: bool) -> int:
    info = fred.series_info(sid)
    execute("""INSERT INTO macro_series (series_id, title, frequency, units, grp, last_loaded) VALUES (%s,%s,%s,%s,%s, now())
               ON CONFLICT (series_id) DO UPDATE SET title=EXCLUDED.title, frequency=EXCLUDED.frequency,
                 units=EXCLUDED.units, grp=EXCLUDED.grp, last_loaded=now()""",
            (sid, info.get("title"), info.get("frequency_short"), info.get("units_short"), grp))
    latest = {o["date"]: _v(o["value"]) for o in fred.observations(sid, START)}
    first: dict[str, tuple] = {}
    if revised:
        for o in fred.observations(sid, START, first_release=True):
            if o["date"] not in first or o["realtime_start"] < first[o["date"]][1]:
                first[o["date"]] = (_v(o["value"]), o["realtime_start"])
    rows = []
    for d, val in latest.items():
        if revised:
            vf, known = first.get(d, (None, None))
        else:   # market data: known the next day, never revised
            vf, known = val, (date.fromisoformat(d) + timedelta(days=1)).isoformat()
        rows.append((sid, d, vf, known, val))
    with conn() as c, c.cursor() as cur:
        cur.executemany("""INSERT INTO macro_obs (series_id, date, value_first, first_known, value_latest) VALUES (%s,%s,%s,%s,%s)
                           ON CONFLICT (series_id, date) DO UPDATE SET value_first=COALESCE(macro_obs.value_first, EXCLUDED.value_first),
                             first_known=COALESCE(macro_obs.first_known, EXCLUDED.first_known), value_latest=EXCLUDED.value_latest""", rows)
    return len(rows)


@task("macro.update", resource="fred", priority=50, description="Economic data from FRED (rates, inflation, jobs, growth…)")
def update(ctx: TaskContext) -> dict:
    done = set(ctx.progress.get("done", []))
    n = ctx.progress.get("rows", 0)
    for sid, (grp, revised) in SERIES.items():
        if sid in done:
            continue
        n += load_series(sid, grp, revised)
        done.add(sid)
        ctx.checkpoint(done=sorted(done), rows=n)
    return {"summary": f"macro: {len(SERIES)} FRED series updated ({n:,} observations)", "series": len(SERIES), "rows": n}
