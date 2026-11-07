"""Fundamentals: Q4 derivation, TTM, label merging and the point-in-time rule."""
import pandas as pd

from core.features import fundamentals as F


def _facts(rows):
    df = pd.DataFrame(rows, columns=["concept", "period_start", "period_end", "filed", "value"])
    for c in ("period_start", "period_end", "filed"):
        df[c] = pd.to_datetime(df[c])
    df["days"] = (df["period_end"] - df["period_start"]).dt.days
    df["cik"], df["unit"] = 1, "USD"
    return df


REV = "us-gaap:Revenues"
NEW = "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"


def test_q4_derived_from_annual_and_ttm():
    f = _facts([
        (REV, "2025-01-01", "2025-03-31", "2025-05-01", 100), (REV, "2025-04-01", "2025-06-30", "2025-08-01", 110),
        (REV, "2025-07-01", "2025-09-30", "2025-11-01", 120), (REV, "2025-01-01", "2025-12-31", "2026-02-15", 460),
    ])
    q = F._quarters(f)
    assert [round(v) for _, v, _ in q] == [100, 110, 120, 130]          # Q4 = 460 − 330
    ev = F._ttm_events(f)
    assert ev[-1][0] == pd.Timestamp("2026-02-15") and ev[-1][1] == 460  # TTM known only once the 10-K is filed
    assert all(e[1] is None for e in ev[:-1])                            # fewer than 4 quarters before that


def test_point_in_time_and_label_merge():
    f = _facts([
        (REV, "2024-01-01", "2024-03-31", "2024-05-01", 50),             # old label
        (NEW, "2025-01-01", "2025-03-31", "2025-05-01", 80),             # company switched labels
        (REV, "2025-01-01", "2025-03-31", "2025-05-01", 79),             # both present for the same period → preferred wins
    ])
    merged = F._pick(f, [REV, NEW])
    assert len(merged) == 2 and set(merged["value"]) == {50, 79}
    ev = F.company_events(f.assign(concept=REV))
    assert ev.index.min() == pd.Timestamp("2024-05-01")                 # nothing visible before the first filing date
