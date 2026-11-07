"""The background service: worker threads + scheduler + heartbeat + housekeeping.
Run by launchd (starts at login, restarted if it exits). One failing task never stops the others."""
from __future__ import annotations

import signal
import socket
import threading
import time
from datetime import timedelta

from core.config import settings
from core.db import execute, migrate
from core.log import error, event, file_logger
from core.tasks import queue, runner, scheduler
from core.tasks.registry import load_all

STOP = threading.Event()
HOST = socket.gethostname().split(".")[0]


def _worker(n: int) -> None:
    name = f"{HOST}:w{n}"
    poll = settings()["workers"]["poll_seconds"]
    while not STOP.is_set():
        try:
            task = queue.claim(name)
            if task is None:
                STOP.wait(poll)
                continue
            runner.run(task)
        except Exception as e:  # database hiccup etc.: log, back off, keep going
            error(e, task_type="worker")
            STOP.wait(10)


def _scheduler_loop() -> None:
    from core.schedules import SCHEDULES
    scheduler.sync(SCHEDULES)
    while not STOP.is_set():
        try:
            scheduler.tick()
            queue.expire_stale()
            queue.recover_running(older_than=timedelta(hours=6))
        except Exception as e:
            error(e, task_type="scheduler")
        STOP.wait(20)


def _heartbeat_loop() -> None:
    every = settings()["workers"]["heartbeat_seconds"]
    while not STOP.is_set():
        try:
            execute(
                "INSERT INTO heartbeats (component, ts, info) VALUES ('daemon', now(), %s) "
                "ON CONFLICT (component) DO UPDATE SET ts = now(), info = EXCLUDED.info",
                ('{"host": "%s", "threads": %d}' % (HOST, settings()["workers"]["threads"]),),
            )
        except Exception as e:
            error(e, task_type="heartbeat")
        STOP.wait(every)


def main() -> None:
    log = file_logger()
    migrate()
    load_all()
    recovered = queue.recover_running(worker_prefix=f"{HOST}:")
    event("daemon", f"started on {HOST}" + (f"; re-queued {recovered} interrupted task(s)" if recovered else ""))

    def _stop(signum, _frame):
        log.info(f"signal {signum}: stopping")
        STOP.set()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    threads = [threading.Thread(target=_worker, args=(i,), name=f"worker-{i}", daemon=True)
               for i in range(settings()["workers"]["threads"])]
    threads += [threading.Thread(target=_scheduler_loop, name="scheduler", daemon=True),
                threading.Thread(target=_heartbeat_loop, name="heartbeat", daemon=True)]
    for t in threads:
        t.start()
    while not STOP.is_set():
        time.sleep(1)
    # Give running tasks a moment; anything still running is re-queued on next start.
    for t in threads:
        t.join(timeout=30)
    event("daemon", "stopped")
