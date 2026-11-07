"""Recurring jobs (times are America/New_York). Synced into the `schedules` table when the daemon starts.
`expires_minutes` = catch-up window: if the daemon was down at the due time, the job still runs on startup
within this window; otherwise that run is skipped. Jobs are added here as each phase is built."""

WEEKDAYS = "1-5"

SCHEDULES: list[dict] = [
    # ── Phase 1: data ──────────────────────────────────────────────────────────────
    {"name": "universe_refresh", "task_type": "universe.refresh", "cron": f"0 7 * * {WEEKDAYS}",
     "priority": 80, "resource": "alpaca", "expires_minutes": 600},
    {"name": "prices_daily", "task_type": "prices.daily", "cron": f"40 16 * * {WEEKDAYS}",
     "priority": 70, "resource": "alpaca", "expires_minutes": 720},
    {"name": "prices_daily_late", "task_type": "prices.daily", "cron": f"30 20 * * {WEEKDAYS}",   # catches late corrections
     "priority": 65, "resource": "alpaca", "expires_minutes": 600},
    {"name": "news_poll", "task_type": "news.poll", "cron": "*/15 * * * *",
     "priority": 75, "resource": "alpaca", "expires_minutes": 14},
    {"name": "sec_daily", "task_type": "sec.daily", "cron": f"15 22 * * {WEEKDAYS}",
     "priority": 60, "resource": "sec", "expires_minutes": 600},
    {"name": "insider_recent", "task_type": "insider.recent", "cron": f"0 23 * * {WEEKDAYS}",
     "priority": 35, "resource": "sec", "expires_minutes": 600},
    {"name": "insider_bulk_monthly", "task_type": "insider.backfill", "cron": "0 3 5 * *",       # picks up newly published quarters
     "payload": {"from": "2016q1"}, "priority": 25, "resource": "sec", "expires_minutes": 1440},
    {"name": "gap_check", "task_type": "quality.gaps", "cron": f"30 21 * * {WEEKDAYS}",
     "priority": 55, "expires_minutes": 600},
    {"name": "survivorship_weekly", "task_type": "quality.survivorship", "cron": "0 9 * * 6",
     "priority": 30, "expires_minutes": 1440},
    {"name": "backup_nightly", "task_type": "system.backup", "cron": "0 2 * * *",
     "priority": 20, "expires_minutes": 600},
]
