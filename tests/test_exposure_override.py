from core.planner import plan


def test_exposure_override(monkeypatch):
    monkeypatch.setattr(plan, "settings", lambda: {"trading": {"exposure_override": 1.0}})
    assert plan._exposure_limit(0.5, "dry_run") == 1.0
    assert plan._exposure_limit(0.5, "paper") == 1.0
    assert plan._exposure_limit(0.5, "live") == 0.5          # real money follows the dial
    monkeypatch.setattr(plan, "settings", lambda: {"trading": {"exposure_override": None}})
    assert plan._exposure_limit(0.25, "dry_run") == 0.25


def test_no_replan_after_session_start(monkeypatch):
    from datetime import date, datetime
    monkeypatch.setattr(plan, "limits", lambda: {})
    monkeypatch.setattr(plan, "mode", lambda: "dry_run")
    monkeypatch.setattr(plan, "next_session", lambda d: date(2026, 11, 11))

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 11, 10, 0, tzinfo=tz)
    monkeypatch.setattr(plan, "datetime", Clock)
    r = plan.plan_day(date(2026, 11, 10))
    assert r["skipped"] and "has started" in r["summary"]
