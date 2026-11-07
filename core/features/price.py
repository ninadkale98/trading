"""Daily price/volume features for every stock (architecture §7). One implementation, used by both the nightly job
and the backtester, so live and historical numbers can't drift apart.

Every value on row t uses only bars up to and including day t's close (point-in-time). Inputs are the aligned
(dates × symbols) arrays from `core.backtest.data.Market`; outputs are float32 arrays of the same shape.
Plain-language meanings are in `FEATURES` (shown on the dashboard and in learning/).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# name → plain-language meaning (kept next to the code so docs and dashboard can't go stale)
FEATURES: dict[str, str] = {
    "close": "Closing price (adjusted for splits and dividends)",
    "ret_1d": "Return today", "ret_5d": "Return over 1 week", "ret_20d": "Return over ~1 month",
    "ret_60d": "Return over ~3 months", "ret_120d": "Return over ~6 months", "ret_250d": "Return over ~1 year",
    "dist_sma20": "How far the price is above (+) or below (−) its 20-day average",
    "dist_sma50": "Distance from the 50-day average", "dist_sma200": "Distance from the 200-day average",
    "sma50_slope": "Is the 50-day average rising? (change over the last 20 days)",
    "sma200_slope": "Is the 200-day average rising? (change over the last 20 days)",
    "rsi14": "RSI: 0–100 momentum score (above 70 = stretched up, below 30 = stretched down)",
    "atr_pct": "Average daily range as % of price (how much it usually moves in a day)",
    "vol20": "Volatility over 1 month (yearly terms)", "vol60": "Volatility over 3 months (yearly terms)",
    "rvol": "Relative volume: today's volume ÷ the 20-day average (2 = twice normal)",
    "adv20": "Average dollars traded per day over 20 days",
    "accum_20": "Accumulation: share of 20-day volume on up days minus down days (−1 … +1)",
    "accum_50": "Accumulation over 50 days (−1 … +1)",
    "dist_52w_high": "Distance below the 52-week high (0 = at the high)",
    "dist_52w_low": "Distance above the 52-week low",
    "gap": "Opening gap today vs yesterday's close",
    "rs_spy_60": "3-month return minus SPY's (beating the market if > 0)",
    "rs_spy_120": "6-month return minus SPY's",
    "rs_sector_60": "3-month return minus its sector ETF's (beating its sector if > 0)",
    "rs_rank": "Relative-strength rank among all stocks, 1–99 (99 = strongest past-year performance)",
    "beta_250": "Beta: how much it tends to move when SPY moves 1% (1-year)",
    "trend_score": "Uptrend checklist, 0–5: above 50-day, 50-day above 200-day, 200-day rising, above 200-day, within 25% of high",
}
INT_FEATURES = {"rs_rank", "trend_score"}

SECTOR_ETF = {
    "Technology": "XLK", "Healthcare": "XLV", "Financials": "XLF", "Real Estate": "XLRE", "Energy": "XLE",
    "Materials": "XLB", "Industrials": "XLI", "Consumer Discretionary": "XLY", "Consumer Staples": "XLP",
    "Communication Services": "XLC", "Utilities": "XLU",
}


def _ratio(a: pd.DataFrame, b) -> pd.DataFrame:
    with np.errstate(divide="ignore", invalid="ignore"):
        out = a / b
    return out.replace([np.inf, -np.inf], np.nan)


def _chunk(close, open_, high, low, volume, dollar_volume, spy_close, bench_close) -> dict[str, pd.DataFrame]:
    """Features for one block of columns. All inputs are DataFrames (T × n) except spy_close (Series, T)."""
    C, O, H, L, V = close, open_, high, low, volume
    out: dict[str, pd.DataFrame] = {"close": C}
    prev = C.shift(1)
    r1 = _ratio(C, prev) - 1
    for n in (1, 5, 20, 60, 120, 250):
        out[f"ret_{n}d"] = r1 if n == 1 else _ratio(C, C.shift(n)) - 1

    sma = {n: C.rolling(n, min_periods=int(n * 0.9)).mean() for n in (20, 50, 200)}
    for n, s in sma.items():
        out[f"dist_sma{n}"] = _ratio(C, s) - 1
    out["sma50_slope"] = _ratio(sma[50], sma[50].shift(20)) - 1
    out["sma200_slope"] = _ratio(sma[200], sma[200].shift(20)) - 1

    d = C.diff()
    gain = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    loss = (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    rsi = 100 - 100 / (1 + _ratio(gain, loss))
    out["rsi14"] = rsi.where(~((loss == 0) & (gain > 0)), 100.0)

    tr = np.fmax(np.fmax(H - L, (H - prev).abs()), (L - prev).abs())   # true range; ignores a missing prev close
    out["atr_pct"] = _ratio(tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean(), C)
    out["vol20"] = r1.rolling(20, min_periods=15).std() * np.sqrt(252)
    out["vol60"] = r1.rolling(60, min_periods=50).std() * np.sqrt(252)

    out["rvol"] = _ratio(V, V.shift(1).rolling(20, min_periods=15).mean())
    out["adv20"] = dollar_volume.rolling(20, min_periods=15).mean()
    signed = V * np.sign(r1)
    for n in (20, 50):
        out[f"accum_{n}"] = _ratio(signed.rolling(n, min_periods=int(n * 0.8)).sum(), V.rolling(n, min_periods=int(n * 0.8)).sum())

    hi = H.rolling(252, min_periods=200).max()
    lo = L.rolling(252, min_periods=200).min()
    out["dist_52w_high"] = _ratio(C, hi) - 1
    out["dist_52w_low"] = _ratio(C, lo) - 1
    out["gap"] = _ratio(O, prev) - 1

    spy_r = {n: spy_close / spy_close.shift(n) - 1 for n in (60, 120)}
    out["rs_spy_60"] = out["ret_60d"].sub(spy_r[60], axis=0)
    out["rs_spy_120"] = out["ret_120d"].sub(spy_r[120], axis=0)
    out["rs_sector_60"] = out["ret_60d"] - (_ratio(bench_close, bench_close.shift(60)) - 1)

    sr = spy_close / spy_close.shift(1) - 1
    w, mp = 250, 200
    mx = r1.rolling(w, min_periods=mp).mean()
    my = sr.rolling(w, min_periods=mp).mean()
    mxy = r1.mul(sr, axis=0).rolling(w, min_periods=mp).mean()
    var = (sr ** 2).rolling(w, min_periods=mp).mean() - my ** 2
    out["beta_250"] = _ratio(mxy - mx.mul(my, axis=0), var.to_numpy()[:, None])

    checks = [C > sma[50], sma[50] > sma[200], out["sma200_slope"] > 0, C > sma[200], out["dist_52w_high"] > -0.25]
    score = sum(c.astype(float) for c in checks)
    out["trend_score"] = score.where(sma[200].notna() & hi.notna())

    # input for the cross-sectional rank (computed later across ALL stocks): weighted 3/6/9/12-month returns
    out["_rs_composite"] = (0.4 * (_ratio(C, C.shift(63)) - 1) + 0.2 * (_ratio(C, C.shift(126)) - 1)
                            + 0.2 * (_ratio(C, C.shift(189)) - 1) + 0.2 * (_ratio(C, C.shift(252)) - 1))
    return out


def compute(m, spy_close: np.ndarray, bench_close: np.ndarray | None = None,
            rank_mask: np.ndarray | None = None, chunk: int = 500) -> dict[str, np.ndarray]:
    """All features for a Market `m`.

    spy_close:   (T,) adjusted SPY closes aligned to m.dates.
    bench_close: (T, N) adjusted close of each column's sector ETF (NaN where unknown); None → no sector feature.
    rank_mask:   (N,) True for columns that take part in the 1–99 relative-strength rank (common stocks).
    """
    T, N = m.close.shape
    idx = pd.RangeIndex(T)
    spy = pd.Series(spy_close, index=idx)
    bench = bench_close if bench_close is not None else np.full((T, N), np.nan)
    res: dict[str, np.ndarray] = {}
    for a in range(0, N, chunk):
        b = min(a + chunk, N)
        df = lambda arr: pd.DataFrame(arr[:, a:b], index=idx)  # noqa: E731
        part = _chunk(df(m.close), df(m.open), df(m.high), df(m.low), df(m.volume), df(m.dollar_volume),
                      spy, df(bench))
        for k, v in part.items():
            res.setdefault(k, np.full((T, N), np.nan, dtype=np.float32))[:, a:b] = v.to_numpy(dtype=np.float32)
    comp = pd.DataFrame(res.pop("_rs_composite"))
    if rank_mask is not None:
        comp.loc[:, ~rank_mask] = np.nan
    res["rs_rank"] = (comp.rank(axis=1, pct=True) * 98 + 1).round().to_numpy(dtype=np.float32)
    return res
