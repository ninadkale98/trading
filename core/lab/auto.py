"""Test runner for the self-improving lab. Always runs in its OWN process (never inside the daemon), so AI-written code
can't crash or hang the service, and the big research market's memory is freed when it ends.

  python -m core.lab.auto smoke --files lab/candidates/a.py lab/candidates/b.py --out /tmp/x.json
      Small recent market (~300 liquid stocks): imports, runs every method, checks speed and look-ahead.
  python -m core.lab.auto test  --files ... --out /tmp/y.json
      Full train period 2016–2022 (survivorship-free, fundamentals): look-ahead check, signal study, backtest + gates.
  python -m core.lab.auto features-lookahead
      Recomputes every feature from prices cut off at past days; values must not change (guards the engineer's edits).
"""
from __future__ import annotations

import argparse
import json
import math
import signal
import sys
import time
import traceback
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from core.config import ROOT
from core.lab.sandbox import Rejected, validate

MAX_SEC_PER_DAY_SMALL = 0.02          # per day on ~300 stocks ≈ 1 s on the full ~9,000: keeps backtests to minutes


class _Timeout(Exception):
    pass


def _alarm(_s, _f):
    raise _Timeout("took too long")


def _make(path: Path):
    from core.strategy.base import load_file
    validate(path.read_text(), path.stem)
    classes = load_file(path, "experimental")
    if len(classes) != 1:
        raise Rejected("file must define exactly one strategy class")
    return classes[0]


def _clean(x):
    if isinstance(x, dict):
        return {str(k): _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if isinstance(x, (np.floating, float)):
        return None if not math.isfinite(float(x)) else float(x)
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, (np.bool_,)):
        return bool(x)
    if hasattr(x, "isoformat"):
        return x.isoformat()
    return x


def small_market():
    from core.backtest.data import load
    from core.db import query
    from core.features import price
    from core.features.build import features_for_market
    # a fixed, size-spread sample (md5 order is arbitrary but stable): big and small companies alike
    liquid = [r["symbol"] for r in query("""SELECT l.symbol FROM liquidity l JOIN stocks s USING (symbol)
                                            WHERE l.date=(SELECT max(date) FROM liquidity) AND s.is_universe
                                              AND s.asset_type='common' AND l.adv20_dollar >= 1e6 AND l.price >= 5
                                            ORDER BY md5(l.symbol) LIMIT 300""")]
    syms = sorted(set(liquid) | {"SPY"} | set(price.SECTOR_ETF.values()))
    m = load(date.today() - timedelta(days=700), date.today(), symbols=syms)
    m.f = features_for_market(m, fundamentals_too=True)
    return m


def smoke(files: list[Path]) -> dict:
    from core.lab.lookahead import check_strategy
    m = small_market()
    T = len(m.dates)
    out = {}
    for path in files:
        r = {"ok": False}
        try:
            signal.signal(signal.SIGALRM, _alarm)
            signal.alarm(300)
            cls = _make(path)
            s = cls()
            s.prepare(m)
            t0, n_sig, n_days = time.time(), 0, 0
            for t in range(T - 120, T):
                el = s.eligible(t)
                sc = s.score(t)
                if np.shape(sc) != (len(m.symbols),) or np.shape(el) != (len(m.symbols),):
                    raise Rejected(f"score()/eligible() must return one value per stock, got {np.shape(sc)} / {np.shape(el)}")
                n_sig += int(np.sum(el & np.isfinite(sc)))
                n_days += 1
                for j in s.picks(t, set()):
                    sig = s.plan(t, j)
                    if sig.stop is None or not (0 < sig.stop < m.close[t, j]):
                        raise Rejected(f"plan() must set a stop below the price (got {sig.stop} vs close {m.close[t, j]:.2f})")
                s.exits(t, m, set(m.symbols[:5]))
                s.why(t, int(np.argmax(np.isfinite(sc)))) if np.isfinite(sc).any() else None
            per_day = (time.time() - t0) / max(n_days, 1)
            if per_day > MAX_SEC_PER_DAY_SMALL:
                raise Rejected(f"too slow: {per_day:.3f}s per day on 300 stocks (limit {MAX_SEC_PER_DAY_SMALL}s); vectorize with numpy")
            problems = check_strategy(cls, m, [T - 100, T - 40, T - 2])
            if problems:
                raise Rejected("look-ahead: " + "; ".join(problems[:3]))
            r = {"ok": True, "signals_last_120d": n_sig, "sec_per_day": round(per_day, 4)}
        except Exception as e:                                          # noqa: BLE001
            tb = traceback.format_exc(limit=-3)
            r = {"ok": False, "error": f"{type(e).__name__}: {e}", "trace": tb[-1500:]}
        finally:
            signal.alarm(0)
        out[path.stem] = r
    return out


def test(files: list[Path]) -> dict:
    from core.backtest.metrics import PERIODS
    from core.features.build import research_market
    from core.lab.evaluate import evaluate, slice_market
    from core.lab.lookahead import check_strategy
    from core.lab.signal_study import study
    start, end = PERIODS["train"]
    m = research_market(date(2016, 1, 1), date.fromisoformat(end), fundamentals_too=True)
    pm = slice_market(m, start, end)
    T = len(pm.dates)
    out = {}
    for path in files:
        r = {}
        try:
            cls = _make(path)
            t0 = time.time()
            problems = check_strategy(cls, pm, [int(T * 0.35), int(T * 0.6), int(T * 0.9)])
            r["lookahead"] = problems
            if problems:
                out[path.stem] = {"ok": False, "error": "look-ahead: " + "; ".join(problems[:3]), **r}
                continue
            ss = study(cls(), pm)
            r["signal_study"] = ss.drop(columns=["strategy"]).to_dict("records")
            rep = evaluate(cls(), m, "train", notes="auto lab")
            mm = rep.metrics
            r["backtest"] = {k: mm.get(k) for k in ("trades", "win_rate", "expectancy", "avg_excess", "t_excess",
                                                     "excess_vs_twin", "t_vs_twin", "avg_hold_days", "max_drawdown",
                                                     "sleeve_vs_spy", "exit_reasons", "by_year")}
            r["gates"] = rep.gates
            r["passed_train"] = rep.passed
            r["run_id"] = rep.run_id
            r["seconds"] = round(time.time() - t0)
            r["ok"] = True
        except Exception as e:                                          # noqa: BLE001
            r.update({"ok": False, "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc(limit=-3)[-1500:]})
        out[path.stem] = r
    return out


def validate_period(files: list[Path]) -> dict:
    """Second gate for anything that passed train: the unseen 2023–2024 years."""
    from core.backtest.metrics import PERIODS
    from core.features.build import research_market
    from core.lab.evaluate import evaluate
    start, end = PERIODS["validate"]
    m = research_market(date.fromisoformat(start) - timedelta(days=400), date.fromisoformat(end), fundamentals_too=True)
    out = {}
    for path in files:
        try:
            rep = evaluate(_make(path)(), m, "validate", notes="auto lab")
            out[path.stem] = {"ok": True, "passed_validate": rep.passed, "gates": rep.gates, "run_id": rep.run_id,
                              "avg_excess": rep.metrics.get("avg_excess"), "trades": rep.metrics.get("trades")}
        except Exception as e:                                          # noqa: BLE001
            out[path.stem] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    return out


def features_lookahead() -> dict:
    from core.lab.lookahead import check_features
    m = small_market()
    T = len(m.dates)
    problems = check_features(m, [T - 200, T - 30], fundamentals_too=True)
    return {"ok": not problems, "problems": problems[:20]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["smoke", "test", "validate", "features-lookahead"])
    ap.add_argument("--files", nargs="*", default=[])
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    files = [Path(f) if Path(f).is_absolute() else ROOT / f for f in a.files]
    res = {"smoke": smoke, "test": test, "validate": validate_period}.get(a.cmd)
    res = res(files) if res else features_lookahead()
    text = json.dumps(_clean(res), indent=1, default=str)
    if a.out:
        Path(a.out).write_text(text)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
