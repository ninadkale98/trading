"""The queue must survive every failure mode (architecture §14). Runs against a throwaway database."""
import os
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

TEST_DB = "market_test"


@pytest.fixture(scope="module", autouse=True)
def test_db():
    subprocess.run(["/opt/homebrew/opt/postgresql@17/bin/dropdb", "--if-exists", TEST_DB], check=True)
    subprocess.run(["/opt/homebrew/opt/postgresql@17/bin/createdb", TEST_DB], check=True)
    from core import config, db
    config.settings()["database"]["dsn"] = f"dbname={TEST_DB}"
    db.close()
    db.migrate()
    from core.tasks.registry import load_all
    load_all()
    yield
    db.close()
    subprocess.run(["/opt/homebrew/opt/postgresql@17/bin/dropdb", "--if-exists", TEST_DB], check=True)


def _drain(seconds=8):
    """Run the claim/run loop until the queue is idle (or time runs out)."""
    from core.tasks import queue, runner
    end = time.time() + seconds
    while time.time() < end:
        t = queue.claim("test:w0")
        if t is None:
            time.sleep(0.3)
            continue
        runner.run(t)


def _status(tid):
    from core.db import query
    return query("SELECT * FROM tasks WHERE id=%s", (tid,))[0]


def test_ok_and_dedupe():
    from core.tasks import queue
    a = queue.enqueue("system.selftest", {"mode": "ok"}, dedupe_key="once")
    b = queue.enqueue("system.selftest", {"mode": "ok"}, dedupe_key="once")
    assert a and b is None
    _drain(2)
    assert _status(a)["status"] == "done"


def test_crash_is_retried_then_fails_without_stopping_others():
    from core.tasks import queue
    bad = queue.enqueue("system.selftest", {"mode": "crash"}, max_attempts=2)
    good = queue.enqueue("system.selftest", {"mode": "ok"})
    _drain(2)
    assert _status(good)["status"] == "done"          # the crash didn't block other work
    from core.db import execute
    execute("UPDATE tasks SET next_try_at=now() WHERE id=%s", (bad,))  # skip the backoff wait
    _drain(2)
    row = _status(bad)
    assert row["status"] == "failed" and row["attempts"] == 2


def test_flaky_retries_and_succeeds():
    from core.tasks import queue
    tid = queue.enqueue("system.selftest", {"mode": "flaky"})
    _drain(5)
    row = _status(tid)
    assert row["status"] == "done" and row["attempts"] == 2


def test_limit_defers_and_pauses_resource_then_resumes():
    from core.tasks import queue
    tid = queue.enqueue("system.selftest", {"mode": "limited", "pause_seconds": 2}, resource="claude:test")
    other = queue.enqueue("system.selftest", {"mode": "ok"}, resource="claude:test")
    _drain(1)
    row = _status(tid)
    assert row["status"] == "deferred" and row["attempts"] == 0     # limits don't use up attempts
    assert _status(other)["status"] == "pending"                   # whole resource paused
    time.sleep(2.2)
    from core.db import execute
    execute("UPDATE tasks SET payload='{\"mode\":\"ok\"}' WHERE id=%s", (tid,))  # limit "reset"
    _drain(2)
    assert _status(tid)["status"] == "done" and _status(other)["status"] == "done"


def test_permanent_fails_immediately():
    from core.tasks import queue
    tid = queue.enqueue("system.selftest", {"mode": "permanent"})
    _drain(1)
    row = _status(tid)
    assert row["status"] == "failed" and row["attempts"] == 1


def test_checkpoint_resume():
    from core.tasks import queue
    tid = queue.enqueue("system.selftest", {"mode": "resume"})
    _drain(4)
    row = _status(tid)
    assert row["status"] == "done" and "resumed from step 3" in row["result"]["summary"]


def test_expiry_and_crash_recovery():
    from core.db import execute
    from core.tasks import queue
    old = queue.enqueue("system.noop", expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))
    assert queue.expire_stale() >= 1 and _status(old)["status"] == "expired"
    stuck = queue.enqueue("system.noop")
    execute("UPDATE tasks SET status='running', locked_by='ichigo:w9', attempts=1 WHERE id=%s", (stuck,))
    assert queue.recover_running(worker_prefix="ichigo:") >= 1
    row = _status(stuck)
    assert row["status"] == "pending" and row["attempts"] == 0


def test_concurrent_workers_never_double_run():
    from core.tasks import queue, runner
    ids = [queue.enqueue("system.selftest", {"mode": "ok"}) for _ in range(40)]
    claimed = []
    lock = threading.Lock()

    def work(n):
        while True:
            t = queue.claim(f"test:c{n}")
            if t is None:
                return
            with lock:
                claimed.append(t["id"])
            runner.run(t)

    ts = [threading.Thread(target=work, args=(i,)) for i in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    mine = [c for c in claimed if c in ids]
    assert sorted(mine) == sorted(ids) and len(mine) == len(set(mine))


def test_scheduler_catch_up_window():
    from zoneinfo import ZoneInfo
    from core.db import query
    from core.tasks import scheduler
    tz = ZoneInfo("America/New_York")
    scheduler.sync([{"name": "t_daily", "task_type": "system.noop", "cron": "30 16 * * 1-5", "expires_minutes": 120}])
    # daemon "comes back" at 17:10 on a Monday → 16:30 run is still in its window → queued once
    now = datetime(2026, 11, 9, 17, 10, tzinfo=tz)
    assert scheduler.tick(now) == ["t_daily"]
    assert scheduler.tick(now) == []
    # back at 19:00 next day: 16:30 was 150 min ago → outside the window → skipped
    assert scheduler.tick(datetime(2026, 11, 10, 19, 0, tzinfo=tz)) == []
    assert query("SELECT count(*) n FROM tasks WHERE dedupe_key LIKE 'sched:t_daily:%%'")[0]["n"] == 1


def test_alpaca_timestamps_are_utc():
    from datetime import datetime, timezone, timedelta
    from core.ingest.alpaca import _iso
    pst = timezone(timedelta(hours=-8))
    assert _iso(datetime(2026, 11, 6, 17, 6, tzinfo=pst)) == "2026-11-07T01:06:00Z"
    assert _iso(datetime(2026, 11, 7, 1, 6)) == "2026-11-07T01:06:00Z"
