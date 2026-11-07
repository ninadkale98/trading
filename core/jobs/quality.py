"""Data quality (build plan 1.8) + backups (1.11)."""
from __future__ import annotations

import gzip
import shutil
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path

from core.config import ROOT
from core.db import query
from core.tasks import queue
from core.tasks.registry import TaskContext, task

PG_BIN = Path("/opt/homebrew/opt/postgresql@17/bin")


@task("quality.gaps", priority=55, description="Find missing price days/symbols and queue backfills")
def gaps(ctx: TaskContext) -> dict:
    """A universe stock that traded recently but is missing bars on recent market days gets re-loaded."""
    market_days = [r["date"] for r in query(
        "SELECT date FROM daily_prices WHERE symbol='SPY' ORDER BY date DESC LIMIT 10")]
    if not market_days:
        return {"summary": None}
    missing = query(
        """SELECT s.symbol, 10 - count(p.date) AS missing_days
           FROM (SELECT DISTINCT symbol FROM stocks WHERE is_universe) s
           LEFT JOIN daily_prices p ON p.symbol = s.symbol AND p.date = ANY(%s)
           GROUP BY s.symbol HAVING count(p.date) BETWEEN 1 AND 9""", (market_days,))
    never = query("""SELECT DISTINCT s.symbol FROM stocks s WHERE s.is_universe
                     AND NOT EXISTS (SELECT 1 FROM daily_prices p WHERE p.symbol = s.symbol)""")
    syms = sorted({r["symbol"] for r in missing} | {r["symbol"] for r in never})
    if syms:
        queue.enqueue("prices.backfill", {"symbols": syms}, priority=50, resource="alpaca",
                      dedupe_key=f"gapfill:{date.today()}")
    # sanity flags (reported, not auto-fixed)
    bad = query("""SELECT count(*) n FROM daily_prices WHERE date >= %s AND (close <= 0 OR high < low OR volume < 0)""",
                (market_days[-1],))[0]["n"]
    return {"summary": f"gap check: {len(missing)} stocks with missing recent days, {len(never)} never loaded"
                       + (f" → backfill queued" if syms else "") + (f"; {bad} bad bars flagged" if bad else ""),
            "partial": len(missing), "never_loaded": len(never), "bad_bars": bad}


@task("quality.survivorship", priority=30, description="How complete is delisted-stock history (backtest honesty)")
def survivorship(ctx: TaskContext) -> dict:
    r = query("""
        WITH d AS (SELECT DISTINCT symbol FROM stocks WHERE status='inactive' AND asset_type='common'
                   AND symbol NOT IN (SELECT symbol FROM stocks WHERE status='active'))
        SELECT (SELECT count(*) FROM d) AS delisted_known,
               (SELECT count(DISTINCT p.symbol) FROM daily_prices p JOIN d USING (symbol)) AS with_prices,
               (SELECT min(last) FROM (SELECT max(date) last FROM daily_prices p JOIN d USING (symbol) GROUP BY symbol) x) AS earliest_end,
               (SELECT count(*) FROM (SELECT max(date) last FROM daily_prices p JOIN d USING (symbol) GROUP BY symbol) x
                 WHERE last < '2020-01-01') AS ended_before_2020""")[0]
    by_year = query("""
        WITH d AS (SELECT DISTINCT symbol FROM stocks WHERE status='inactive' AND asset_type='common'
                   AND symbol NOT IN (SELECT symbol FROM stocks WHERE status='active'))
        SELECT extract(year FROM last)::int AS year, count(*) n
        FROM (SELECT symbol, max(date) last FROM daily_prices JOIN d USING (symbol) GROUP BY symbol) x
        GROUP BY 1 ORDER BY 1""")
    years = {str(x["year"]): x["n"] for x in by_year}
    return {"summary": f"survivorship: {r['with_prices']} of {r['delisted_known']} known delisted stocks have price history; "
                       f"delistings by year: {years}",
            **{k: (str(v) if isinstance(v, date) else v) for k, v in r.items()}, "by_year": years}


@task("system.backup", priority=20, description="Nightly compressed database backup (keeps 7 daily + 4 weekly)")
def backup(ctx: TaskContext) -> dict:
    out = ROOT / "backups"
    out.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d")
    path = out / f"market-{stamp}.dump"
    subprocess.run([str(PG_BIN / "pg_dump"), "-d", "market", "-Fc", "-Z", "6", "-f", str(path)], check=True)
    if datetime.now().weekday() == 6:      # Sunday copy is kept as a weekly
        shutil.copy2(path, out / f"weekly-{stamp}.dump")
    daily = sorted(out.glob("market-*.dump"))
    weekly = sorted(out.glob("weekly-*.dump"))
    for old in daily[:-7] + weekly[:-4]:
        old.unlink()
    size = path.stat().st_size / 1e9
    return {"summary": f"backup saved ({size:.2f} GB); keeping {min(len(daily), 7)} daily + {min(len(weekly), 4)} weekly",
            "gb": round(size, 2)}
