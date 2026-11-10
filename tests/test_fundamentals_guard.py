"""Market cap guard: price × SEC share count is blanked for 20-F filers (ADR ratio unknown) and for implausible values
(huge 'market cap' with almost no trading, e.g. an ADR of a 10-K filer)."""
import numpy as np

from core.features import fundamentals as fu
from tests.test_strategy import _market


def test_market_cap_guard(monkeypatch):
    m = _market(T=100, N=4)
    m.dollar_volume[:] = 5e6                                   # $5M a day for everyone
    out = {k: np.full(m.close.shape, np.nan, dtype=np.float32) for k in fu.FEATURES}
    out["market_cap"][:] = 1e9                                  # fine: turnover 0.5%/day
    out["market_cap"][:, 2] = 1e12                              # "$1T" on $5M a day → implausible
    out["pe"][:] = 15
    ciks = {m.symbols[0]: 1, m.symbols[1]: 2, m.symbols[2]: 3, m.symbols[3]: 4}
    monkeypatch.setattr(fu, "foreign_filers", lambda c: {2})    # symbol 1 files a 20-F
    fu._blank_foreign_share_counts(m, ciks, out)
    assert np.isfinite(out["market_cap"][50:, 0]).all() and np.isfinite(out["pe"][50:, 3]).all()
    assert np.isnan(out["market_cap"][:, 1]).all() and np.isnan(out["pe"][:, 1]).all()
    assert np.isnan(out["market_cap"][50:, 2]).all() and np.isnan(out["pe"][50:, 2]).all()
