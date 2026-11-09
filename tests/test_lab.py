"""Self-improving lab: the sandbox validator, the look-ahead check and the fixed decision rules (no database, no AI)."""
import numpy as np
import pytest

from core.backtest.engine import Signal
from core.jobs.lab import decide
from core.lab.lookahead import check_strategy
from core.lab.sandbox import Rejected, validate
from core.strategy.base import FeatureStrategy
from tests.test_strategy import _market

GOOD = '''"""Test idea."""
import numpy as np

from core.backtest.engine import Signal
from core.strategy.base import FeatureStrategy, earnings_clear


class Good(FeatureStrategy):
    name = "good_idea"
    version = "1"
    description = "Stocks with the strongest month, a plain test description."
    hypothesis = "Momentum persists for a few weeks because investors under-react."
    params = {"w": 20}

    def eligible(self, t):
        return super().eligible(t)

    def score(self, t):
        w = self.params["w"]
        past = self.m.close[t - w + 1: t + 1]
        with np.errstate(invalid="ignore"):
            return past[-1] / past[0] - 1

    def plan(self, t, j):
        return Signal(self.m.symbols[j], stop=self.m.close[t, j] * 0.9, max_hold=20, tag=self.name)
'''


def test_validator_accepts_a_normal_strategy_and_the_existing_ones():
    assert validate(GOOD, "good_idea") == {"class": "Good"}
    from pathlib import Path
    for f in Path("strategies").rglob("*.py"):
        validate(f.read_text(), f.stem)


@pytest.mark.parametrize("change, why", [
    (("import numpy as np", "import os"), "import"),
    (("past[-1] / past[0] - 1", "open('/etc/passwd') and 0"), "open"),
    (("past = self.m.close[t - w + 1: t + 1]", "past = self.m.close[t - w + 1: t + 2]"), "past day t"),
    (("past = self.m.close[t - w + 1: t + 1]", "past = self.m.close[t:]"), "open-ended"),
    (("return past[-1] / past[0] - 1", "return self.m.close[t + 1] / self.m.close[t] - 1"), "future"),
    (("w = self.params[\"w\"]", "w = self.params[\"w\"]\n        while True:\n            pass"), "While"),
    (('name = "good_idea"', 'name = "other_name"'), "name must be"),
    (("past[-1] / past[0] - 1", "self.m.__class__"), "__class__"),
    (("past[-1] / past[0] - 1", "np.load('x')"), "numpy.load"),
])
def test_validator_rejects_unsafe_or_future_peeking_code(change, why):
    with pytest.raises(Rejected, match=why):
        validate(GOOD.replace(*change), "good_idea")


class Honest(FeatureStrategy):
    name = "test.honest"

    def score(self, t):
        return self.f["ret_20d"][t]

    def plan(self, t, j):
        return Signal(self.m.symbols[j], stop=self.m.close[t, j] * 0.9, max_hold=10)


class Cheater(Honest):
    """Uses tomorrow's close. The static validator would catch `t + 1`; this hides it from a naive check."""
    name = "test.cheater"

    def score(self, t):
        nxt = min(t + 1, len(self.m.dates) - 1)
        return self.m.close[nxt] / self.m.close[t] - 1


def test_lookahead_check_passes_honest_and_catches_cheater():
    m = _market(T=300, N=12)
    assert check_strategy(Honest, m, [150, 250]) == []
    problems = check_strategy(Cheater, m, [150, 250])
    assert problems and "score() differs" in problems[0]


def _res(vs20=0.0, t20=0.0, vs60=0.0, t60=0.0, n=500, passed=False, ex=0.0, tex=0.0, ok=True):
    return {"ok": ok, "passed_train": passed, "backtest": {"avg_excess": ex, "t_excess": tex},
            "signal_study": [{"horizon_days": 20, "signals": n, "vs_pool": vs20, "t_vs_pool_adj": t20},
                             {"horizon_days": 60, "signals": n, "vs_pool": vs60, "t_vs_pool_adj": t60}]}


def test_decision_rules():
    assert decide({"ok": False, "error": "boom"})[0] == "reject"
    assert decide(_res(vs60=0.02, t60=2.0, n=10))[0] == "reject"            # too few signals
    assert decide(_res(passed=True))[0] == "validate"
    assert decide(_res(vs60=0.0106, t60=0.64))[0] == "admit"                # insider_cluster-like: weak sign of life
    assert decide(_res(ex=0.004, tex=1.3))[0] == "admit"
    assert decide(_res(vs60=-0.01, t60=-1.0, vs20=0.001, t20=0.2))[0] == "reject"


def test_overlap_t_deflates_dense_overlap_but_not_sparse_signals():
    from core.lab.signal_study import t_overlap
    rng = np.random.default_rng(5)
    c = np.cumsum(rng.normal(0.0005, 0.01, 1800))
    f = c[60:] - c[:-60]                                       # overlapping 60-day returns, small true edge
    dense = t_overlap(f, np.arange(len(f)), 60)
    naive = f.mean() / (f.std(ddof=1) / np.sqrt(len(f)))
    assert abs(dense) < abs(naive) / 3                         # heavy overlap → big deflation
    d = np.arange(0, len(f), 70)                               # signals never overlap
    sparse = t_overlap(f[d], d, 60)
    raw = f[d].mean() / (f[d].std(ddof=1) / np.sqrt(len(d)))
    assert abs(sparse - raw) < 0.05 * abs(raw) + 0.05


def test_leave_best_year_out_and_unmeasurable_signal_study():
    from core.jobs.lab import leave_best_year_out
    yrs = [{"year": 2019, "trades": 50, "avg_excess": -0.02}, {"year": 2020, "trades": 70, "avg_excess": 0.15},
           {"year": 2021, "trades": 50, "avg_excess": -0.01}]
    assert leave_best_year_out(yrs) == pytest.approx(-0.015)
    r = _res(ex=0.03, tex=1.5)
    r["backtest"]["by_year"] = yrs
    assert decide(r)[0] == "reject"                            # one great year doesn't earn admission
    dec, why = decide(_res())
    assert dec == "reject" and "could not measure" in why
