"""Paper mode keeps the dry-run book running beside it (execution.run.books), with its own simulated account."""
from datetime import date

from core.execution import run
from core.planner import plan


def test_books_by_mode(monkeypatch):
    monkeypatch.setattr(run, "settings", lambda: {"trading": {"mode": "dry_run"}})
    assert run.books() == ["dry_run"]
    monkeypatch.setattr(run, "settings", lambda: {"trading": {"mode": "paper"}})
    assert run.books() == ["paper", "dry_run"]                     # shadow on by default
    monkeypatch.setattr(run, "settings", lambda: {"trading": {"mode": "paper", "shadow_dry_run": False}})
    assert run.books() == ["paper"]


def test_dry_run_account_is_its_own_money(monkeypatch):
    def fake_query(sql, params=None):
        if "status='closed'" in sql:
            return [{"s": -726.0}]
        return [{"symbol": "AAA", "shares": 100, "entry_price": 10.0}, {"symbol": "BBB", "shares": 10, "entry_price": 50.0}]
    monkeypatch.setattr(plan, "query", fake_query)
    monkeypatch.setattr(plan, "settings", lambda: {"trading": {"dry_run_start_equity": 100000}})
    a = plan.dry_run_account(date(2026, 11, 11), {"AAA": 12.0, "BBB": None}.get)   # BBB: no price → entry price
    assert a["equity"] == 100000 - 726 + 200                       # +$2/share on AAA
    assert a["cash"] == a["equity"] - (1200 + 500)
    assert a["peak"] == 100000 and a["positions"] == {}
