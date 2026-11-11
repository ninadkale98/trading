from types import SimpleNamespace

import numpy as np
import pandas as pd

from core.features import fundamentals as fu


def test_eps_surprise_px(monkeypatch):
    dates = pd.bdate_range("2026-01-05", periods=10)
    m = SimpleNamespace(symbols=["AAA"], dates=dates)
    rows = [  # first report: estimate near zero → +300% of estimate but only 0.5% of a $51 price
        {"symbol": "AAA", "reported_date": dates[1].date(), "surprise_pct": 300.0, "sue": 0.255 / 51},
        # second report has no price before it → blank, not last quarter's value carried forward
        {"symbol": "AAA", "reported_date": dates[5].date(), "surprise_pct": 10.0, "sue": None},
    ]
    monkeypatch.setattr(fu, "query", lambda *a, **k: rows)
    out = {k: np.full((len(dates), 1), np.nan) for k in ("eps_surprise", "eps_surprise_px")}
    fu._surprise(m, out)
    px, pct = out["eps_surprise_px"][:, 0], out["eps_surprise"][:, 0]
    assert np.isnan(px[1]) and np.isnan(pct[1])            # report day itself: not known yet (point in time)
    assert abs(px[2] - 0.005) < 1e-9 and pct[2] == 3.0       # known from the next day
    assert abs(px[5] - 0.005) < 1e-9                          # carried until the next report
    assert np.isnan(px[6]) and abs(pct[6] - 0.10) < 1e-9     # next report: pct updates, px blank
