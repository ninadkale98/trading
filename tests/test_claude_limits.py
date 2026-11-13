from datetime import datetime, timezone

from core.ai import claude


def test_five_hour_limit_message_is_a_limit():
    msg = "You've hit your 5-hour limit · resets 12:40am (America/Los_Angeles)"
    assert claude._LIMIT.search(msg)
    assert claude._LIMIT.search("Claude usage limit reached")
    assert not claude._LIMIT.search("answer didn't match the schema")


def test_reset_time_uses_the_named_time_zone():
    until = claude._limit_until("You've hit your 5-hour limit · resets 12:40am (America/Los_Angeles)")
    local = until.astimezone(claude.ZoneInfo("America/Los_Angeles"))
    assert (local.hour, local.minute) == (0, 42)                 # reset + 2 minutes, in Pacific time
    assert until > datetime.now(timezone.utc)
    et = claude._limit_until("usage limit · resets 3pm").astimezone(claude.ET)
    assert (et.hour, et.minute) == (15, 2)                        # no zone given → Eastern


def test_backfills_skip_the_hours_before_key_ai_jobs():
    from core.schedules import BACKFILL_HOURS, SCHEDULES
    hours = set()
    for part in BACKFILL_HOURS.split(","):
        a, _, b = part.partition("-")
        hours |= set(range(int(a), int(b or a) + 1))
    assert not hours & set(range(4, 10))        # pre-open triage + 9:20 news check
    assert not hours & set(range(16, 22))       # after-close reads + 9 pm Opus analysis
    crons = {s["name"]: s["cron"] for s in SCHEDULES}
    assert BACKFILL_HOURS in crons["news_triage_backlog"] and BACKFILL_HOURS in crons["earnings_read_history"]
