"""Dashboard endpoints load against an empty throwaway database, and actions only touch the queue."""
import subprocess

import pytest

TEST_DB = "market_test_dash"


@pytest.fixture(scope="module", autouse=True)
def test_db():
    subprocess.run(["/opt/homebrew/opt/postgresql@17/bin/dropdb", "--if-exists", TEST_DB], check=True)
    subprocess.run(["/opt/homebrew/opt/postgresql@17/bin/createdb", TEST_DB], check=True)
    from core import config, db
    config.settings()["database"]["dsn"] = f"dbname={TEST_DB}"
    db.close()
    db.migrate()
    from core.schedules import SCHEDULES
    from core.tasks import scheduler
    scheduler.sync(SCHEDULES)
    yield
    db.close()
    subprocess.run(["/opt/homebrew/opt/postgresql@17/bin/dropdb", "--if-exists", TEST_DB], check=True)


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    from dashboard import app as dash
    dash.trading_days = lambda start, end: [d for d in (start + __import__("datetime").timedelta(n)
                                             for n in range((end - start).days + 1)) if d.weekday() < 5]  # no network
    return TestClient(dash.app)


@pytest.mark.parametrize("path", ["/", "/api/overview", "/api/review", "/api/live", "/api/today",
                                  "/api/today?day=2026-11-05", "/api/health", "/api/data",
                                  "/static/app.js", "/static/app.css"])
def test_pages_load_on_empty_database(client, path):
    r = client.get(path)
    assert r.status_code == 200, r.text[:300]
    assert r.headers["cache-control"] == "no-cache"


def test_empty_system_reports_problems_plainly(client):
    o = client.get("/api/overview").json()
    texts = " ".join(a["text"] for a in o["attention"])
    assert "isn't running" in texts            # no heartbeat in an empty database
    assert "Daily prices is behind" in texts


def test_actions_change_only_the_queue(client):
    from core.db import query
    r = client.post("/api/schedules/news_poll/run")
    assert r.status_code == 200 and r.json()["ok"]
    assert client.post("/api/schedules/news_poll/run").json()["message"] == "already queued"
    assert client.post("/api/schedules/nope/run").status_code == 404
    assert client.post("/api/resources/sec/pause", json={"minutes": 5}).json()["ok"]
    assert query("SELECT count(*) n FROM resource_pauses WHERE resource='sec' AND paused_until > now()")[0]["n"] == 1
    assert client.post("/api/resources/sec/resume").json()["ok"]
    assert client.post("/api/resources/sec/pause", json={"minutes": 0}).status_code == 400
    tid = query("SELECT id FROM tasks ORDER BY id DESC LIMIT 1")[0]["id"]
    assert client.post(f"/api/tasks/{tid}/retry").status_code == 200
    assert client.post("/api/tasks/999999/retry").status_code == 404
