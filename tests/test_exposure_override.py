from core.planner import plan


def test_exposure_override(monkeypatch):
    monkeypatch.setattr(plan, "settings", lambda: {"trading": {"exposure_override": 1.0}})
    assert plan._exposure_limit(0.5, "dry_run") == 1.0
    assert plan._exposure_limit(0.5, "paper") == 1.0
    assert plan._exposure_limit(0.5, "live") == 0.5          # real money follows the dial
    monkeypatch.setattr(plan, "settings", lambda: {"trading": {"exposure_override": None}})
    assert plan._exposure_limit(0.25, "dry_run") == 0.25
