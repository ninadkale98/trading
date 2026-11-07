"""Build plan 1.10: prove the data + backtester give correct, reproducible answers on known cases.
Run:  python -m core.backtest.validate"""
from __future__ import annotations

import numpy as np
import pandas as pd

from core.backtest import data, metrics
from core.backtest.engine import Config, run
from core.backtest.reference import BuyAndHold, TrendFilter, no_lookahead
from core.db import migrate, query


def pct(x):
    return f"{x * 100:+.2f}%"


def main() -> None:
    migrate()
    m = data.load("2016-01-01", "2026-12-31", symbols=["SPY", "AAPL", "QCOM", "SWKS", "CRUS", "KO", "SMH"])
    spy = m.close[:, m.col("SPY")]
    ok = np.where(np.isfinite(spy))[0]
    print(f"Data: {m.dates[0].date()} → {m.dates[-1].date()}, {len(m.dates)} days\n")

    # 1. Adjustment factors: AAPL split 4:1 in Aug 2020 (+ dividends) → early-2016 factor ≈ 0.22–0.25
    f = query("SELECT adj_factor FROM daily_prices WHERE symbol='AAPL' ORDER BY date LIMIT 1")[0]["adj_factor"]
    print(f"1) AAPL adjustment factor on its first 2016 bar: {f:.4f}  (expected ≈ 0.22–0.25: 4:1 split + dividends) "
          f"{'✓' if 0.20 < f < 0.26 else '✗'}")

    # 2. Buy & hold SPY must match SPY's own adjusted return (from the first open we can buy at)
    res = run(BuyAndHold("SPY"), m, Config(cost_bps={"liquid": 0, "thin": 0, "emerging": 0}, enforce_limits=False))  # benchmark: no 15% cap
    bt = res.equity.iloc[-1] / res.equity.iloc[0] - 1
    actual = spy[ok[-1]] / m.open[1, m.col("SPY")] - 1
    print(f"2) Buy & hold SPY: backtester {pct(bt)} vs actual {pct(actual * 0.999)} (0.1% kept as cash) "
          f"{'✓' if abs(bt - actual * 0.999) < 0.005 else '✗'}")
    metrics.record(BuyAndHold("SPY"), "custom", metrics.summarize(res, m), "validation 1.10")

    # 3. 200-day trend rule: should cut the worst drawdown (2020 crash, 2022 bear) at the cost of some return
    s = TrendFilter("SPY")
    r2 = run(s, m, Config(enforce_limits=False))
    sm = metrics.summarize(r2, m)
    bh = metrics.summarize(res, m)
    print(f"3) 200-day trend rule on SPY: return {pct(sm['total_return'])}, max drawdown {pct(sm['max_drawdown'])}, "
          f"{sm['trades']} trades, in the market {sm['avg_exposure']:.0%} of the time")
    print(f"   vs buy & hold: return {pct(bh['total_return'])}, max drawdown {pct(bh['max_drawdown'])} "
          f"{'✓ smaller drawdown' if sm['max_drawdown'] > bh['max_drawdown'] else '✗'}")
    metrics.record(s, "custom", sm, "validation 1.10")
    print(f"   no look-ahead: {'✓' if no_lookahead(TrendFilter('SPY'), m) else '✗ LEAK'}")

    # 4. Re-run the Apple → supplier study from our own database (Nov 2026 numbers, Alpaca direct)
    px = pd.DataFrame(m.close, index=m.dates, columns=m.symbols)
    r = px.pct_change().dropna()

    def resid(y, x):
        b = np.cov(y, x)[0, 1] / np.var(x, ddof=1)
        return y - b * x

    print("4) Apple → supplier study from our database (earlier study in brackets):")
    expected = {"QCOM": (0.51, 0.09), "SWKS": (0.59, 0.22), "CRUS": (0.51, 0.17)}
    for sup, (raw_e, res_e) in expected.items():
        raw = r["AAPL"].corr(r[sup])
        rr = resid(r["AAPL"], r["SPY"]).corr(resid(r[sup], r["SPY"]))
        good = abs(raw - raw_e) < 0.015 and abs(rr - res_e) < 0.015
        print(f"   AAPL vs {sup}: raw {raw:.2f} [{raw_e}], after removing market {rr:.2f} [{res_e}] {'✓' if good else '✗'}")
    print(f"\nBacktests recorded so far (multiple-testing counter): {metrics.tests_run()}")


if __name__ == "__main__":
    main()
