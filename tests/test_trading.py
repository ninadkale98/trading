"""Dry-run execution and approvals against a throwaway database."""
import subprocess
from datetime import date, datetime, timedelta, timezone

import pytest

TEST_DB = "market_test_trading"
D0, D1, D2 = date(2026, 11, 9), date(2026, 11, 10), date(2026, 11, 11)


@pytest.fixture(scope="module", autouse=True)
def test_db():
    subprocess.run(["/opt/homebrew/opt/postgresql@17/bin/dropdb", "--if-exists", TEST_DB], check=True)
    subprocess.run(["/opt/homebrew/opt/postgresql@17/bin/createdb", TEST_DB], check=True)
    from core import config, db
    config.settings()["database"]["dsn"] = f"dbname={TEST_DB}"
    config.settings().setdefault("trading", {})["mode"] = "dry_run"
    db.close()
    db.migrate()
    yield
    db.close()
    subprocess.run(["/opt/homebrew/opt/postgresql@17/bin/dropdb", "--if-exists", TEST_DB], check=True)


def _bar(sym, d, o, h, low, c):
    from core.db import execute
    execute("INSERT INTO daily_prices (symbol, date, open, high, low, close, volume) VALUES (%s,%s,%s,%s,%s,%s,1000000)",
            (sym, d, o, h, low, c))


def _plan(sym, limit, stop, target=None, trail=None, side="buy", day=D0, status="planned"):
    from core.db import query
    return query("""INSERT INTO trade_plans (signal_date, trade_date, mode, strategy, symbol, side, shares, limit_price, stop,
                       target, trail_pct, max_hold, risk_dollars, position_value, status)
                    VALUES (%s,%s,'dry_run','test',%s,%s,100,%s,%s,%s,%s,20,100,1000,%s) RETURNING id""",
                 (day - timedelta(days=1), day, sym, side, limit, stop, target, trail, status))[0]["id"]


def test_dry_run_fills_stops_and_gaps():
    from core.db import query
    from core.execution.run import simulate_session
    for s in ("SPY",):
        for d in (D0, D1, D2):
            _bar(s, d, 500, 505, 495, 500)
    _bar("AAA", D0, 10.0, 10.5, 9.8, 10.2)      # opens at 10 ≤ limit 10.1 → filled, stop 9 not hit
    _bar("BBB", D0, 21.0, 21.5, 20.5, 21.0)     # opens above limit 20.2 → expired
    _bar("CCC", D0, 30.0, 30.2, 27.0, 28.0)     # filled at 30, low 27 ≤ stop 28 → stopped same day at 28
    from core.db import execute
    for sym in ("AAA", "BBB", "CCC"):
        execute("INSERT INTO liquidity (symbol, date, price, adv20_dollar, tier) VALUES (%s, %s, 10, 1e8, 'liquid')", (sym, D0))
    _plan("AAA", 10.1, 9.0)
    _plan("BBB", 20.2, 18.0)
    _plan("CCC", 30.3, 28.0)
    r = simulate_session(D0)
    assert (r["filled"], r["expired"], r["exits"]) == (2, 1, 1)
    book = {b["symbol"]: b for b in query("SELECT * FROM positions_book")}
    assert book["AAA"]["status"] == "open" and abs(book["AAA"]["entry_price"] - 10.005) < 1e-3   # open + 5 bps cost
    assert book["CCC"]["exit_reason"] == "stop" and book["CCC"]["pnl"] < 0
    _bar("AAA", D1, 8.5, 8.8, 8.4, 8.6)          # gaps below the 9.00 stop → filled at the open, not at the stop
    simulate_session(D1)
    a = query("SELECT * FROM positions_book WHERE symbol='AAA'")[0]
    assert a["exit_reason"].startswith("stop (gapped") and abs(a["exit_price"] - 8.5 * (1 - 5 / 1e4)) < 1e-3


def test_approvals_expire_to_no_trade_and_half_size():
    from core.db import query
    from core.execution.run import expire_approvals
    from core.planner.approvals import decide
    p1 = _plan("DDD", 5.0, 4.5, day=D2, status="waiting_approval")
    p2 = _plan("EEE", 5.0, 4.5, day=D2, status="waiting_approval")
    past, future = datetime.now(timezone.utc) - timedelta(minutes=1), datetime.now(timezone.utc) + timedelta(hours=1)
    a1 = query("INSERT INTO approvals (kind, plan_id, title, deadline) VALUES ('emerging_stock', %s, 'x', %s) RETURNING id", (p1, past))[0]["id"]
    a2 = query("INSERT INTO approvals (kind, plan_id, title, deadline) VALUES ('emerging_stock', %s, 'y', %s) RETURNING id", (p2, future))[0]["id"]
    assert expire_approvals() == 1
    assert query("SELECT status FROM trade_plans WHERE id=%s", (p1,))[0]["status"] == "expired"
    assert "half" not in decide(a2, True, 0.5) and query("SELECT shares, status FROM trade_plans WHERE id=%s", (p2,))[0] == {"shares": 50, "status": "planned"}
    assert "already" in decide(a1, True)
    with pytest.raises(ValueError):
        decide(a2, True, 1.5)
