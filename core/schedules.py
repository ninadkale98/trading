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
    # ── Phase 2: earnings, analysts, macro (prices → features → market snapshot are chained, not scheduled) ──
    {"name": "earnings_calendar_av", "task_type": "earnings.calendar_av", "cron": f"15 6 * * {WEEKDAYS}",
     "priority": 66, "resource": "alphavantage", "expires_minutes": 600},
    {"name": "earnings_calendar_finnhub", "task_type": "earnings.calendar_finnhub", "cron": f"20 6 * * {WEEKDAYS}",
     "priority": 66, "resource": "finnhub", "expires_minutes": 600},
    {"name": "earnings_history_av", "task_type": "earnings.history_av", "cron": "30 6 * * *",          # uses the rest of the daily budget
     "priority": 30, "resource": "alphavantage", "expires_minutes": 900},
    {"name": "analyst_ratings_weekly", "task_type": "analyst.ratings", "cron": "0 10 * * 6",
     "priority": 25, "resource": "finnhub", "expires_minutes": 1440},
    {"name": "macro_update", "task_type": "macro.update", "cron": f"5 9,18 * * {WEEKDAYS}",          # after 8:30 am releases; evening catch-up
     "priority": 50, "resource": "fred", "expires_minutes": 360},
    # ── Re-plan step A: news understanding (Haiku) ──
    {"name": "news_triage", "task_type": "news.triage", "cron": "7,37 * * * *", "payload": {"days": 3, "max_items": 2000},
     "priority": 62, "resource": "claude:haiku", "expires_minutes": 25},
    {"name": "news_triage_backlog", "task_type": "news.triage", "cron": "50 * * * *",   # ALL older news (2019+), newest first,
     "payload": {"days": 3000, "max_items": 1000}, "priority": 20, "resource": "claude:haiku", "expires_minutes": 55},  # ~3 weeks
    # ── Earnings release reader (build plan 4.1): live 8-K feed → Haiku reads the press release ──
    {"name": "sec_earnings_poll", "task_type": "sec.earnings_poll", "cron": f"*/20 6-21 * * {WEEKDAYS}",   # chains earnings.read
     "priority": 64, "resource": "sec", "expires_minutes": 18},
    {"name": "earnings_read_catchup", "task_type": "earnings.read", "cron": f"50 22 * * {WEEKDAYS}",   # after sec.daily
     "priority": 63, "resource": "claude:haiku", "expires_minutes": 600},
    {"name": "earnings_read_history", "task_type": "earnings.read_history", "cron": "20 * * * *",   # ~40/hour, random order
     "payload": {"max_items": 40}, "priority": 18, "resource": "claude:haiku", "expires_minutes": 55},
    # ── Re-plan step B: daily market analysis + predictions ──
    {"name": "predictions_score", "task_type": "predictions.score", "cron": f"45 17 * * {WEEKDAYS}",
     "priority": 56, "expires_minutes": 600},
    {"name": "market_analysis", "task_type": "ai.market_analysis", "cron": f"0 21 * * {WEEKDAYS}",
     "priority": 70, "resource": "claude:opus", "expires_minutes": 600},
    # ── Re-plan step E: trading (dry run or paper; evening steps are chained after the market snapshot) ──
    {"name": "trading_open", "task_type": "trading.open", "cron": f"20 9 * * {WEEKDAYS}",
     "priority": 90, "expires_minutes": 30},
    {"name": "trading_sync", "task_type": "trading.sync", "cron": f"*/15 10-15 * * {WEEKDAYS}",
     "priority": 85, "expires_minutes": 14},
    {"name": "trading_sync_close", "task_type": "trading.sync", "cron": f"10 16 * * {WEEKDAYS}",
     "priority": 85, "expires_minutes": 60},
    {"name": "briefing_daily", "task_type": "briefing.daily", "cron": f"30 21 * * {WEEKDAYS}",
     "priority": 60, "expires_minutes": 600},
    {"name": "briefing_morning", "task_type": "briefing.daily", "cron": f"30 6 * * {WEEKDAYS}",   # refresh with overnight changes
     "priority": 60, "expires_minutes": 120},
    {"name": "trade_review_weekly", "task_type": "review.weekly_trades", "cron": "0 10 * * 6",
     "priority": 40, "resource": "claude:opus", "expires_minutes": 1440},
    # ── Phase 4: the self-improving loop ──
    {"name": "lab_cycle_sunday", "task_type": "lab.cycle", "cron": "0 12 * * 0", "payload": {"ideas": 4},
     "priority": 30, "resource": "lab", "expires_minutes": 1440},
    {"name": "lab_cycle_wednesday", "task_type": "lab.cycle", "cron": "0 23 * * 3", "payload": {"ideas": 4},   # after the briefing
     "priority": 30, "resource": "lab", "expires_minutes": 720},
    {"name": "engineer_weekly", "task_type": "engineer.weekly", "cron": "30 12 * * 6",   # after the trade review; waits for review
     "priority": 25, "resource": "claude:opus", "expires_minutes": 1440},
    {"name": "backup_nightly", "task_type": "system.backup", "cron": "0 2 * * *",
     "priority": 20, "expires_minutes": 600},
]
