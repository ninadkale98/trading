"""Company fundamentals from SEC XBRL filings, point-in-time (architecture §7, build plan 2.1).

Rules:
  • A number becomes visible on the day its filing was filed (`filed`), never earlier.
  • Each period uses the value as FIRST filed (later restatements are ignored here, which is conservative and honest).
  • Quarterly values are 3-month periods; a missing 4th quarter is derived as the annual value minus the first three.
  • TTM ("trailing twelve months") = sum of the last 4 consecutive quarters known at that date, else the last annual value.
  • Market cap = raw close × shares outstanding from the latest filing. A split after that filing distorts it until the
    next filing (rare, and fixed within a quarter).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

import numpy as np
import pandas as pd

from core.db import query

FEATURES = {
    "market_cap": "Company value: price × shares (dollars)",
    "revenue_ttm": "Sales over the last 12 months (dollars)",
    "rev_growth_yoy": "Sales growth: last 12 months vs the 12 months before",
    "rev_growth_q": "Sales growth of the latest quarter vs the same quarter a year earlier",
    "gross_margin": "Gross profit ÷ sales, last 12 months",
    "op_margin": "Operating profit ÷ sales, last 12 months",
    "op_margin_chg": "Change in operating margin vs a year earlier (percentage points as a fraction)",
    "net_margin": "Net profit ÷ sales, last 12 months",
    "pe": "Price ÷ earnings: market cap ÷ net profit over 12 months (blank if losing money)",
    "ps": "Price ÷ sales: market cap ÷ 12-month sales",
    "fcf_yield": "Free cash flow (operating cash − capital spending) ÷ market cap",
    "roe": "Return on equity: 12-month profit ÷ shareholders' equity",
    "debt_to_equity": "Long-term debt ÷ shareholders' equity",
    "insider_buyers_90d": "Number of different insiders who bought shares on the open market in the last 90 days",
    "insider_net_buy_90d": "Insider open-market buying minus selling over 90 days, as a fraction of market cap",
    "eps_surprise": "Last reported EPS surprise vs analyst estimate (Alpha Vantage), as a fraction",
    "eps_surprise_px": "Last EPS surprise scaled by share price: (actual − estimate) ÷ the close before the report. "
                       "Stable when the estimate is near zero, unlike eps_surprise (SUE-style)",
}
INT_FEATURES = {"insider_buyers_90d"}

FLOW = {  # metric → concepts in order of preference (first one a company reports wins)
    "revenue": ["us-gaap:Revenues", "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
                "us-gaap:RevenueFromContractWithCustomerIncludingAssessedTax", "us-gaap:SalesRevenueNet",
                "us-gaap:RevenuesNetOfInterestExpense", "us-gaap:SalesRevenueGoodsNet", "ifrs-full:Revenue"],
    "gross": ["us-gaap:GrossProfit", "ifrs-full:GrossProfit"],
    "cogs": ["us-gaap:CostOfRevenue", "us-gaap:CostOfGoodsAndServicesSold"],
    "opinc": ["us-gaap:OperatingIncomeLoss", "ifrs-full:ProfitLossFromOperatingActivities"],
    "netinc": ["us-gaap:NetIncomeLoss", "us-gaap:NetIncomeLossAvailableToCommonStockholdersBasic", "us-gaap:ProfitLoss",
               "ifrs-full:ProfitLoss"],
    "ocf": ["us-gaap:NetCashProvidedByUsedInOperatingActivities"],
    "capex": ["us-gaap:PaymentsToAcquirePropertyPlantAndEquipment"],
}
STOCK = {  # balance-sheet (point in time) metrics
    "equity": ["us-gaap:StockholdersEquity", "ifrs-full:Equity"],
    "ltdebt": ["us-gaap:LongTermDebtNoncurrent", "us-gaap:LongTermDebt"],
    "shares": ["dei:EntityCommonStockSharesOutstanding"],
}


def _load_facts(ciks: list[int], until: date) -> pd.DataFrame:
    concepts = sorted({c for v in (*FLOW.values(), *STOCK.values()) for c in v})
    rows = query("""SELECT cik, concept, unit, period_start, period_end, filed, value FROM financials
                    WHERE cik = ANY(%s) AND concept = ANY(%s) AND filed <= %s""", (ciks, concepts, until))
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df[df["unit"].isin(["USD", "shares"]) | df["concept"].str.startswith("dei")]
    # first filing of each period only (point-in-time; restatements ignored)
    df = df.sort_values("filed").drop_duplicates(["cik", "concept", "period_start", "period_end"], keep="first")
    bad = pd.Series(False, index=df.index)
    for c in ("period_start", "period_end", "filed"):
        raw = df[c]
        df[c] = pd.to_datetime(raw.astype(str).where(raw.notna()), errors="coerce")   # typos like year 0202 → NaT
        bad |= (raw.notna() & df[c].isna()) | (df[c] < "1990-01-01")
    df = df[~(bad | df["period_end"].isna() | df["filed"].isna())]
    df["days"] = (df["period_end"] - df["period_start"]).dt.days
    return df


def _quarters(f: pd.DataFrame) -> list[tuple]:
    """One company + concept → discrete quarters [(end, value, filed)], sorted by end. Q4 = annual − Q1..Q3 if needed."""
    rec = list(zip(f["period_start"], f["period_end"], f["days"], f["value"].astype(float), f["filed"]))
    q = {end: (val, filed) for start, end, days, val, filed in rec if 80 <= days <= 100}
    for start, end, days, val, filed in rec:
        if 350 <= days <= 380 and end not in q:
            inside = [(e, v, fd) for e, (v, fd) in q.items() if start < e < end]
            if len(inside) == 3:
                q[end] = (val - sum(v for _, v, _ in inside), max([filed] + [fd for _, _, fd in inside]))
    return sorted(((e, v, fd) for e, (v, fd) in q.items()), key=lambda x: x[0])


def _ttm_events(f: pd.DataFrame) -> list[tuple]:
    """(known_date, ttm, ttm_one_year_earlier, latest_quarter, same_quarter_last_year) after each filing."""
    if f.empty:
        return []
    q = _quarters(f)
    annual = sorted(((e, float(v), fd) for d, e, v, fd in zip(f["days"], f["period_end"], f["value"], f["filed"])
                     if 350 <= d <= 380), key=lambda x: x[0])
    year = pd.Timedelta(days=365)
    events = []
    for known in sorted({x[2] for x in q} | {x[2] for x in annual}):
        kq = [x for x in q if x[2] <= known]
        ttm = prev = lastq = lastq_ly = None
        if len(kq) >= 4 and (kq[-1][0] - kq[-4][0]).days <= 300:
            ttm = sum(x[1] for x in kq[-4:])
            if len(kq) >= 8 and (kq[-5][0] - kq[-8][0]).days <= 300 and (kq[-1][0] - kq[-5][0]).days <= 380:
                prev = sum(x[1] for x in kq[-8:-4])
        if kq:
            lastq = kq[-1][1]
            ly = [x for x in kq if abs((x[0] - (kq[-1][0] - year)).days) <= 20]
            lastq_ly = ly[-1][1] if ly else None
        if ttm is None:
            ka = [x for x in annual if x[2] <= known]
            if ka and (known - ka[-1][0]).days <= 460:
                ttm = ka[-1][1]
                prev = ka[-2][1] if len(ka) >= 2 else None
        events.append((known, ttm, prev, lastq, lastq_ly))
    return events


def _pick(f_cik: pd.DataFrame, concepts: list[str]) -> pd.DataFrame:
    """Merge a company's alternative labels for the same number (companies switch labels over the years, e.g.
    SalesRevenueNet → RevenueFromContractWithCustomer… in 2018): per period, the most preferred label wins."""
    sub = f_cik[f_cik["concept"].isin(concepts)]
    if sub.empty:
        return sub
    rank = {c: i for i, c in enumerate(concepts)}
    sub = sub.assign(_r=sub["concept"].map(rank)).sort_values(["period_start", "period_end", "_r"], na_position="first")
    return sub.drop_duplicates(["period_start", "period_end"], keep="first").drop(columns="_r")


def company_events(f_cik: pd.DataFrame) -> pd.DataFrame:
    """All fundamentals for one company as a table: one row per filing date, metrics as known after it."""
    cols: dict[str, dict] = defaultdict(dict)
    for metric, concepts in FLOW.items():
        for known, ttm, prev, lq, lqly in _ttm_events(_pick(f_cik, concepts)):
            cols[f"{metric}_ttm"][known] = ttm
            cols[f"{metric}_ttm_prev"][known] = prev
            if metric == "revenue":
                cols["revenue_q"][known] = lq
                cols["revenue_q_ly"][known] = lqly
    for metric, concepts in STOCK.items():
        s = _pick(f_cik, concepts)
        s = s[s["days"].isna() | (s["days"] <= 1)] if "days" in s else s
        for _, r in s.sort_values(["filed", "period_end"]).iterrows():
            cols[metric][r["filed"]] = float(r["value"])
    if not cols:
        return pd.DataFrame()
    return pd.DataFrame(cols).sort_index().ffill()


PRICE_X_SHARES = ("market_cap", "pe", "ps", "fcf_yield", "insider_net_buy_90d")


def foreign_filers(ciks: list[int]) -> set[int]:
    """Companies whose latest annual report is a 20-F (foreign private issuers). Their SEC share count is the home
    market's ordinary shares, while the US listing is usually an ADR worth 1–100+ of them (VOD, AKTX, EC…), so
    price × shares is wrong. Being a 20-F filer rarely changes, so the current status is used for all dates."""
    rows = query("""SELECT cik FROM filings WHERE cik = ANY(%s) GROUP BY cik
                    HAVING max(filed_at) FILTER (WHERE form IN ('20-F', '20-F/A'))
                           > coalesce(max(filed_at) FILTER (WHERE form IN ('10-K', '10-K/A')), '1900-01-01')""", (ciks,))
    return {r["cik"] for r in rows}


def _blank_foreign_share_counts(m, symbols_cik: dict[str, int], out: dict) -> None:
    """Blank price × shares features where the share count doesn't match the US listing: (1) 20-F filers; (2) any
    stock 'worth' over $2B that trades under 0.01% of that a day over 60 days (an ADR of a 10-K filer, e.g. AKTX at
    "$1.2T"; checked 2026-11-09: no ordinary stock is caught). (2) uses only past bars, so it's point-in-time."""
    foreign = foreign_filers(sorted({c for c in symbols_cik.values() if c}))
    cols = [j for j, s in enumerate(m.symbols) if symbols_cik.get(s) in foreign]
    mc = out["market_cap"]
    adv = pd.DataFrame(m.dollar_volume).rolling(60, min_periods=20).mean().to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        odd = (mc > 2e9) & (adv / mc < 1e-4)
    for k in PRICE_X_SHARES:
        out[k][:, cols] = np.nan
        out[k][odd] = np.nan


def compute(m, symbols_cik: dict[str, int]) -> dict[str, np.ndarray]:
    """Fundamental features aligned to the Market's dates × symbols."""
    T, N = m.close.shape
    out = {k: np.full((T, N), np.nan, dtype=np.float32) for k in FEATURES}
    ciks = sorted({c for c in symbols_cik.values() if c})
    if not ciks:
        return out
    facts = _load_facts(ciks, m.dates[-1].date())
    raw_close = _raw_close(m)
    dates = m.dates
    by_cik = {c: g for c, g in facts.groupby("cik")} if len(facts) else {}
    cache: dict[int, pd.DataFrame] = {}
    for j, sym in enumerate(m.symbols):
        cik = symbols_cik.get(sym)
        if not cik or cik not in by_cik:
            continue
        if cik not in cache:
            cache[cik] = company_events(by_cik[cik])
        ev = cache[cik]
        if ev.empty:
            continue
        a = ev.reindex(ev.index.union(dates)).astype(float).ffill().reindex(dates)
        a = a[a.index >= ev.index[0]].reindex(dates)          # nothing before the first filing
        g = lambda k: a[k].to_numpy(dtype=float) if k in a else np.full(T, np.nan)  # noqa: E731
        with np.errstate(divide="ignore", invalid="ignore"):
            rev, rev_prev = g("revenue_ttm"), g("revenue_ttm_prev")
            gross = g("gross_ttm")
            gross = np.where(np.isnan(gross), rev - g("cogs_ttm"), gross)
            opinc, opinc_prev, netinc = g("opinc_ttm"), g("opinc_ttm_prev"), g("netinc_ttm")
            mcap = raw_close[:, j] * g("shares")
            out["market_cap"][:, j] = mcap
            out["revenue_ttm"][:, j] = rev
            out["rev_growth_yoy"][:, j] = np.where(rev_prev > 0, rev / rev_prev - 1, np.nan)
            rq, rqly = g("revenue_q"), g("revenue_q_ly")
            out["rev_growth_q"][:, j] = np.where(rqly > 0, rq / rqly - 1, np.nan)
            out["gross_margin"][:, j] = np.where(rev > 0, gross / rev, np.nan)
            om = np.where(rev > 0, opinc / rev, np.nan)
            om_prev = np.where(rev_prev > 0, opinc_prev / rev_prev, np.nan)
            out["op_margin"][:, j] = om
            out["op_margin_chg"][:, j] = om - om_prev
            out["net_margin"][:, j] = np.where(rev > 0, netinc / rev, np.nan)
            out["pe"][:, j] = np.where(netinc > 0, mcap / netinc, np.nan)
            out["ps"][:, j] = np.where(rev > 0, mcap / rev, np.nan)
            out["fcf_yield"][:, j] = np.where(mcap > 0, (g("ocf_ttm") - np.nan_to_num(g("capex_ttm"))) / mcap, np.nan)
            eq = g("equity")
            out["roe"][:, j] = np.where(eq > 0, netinc / eq, np.nan)
            out["debt_to_equity"][:, j] = np.where(eq > 0, g("ltdebt") / eq, np.nan)
    _insiders(m, out)
    _surprise(m, out)
    _blank_foreign_share_counts(m, symbols_cik, out)
    for k in out:
        out[k][~np.isfinite(out[k])] = np.nan
    return out


def _raw_close(m) -> np.ndarray:
    """Market cap needs the actual traded price, not the split/dividend-adjusted one."""
    rows = query("SELECT symbol, date, close FROM daily_prices WHERE symbol = ANY(%s) AND date BETWEEN %s AND %s",
                 (m.symbols, m.dates[0].date(), m.dates[-1].date()))
    df = pd.DataFrame(rows)
    if df.empty:
        return np.full(m.close.shape, np.nan)
    df["date"] = pd.to_datetime(df["date"])
    p = df.pivot(index="date", columns="symbol", values="close").reindex(index=m.dates, columns=m.symbols)
    return p.to_numpy(dtype=float)


def _insiders(m, out) -> None:
    """Open-market insider purchases (code P) and sales (code S) over the trailing 90 days, by filing date."""
    rows = query("""SELECT symbol, filed_at, owner_name, code, shares * price AS value FROM insider_trades
                    WHERE symbol = ANY(%s) AND code IN ('P','S') AND filed_at BETWEEN %s AND %s AND price > 0""",
                 (m.symbols, (m.dates[0] - pd.Timedelta(days=95)).date(), m.dates[-1].date()))
    if not rows:
        return
    df = pd.DataFrame(rows)
    df["filed_at"] = pd.to_datetime(df["filed_at"])
    df["value"] = df["value"].astype(float)
    cal = pd.date_range(m.dates[0] - pd.Timedelta(days=95), m.dates[-1], freq="D")
    col = {s: j for j, s in enumerate(m.symbols)}
    for sym, g in df.groupby("symbol"):
        j = col.get(sym)
        if j is None:
            continue
        signed = g.assign(v=np.where(g["code"] == "P", g["value"], -g["value"])).groupby("filed_at")["v"].sum()
        net = signed.reindex(cal, fill_value=0.0).rolling(90, min_periods=1).sum().reindex(m.dates).to_numpy()
        # distinct buyers in the trailing 90 days: each buyer is "active" for 90 days after a purchase filing;
        # merge each buyer's overlapping windows, then count active buyers per day with +1/−1 steps
        steps = defaultdict(int)
        for _, gb in g[g["code"] == "P"].groupby("owner_name"):
            start = end = None
            for d in sorted(gb["filed_at"].unique()):
                d = pd.Timestamp(d)
                if start is not None and d <= end:
                    end = d + pd.Timedelta(days=89)
                    continue
                if start is not None:
                    steps[start] += 1
                    steps[end + pd.Timedelta(days=1)] -= 1
                start, end = d, d + pd.Timedelta(days=89)
            if start is not None:
                steps[start] += 1
                steps[end + pd.Timedelta(days=1)] -= 1
        active = pd.Series(steps, dtype=float).sort_index().cumsum() if steps else pd.Series(dtype=float)
        out["insider_buyers_90d"][:, j] = (active.reindex(active.index.union(m.dates)).ffill().reindex(m.dates)
                                           .fillna(0.0).to_numpy() if len(active) else 0.0)
        with np.errstate(divide="ignore", invalid="ignore"):
            out["insider_net_buy_90d"][:, j] = net / out["market_cap"][:, j]


def _surprise(m, out) -> None:
    """EPS surprise two ways, both known from the day after the report date (reports come before the open or after the
    close). `eps_surprise` is % of the estimate (noisy when the estimate is near zero: −$0.085 → +$0.17 reads +300%);
    `eps_surprise_px` divides the $ surprise by the split-adjusted close before the report. Alpha Vantage EPS history is
    split-adjusted (NVDA 2019 shows $0.02), so it matches close × adj_factor."""
    rows = query("""SELECT e.symbol, e.reported_date, e.surprise_pct,
                           (e.reported_eps - e.estimated_eps) / NULLIF(p.c, 0) AS sue
                    FROM earnings_history e
                    LEFT JOIN LATERAL (SELECT close * adj_factor AS c FROM daily_prices d
                                       WHERE d.symbol = e.symbol AND d.date < e.reported_date
                                       ORDER BY d.date DESC LIMIT 1) p ON true
                    WHERE e.symbol = ANY(%s) AND e.reported_date <= %s AND e.surprise_pct IS NOT NULL""",
                 (m.symbols, m.dates[-1].date()))
    if not rows:
        return
    df = pd.DataFrame(rows)
    df["reported_date"] = pd.to_datetime(df["reported_date"])
    col = {s: j for j, s in enumerate(m.symbols)}
    for sym, g in df.groupby("symbol"):
        g = g.drop_duplicates("reported_date", keep="last").set_index("reported_date")
        g.index = g.index + pd.Timedelta(days=1)
        idx = g.index.union(m.dates)
        for key, ser in (("eps_surprise", g["surprise_pct"].astype(float) / 100),
                         ("eps_surprise_px", pd.to_numeric(g["sue"], errors="coerce").astype(float))):
            # a report with no value must blank the feature, not carry the previous quarter's forward
            filled = ser.fillna(-9e9).reindex(idx).ffill().reindex(m.dates).to_numpy()
            out[key][:, col[sym]] = np.where(filled == -9e9, np.nan, filled)
