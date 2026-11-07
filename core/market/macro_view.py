"""Readable economy table from FRED data (latest value, previous, year ago). Shared by the dashboard and the AI market pack."""
from __future__ import annotations

import pandas as pd

from core.db import query


MACRO_SHOW = [  # (series, label, how to show the change)
    ("DFF", "Fed funds rate", "level"), ("DGS2", "2-year Treasury yield", "level"), ("DGS10", "10-year Treasury yield", "level"),
    ("T10Y2Y", "Yield curve (10y − 2y)", "level"), ("DFII10", "Real 10-year yield (after inflation)", "level"),
    ("BAMLH0A0HYM2", "Junk-bond spread (risk premium)", "level"), ("T10YIE", "Expected inflation (10-year)", "level"),
    ("CPIAUCSL", "Inflation (CPI, yearly)", "yoy"), ("CPILFESL", "Core inflation (CPI ex food & energy, yearly)", "yoy"),
    ("PCEPILFE", "Core PCE inflation (the Fed's gauge, yearly)", "yoy"), ("UNRATE", "Unemployment rate", "level"),
    ("PAYEMS", "Jobs added last month (thousands)", "diff"), ("ICSA", "Weekly jobless claims", "level"),
    ("RSAFS", "Retail sales (yearly)", "yoy"), ("INDPRO", "Industrial production (yearly)", "yoy"),
    ("UMCSENT", "Consumer sentiment", "level"), ("HOUST", "Housing starts (thousands, yearly rate)", "level"),
    ("DCOILWTICO", "Oil price (WTI, $)", "level"), ("DTWEXBGS", "US dollar index", "level"),
    ("NFCI", "Financial conditions (below 0 = easy money)", "level"),
]


def macro_table() -> list[dict]:
    out = []
    for sid, label, how in MACRO_SHOW:
        obs = query("""SELECT date, value_latest v, first_known FROM macro_obs WHERE series_id=%s AND value_latest IS NOT NULL
                       ORDER BY date DESC LIMIT 400""", (sid,))
        if not obs:
            continue
        info = query("SELECT frequency, units FROM macro_series WHERE series_id=%s", (sid,))[0]
        df = pd.DataFrame(obs).sort_values("date")
        df["date"] = pd.to_datetime(df["date"])
        s = df.set_index("date")["v"].astype(float)
        last_date = s.index[-1]

        def at(days):
            prev = s[s.index <= last_date - pd.Timedelta(days=days)]
            return float(prev.iloc[-1]) if len(prev) else None

        if how == "yoy":
            val = (s.iloc[-1] / at(365) - 1) * 100 if at(365) else None
            prev_m = s[s.index < last_date]
            p = prev_m.index[-1] if len(prev_m) else None
            base = s[s.index <= p - pd.Timedelta(days=365)] if p is not None else []
            before = (prev_m.iloc[-1] / base.iloc[-1] - 1) * 100 if p is not None and len(base) else None
            unit = "%"
        elif how == "diff":
            val = s.iloc[-1] - s.iloc[-2] if len(s) > 1 else None
            before = s.iloc[-2] - s.iloc[-3] if len(s) > 2 else None
            unit = "k"
        else:
            val, before, unit = float(s.iloc[-1]), at(30), info["units"] or ""
        out.append({"series": sid, "label": label, "date": last_date.date(), "value": val, "prev": before,
                    "year_ago": at(365) if how == "level" else None, "unit": unit, "freq": info["frequency"],
                    "published": obs[0]["first_known"]})
    return out
