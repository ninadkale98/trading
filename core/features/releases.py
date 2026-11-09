"""Features from Claude's reads of earnings press releases (`earnings_reads`, core/jobs/earnings_reads.py).

Point-in-time: a release's values appear on its reaction day (the same rule as core/features/earnings.py: a release
before 9:30 am ET is traded that day, otherwise the next trading day) and stay until the company's NEXT earnings
release, which replaces them (or blanks them if that release hasn't been read). Live reads exist from Nov 2026;
history reads fill in slowly in random order, so on old years these features are a sample (NaN = not read).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from core.db import query
from core.features.earnings import reaction_index

FEATURES = {
    "release_tone": "Claude's read of the last earnings press release: how good the quarter and outlook look (−2…+2); "
                    "NaN if that release hasn't been read",
    "guidance_change": "Last earnings release's outlook vs the previous one: +1 raised, −1 lowered or withdrawn, "
                       "0 maintained / initiated / mixed / none",
    "rev_surprise": "Last quarter's revenue vs the consensus estimate known before the release, as a fraction "
                    "(forward only: estimate snapshots start Nov 2026)",
}
INT_FEATURES = {"guidance_change"}
GUIDE = {"raised": 1, "lowered": -1, "withdrawn": -1, "maintained": 0, "initiated": 0, "mixed": 0, "none": 0}


def compute(m) -> dict[str, np.ndarray]:
    T, N = m.close.shape
    out = {k: np.full((T, N), np.nan, dtype=np.float32) for k in FEATURES}
    rows = query("""SELECT e.symbol, e.accepted_at, e.timing, r.status, r.tone, r.guidance, r.rev_surprise
                    FROM earnings_events e LEFT JOIN earnings_reads r ON r.accession = e.accession
                    WHERE e.symbol = ANY(%s) AND e.accepted_at >= %s AND e.accepted_at < %s""",
                 (m.symbols, (m.dates[0] - pd.Timedelta(days=200)).to_pydatetime(),
                  (m.dates[-1] + pd.Timedelta(days=1)).to_pydatetime()))
    if not rows:
        return out
    df = pd.DataFrame(rows)
    df = df[df["accepted_at"].notna()]
    df["t"] = reaction_index(m.dates, df["accepted_at"], df["timing"])
    df["j"] = pd.Index(m.symbols).get_indexer(df["symbol"])
    df = df[(df["t"] < T) & (df["j"] >= 0)].copy()
    ok = df["status"].eq("ok")
    df["release_tone"] = np.where(ok, pd.to_numeric(df["tone"], errors="coerce"), np.nan)
    df["guidance_change"] = np.where(ok, df["guidance"].map(GUIDE), np.nan)
    df["rev_surprise"] = np.where(ok, pd.to_numeric(df["rev_surprise"], errors="coerce"), np.nan)
    # releases before the range all land on day 0: only the latest of them counts
    first = df["t"].eq(0)
    latest0 = df[first].groupby("j")["accepted_at"].transform("max")
    df = df[~first | df["accepted_at"].eq(latest0.reindex(df.index))]
    # several filings for one reaction day (an 8-K and its amendment): prefer the one that was read
    df = df.assign(_ok=ok.reindex(df.index)).sort_values(["j", "t", "_ok", "accepted_at"])
    df = df.drop_duplicates(["j", "t"], keep="last")
    seen = np.zeros((T, N), dtype=bool)
    t0, j = df["t"].to_numpy(dtype=int), df["j"].to_numpy(dtype=int)
    vals = {k: np.full((T, N), np.nan, dtype=np.float32) for k in FEATURES}
    for k in FEATURES:
        vals[k][t0, j] = df[k].to_numpy(dtype=np.float64)
    seen[t0, j] = True
    last = np.maximum.accumulate(np.where(seen, np.arange(T)[:, None], -1), axis=0)
    has = last >= 0
    lc = np.clip(last, 0, None)
    cols = np.arange(N)[None, :]
    for k in FEATURES:
        out[k] = np.where(has, vals[k][lc, cols], np.nan).astype(np.float32)
    return out
