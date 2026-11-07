"""SEC EDGAR loaders (build plan 1.7): company profiles + filing history, XBRL financials, nightly new filings.
All facts are point-in-time: a financial number is usable only from the date it was filed."""
from __future__ import annotations

import re
from datetime import date, timedelta

from core.db import conn, query
from core.ingest import sec
from core.sectors import sector_for_sic
from core.tasks import queue
from core.tasks.errors import Permanent
from core.tasks.registry import TaskContext, task

FORMS = {"10-K", "10-K/A", "10-Q", "10-Q/A", "8-K", "8-K/A", "20-F", "20-F/A", "40-F", "6-K", "4", "4/A",
         "SC 13D", "SC 13D/A", "SC 13G", "SC 13G/A", "S-1", "S-1/A", "DEF 14A"}
HISTORY_FROM = "2016-01-01"

# XBRL concepts we keep (us-gaap and IFRS names for the same idea)
CONCEPTS = {
    "us-gaap": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet", "CostOfRevenue",
                "RevenueFromContractWithCustomerIncludingAssessedTax", "RevenuesNetOfInterestExpense", "SalesRevenueGoodsNet",
                "CostOfGoodsAndServicesSold", "ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic",
                "GrossProfit", "OperatingIncomeLoss", "NetIncomeLoss", "EarningsPerShareBasic", "EarningsPerShareDiluted",
                "ResearchAndDevelopmentExpense", "CashAndCashEquivalentsAtCarryingValue", "Assets", "Liabilities",
                "StockholdersEquity", "LongTermDebt", "LongTermDebtNoncurrent",
                "NetCashProvidedByUsedInOperatingActivities", "PaymentsToAcquirePropertyPlantAndEquipment",
                "WeightedAverageNumberOfDilutedSharesOutstanding"],
    "ifrs-full": ["Revenue", "GrossProfit", "ProfitLoss", "ProfitLossFromOperatingActivities", "BasicEarningsLossPerShare",
                  "DilutedEarningsLossPerShare", "CashAndCashEquivalents", "Assets", "Liabilities", "Equity"],
    "dei": ["EntityCommonStockSharesOutstanding"],
}


def _store_filings(cik: int, recent: dict) -> int:
    rows = []
    for i, acc in enumerate(recent.get("accessionNumber", [])):
        form = recent["form"][i]
        filed = recent["filingDate"][i]
        if form not in FORMS or filed < HISTORY_FROM:
            continue
        rows.append((acc, cik, form, filed, recent.get("acceptanceDateTime", [None] * (i + 1))[i] or None,
                     recent.get("reportDate", [""] * (i + 1))[i] or None, recent.get("items", [""] * (i + 1))[i] or None,
                     recent.get("primaryDocument", [""] * (i + 1))[i] or None))
    if rows:
        with conn() as c, c.cursor() as cur:
            cur.executemany(
                """INSERT INTO filings (accession, cik, form, filed_at, accepted_at, report_date, items, primary_doc)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (accession) DO UPDATE SET items=COALESCE(EXCLUDED.items, filings.items),
                     accepted_at=COALESCE(EXCLUDED.accepted_at, filings.accepted_at)""", rows)
    return len(rows)


def sync_company(cik: int, full_history: bool) -> dict:
    s = sec.submissions(cik)
    sic = int(s["sic"]) if str(s.get("sic") or "").isdigit() else None
    with conn() as c:
        c.execute("UPDATE stocks SET sic=%s, sic_description=%s, sector=%s, updated_at=now() WHERE cik=%s",
                  (sic, s.get("sicDescription"), sector_for_sic(sic), cik))
    n = _store_filings(cik, s["filings"]["recent"])
    if full_history:
        for f in s["filings"].get("files", []):
            if f.get("filingTo", "9999") >= HISTORY_FROM:
                n += _store_filings(cik, sec.get_json(f"https://data.sec.gov/submissions/{f['name']}"))
    return {"filings": n, "sic": sic}


def sync_financials(cik: int) -> int:
    try:
        facts = sec.company_facts(cik).get("facts") or {}
    except Permanent as e:
        if "404" in str(e):
            return 0          # no XBRL financials (e.g. some foreign filers)
        raise
    best: dict[tuple, tuple] = {}
    for ns, names in CONCEPTS.items():
        for name in names:
            for unit, items in ((facts.get(ns) or {}).get(name) or {}).get("units", {}).items():
                for it in items:
                    if it.get("end", "") < "2014-01-01" or "accn" not in it:
                        continue
                    key = (f"{ns}:{name}", unit, it.get("start"), it["end"])
                    row = (cik, f"{ns}:{name}", unit, it.get("start"), it["end"], it.get("fy"), it.get("fp"),
                           it.get("form"), it["filed"], it["accn"], float(it["val"]))
                    prev = best.get(key)
                    # keep the first filing of each number, plus later filings only if the number changed (restatement)
                    if prev is None or (row[8] < prev[0][8]):
                        best[key] = (row, [])
                    elif abs(row[10] - prev[0][10]) > 1e-9 and all(abs(row[10] - r[10]) > 1e-9 for r in prev[1]):
                        prev[1].append(row)
    rows = [r for first, restated in best.values() for r in [first, *restated]]
    if rows:
        with conn() as c, c.cursor() as cur:
            cur.executemany(
                """INSERT INTO financials (cik, concept, unit, period_start, period_end, fy, fp, form, filed, accession, value)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""", rows)
    return len(rows)


def _universe_ciks() -> list[int]:
    return [r["cik"] for r in query("SELECT DISTINCT cik FROM stocks WHERE is_universe AND cik IS NOT NULL ORDER BY cik")]


@task("sec.backfill", resource="sec", priority=30, description="Company profiles, sectors, filing history and financials (resumable)")
def backfill(ctx: TaskContext) -> dict:
    ciks = ctx.payload.get("ciks") or _universe_ciks()
    done = ctx.progress.get("done", 0)
    filings = ctx.progress.get("filings", 0)
    facts = ctx.progress.get("facts", 0)
    skipped = ctx.progress.get("skipped", [])
    for i in range(done, len(ciks)):
        try:
            r = sync_company(ciks[i], full_history=True)
            filings += r["filings"]
            facts += sync_financials(ciks[i])
        except (Permanent, KeyError, ValueError, TypeError) as e:
            # bad data for ONE company must not stop the other thousands; note it and move on
            skipped.append(ciks[i])
            ctx.log(f"SEC backfill: skipped CIK {ciks[i]} ({type(e).__name__}: {e})")
        if (i + 1) % 25 == 0 or i + 1 == len(ciks):
            ctx.checkpoint(done=i + 1, filings=filings, facts=facts, skipped=skipped)
        if (i + 1) % 500 == 0:
            ctx.log(f"SEC backfill {i + 1:,}/{len(ciks):,} companies: {filings:,} filings, {facts:,} financial facts")
    return {"summary": f"SEC backfill: {len(ciks):,} companies, {filings:,} filings, {facts:,} financial facts"
                       f"{f', {len(skipped)} skipped' if skipped else ''}",
            "companies": len(ciks), "filings": filings, "facts": facts, "skipped": skipped}


@task("sec.financials_refresh", resource="sec", priority=35, description="Re-download financial numbers for every company (after adding concepts; resumable)")
def financials_refresh(ctx: TaskContext) -> dict:
    ciks = ctx.payload.get("ciks") or _universe_ciks()
    done, facts, skipped = ctx.progress.get("done", 0), ctx.progress.get("facts", 0), ctx.progress.get("skipped", [])
    for i in range(done, len(ciks)):
        try:
            facts += sync_financials(ciks[i])
        except (Permanent, KeyError, ValueError, TypeError) as e:
            skipped.append(ciks[i])
            ctx.log(f"financials refresh: skipped CIK {ciks[i]} ({type(e).__name__}: {e})")
        if (i + 1) % 25 == 0 or i + 1 == len(ciks):
            ctx.checkpoint(done=i + 1, facts=facts, skipped=skipped)
    queue.enqueue("features.backfill", {}, priority=40, dedupe_key="features.backfill")   # rebuild stored fundamentals
    return {"summary": f"financials refreshed: {len(ciks):,} companies, {facts:,} facts" + (f", {len(skipped)} skipped" if skipped else ""),
            "facts": facts, "skipped": skipped}


_SUFFIX = re.compile(r"\b(common stock|ordinary shares|american depositary shares?.*|depositary shares?.*|class [a-c]\b.*|"
                     r"inc|incorporated|corp|corporation|co|company|ltd|limited|plc|llc|l\.?p|sa|nv|ag|se|the)\b")


def _norm(name: str) -> str:
    n = re.sub(r"[.,&'/()-]", " ", name.lower())
    n = _SUFFIX.sub(" ", n)
    return " ".join(n.split())


@task("sec.delisted_ciks", resource="sec", priority=35, description="Find SEC ids for delisted companies by name (survivorship)")
def delisted_ciks(ctx: TaskContext) -> dict:
    """SEC's ticker file only lists current companies, so delisted stocks have no CIK and no fundamentals. Match their
    names against EDGAR's full filer list; accept only a unique exact match of the normalized name."""
    todo = query("""SELECT DISTINCT symbol, name FROM stocks WHERE status='inactive' AND asset_type='common' AND cik IS NULL
                    AND NOT EXISTS (SELECT 1 FROM stocks a WHERE a.symbol = stocks.symbol AND a.status = 'active')""")
    wanted: dict[str, list[str]] = {}
    for r in todo:
        if r["name"]:
            wanted.setdefault(_norm(r["name"]), []).append(r["symbol"])
    hits: dict[str, set[int]] = {}
    for line in sec.get_text("https://www.sec.gov/Archives/edgar/cik-lookup-data.txt").splitlines():
        parts = line.rsplit(":", 2)
        if len(parts) < 3 or not parts[1].isdigit():
            continue
        key = _norm(parts[0])
        if key in wanted:
            hits.setdefault(key, set()).add(int(parts[1]))
    matched, ambiguous = {}, 0
    for key, ciks in hits.items():
        if len(ciks) == 1:
            for sym in wanted[key]:
                matched[sym] = next(iter(ciks))
        else:
            ambiguous += 1
    with conn() as c:
        for sym, cik in matched.items():
            c.execute("UPDATE stocks SET cik=%s WHERE symbol=%s AND status='inactive' AND cik IS NULL", (cik, sym))
    if matched:
        queue.enqueue("sec.backfill", {"ciks": sorted(set(matched.values()))}, priority=34, resource="sec",
                      dedupe_key="sec.backfill:delisted")
    return {"summary": f"delisted companies: {len(matched)} of {len(todo)} matched to SEC ids ({ambiguous} ambiguous names skipped)",
            "matched": len(matched), "candidates": len(todo), "ambiguous": ambiguous}


@task("sec.company", resource="sec", priority=60, description="Refresh one company's filings (and financials after a 10-K/10-Q)")
def company(ctx: TaskContext) -> dict:
    cik = int(ctx.payload["cik"])
    r = sync_company(cik, full_history=False)
    n = sync_financials(cik) if ctx.payload.get("financials") else 0
    return {"filings": r["filings"], "facts": n}


@task("sec.daily", resource="sec", priority=60, description="Find today's new filings for our companies")
def daily(ctx: TaskContext) -> dict:
    """Read EDGAR's daily form index for the last few business days and refresh companies that filed."""
    ours = set(_universe_ciks())
    days = ctx.payload.get("days", 4)
    touched: dict[int, bool] = {}
    d = date.today()
    for _ in range(days + 3):
        if d.weekday() < 5:
            q = (d.month - 1) // 3 + 1
            url = f"https://www.sec.gov/Archives/edgar/daily-index/{d.year}/QTR{q}/form.{d:%Y%m%d}.idx"
            try:
                text = sec.get_text(url)
            except Permanent:
                text = ""          # no index for that day (holiday / not published yet)
            for line in text.splitlines():
                parts = line.split()
                if len(parts) < 5 or not parts[-3].isdigit():
                    continue
                cik = int(parts[-3])
                form = " ".join(parts[:-4]) if len(parts) > 5 else parts[0]
                if cik in ours and any(form.startswith(f) for f in ("10-K", "10-Q", "8-K", "20-F", "6-K", "4", "SC 13")):
                    touched[cik] = touched.get(cik, False) or form.startswith(("10-K", "10-Q", "20-F"))
            days -= 1
            if days <= 0:
                break
        d -= timedelta(days=1)
    for cik, fin in touched.items():
        queue.enqueue("sec.company", {"cik": cik, "financials": fin}, priority=60, resource="sec",
                      dedupe_key=f"sec.company:{cik}")
    return {"summary": f"SEC: {len(touched)} companies filed recently; refresh queued" if touched else None,
            "companies": len(touched)}
