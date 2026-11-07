"""Insider trades (SEC Form 4) — who inside the company is buying or selling (architecture §3, §5.3).

• Bulk: SEC's quarterly "Insider Transactions Data Sets" (2016 → latest published quarter, ~1 quarter behind).
• Recent: individual Form 4 XML filings after the last bulk quarter (from our `filings` table).
Codes that matter most: P = open-market purchase (insider spends own money), S = open-market sale."""
from __future__ import annotations

import csv
import io
import re
import xml.etree.ElementTree as ET
import zipfile
from datetime import date, datetime, timedelta, timezone

from core.db import conn, query
from core.ingest import sec
from core.ingest.http import request
from core.tasks.errors import Permanent, ResourceLimited
from core.tasks.registry import TaskContext, task

LIST_URL = "https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets"
csv.field_size_limit(10_000_000)


def _d(s: str | None) -> date | None:
    if not s:
        return None
    for fmt in ("%d-%b-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s.strip()[:11], fmt).date()
        except ValueError:
            continue
    return None


def _f(s) -> float | None:
    try:
        return float(s) if s not in (None, "") else None
    except ValueError:
        return None


def _our_ciks() -> set[int]:
    return {r["cik"] for r in query("SELECT DISTINCT cik FROM stocks WHERE cik IS NOT NULL")}


def _insert(rows: list[tuple]) -> int:
    if not rows:
        return 0
    with conn() as c, c.cursor() as cur:
        cur.executemany(
            """INSERT INTO insider_trades (accession, line, issuer_cik, symbol, owner_name, owner_role, trade_date, code,
                                           shares, price, acquired, shares_after, filed_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""", rows)
    return len(rows)


def available_quarters() -> list[str]:
    html = sec.get_text(LIST_URL)
    return sorted(set(re.findall(r"(\d{4}q[1-4])_form345\.zip", html)))


def load_quarter(q: str, ciks: set[int]) -> int:
    url = f"https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/{q}_form345.zip"
    try:
        r = request(sec.client(), sec._limiter, sec.RESOURCE, "GET", url, follow_redirects=True, timeout=300)
    except Permanent as e:
        if " 404 " in f" {e} ":
            return None            # listed on the SEC page but not published yet: skip (recent Form 4s cover it)
        raise
    if not r.content.startswith(b"PK"):
        raise ResourceLimited(sec.RESOURCE, datetime.now(timezone.utc) + timedelta(minutes=10),
                              f"SEC returned a web page instead of {q} data (likely rate limited)")
    z = zipfile.ZipFile(io.BytesIO(r.content))

    def read(name):
        with z.open(name) as f:
            yield from csv.DictReader(io.TextIOWrapper(f, encoding="utf-8", errors="replace"), delimiter="\t")

    subs = {}
    for s in read("SUBMISSION.tsv"):
        if s["DOCUMENT_TYPE"] in ("4", "4/A") and s["ISSUERCIK"].isdigit() and int(s["ISSUERCIK"]) in ciks:
            subs[s["ACCESSION_NUMBER"]] = s
    owners: dict[str, list[str]] = {}
    for o in read("REPORTINGOWNER.tsv"):
        if o["ACCESSION_NUMBER"] in subs:
            role = o["RPTOWNER_TITLE"] or o["RPTOWNER_RELATIONSHIP"]
            owners.setdefault(o["ACCESSION_NUMBER"], []).append(f"{o['RPTOWNERNAME']}|{role}")
    rows = []
    for t in read("NONDERIV_TRANS.tsv"):
        s = subs.get(t["ACCESSION_NUMBER"])
        if not s:
            continue
        own = owners.get(t["ACCESSION_NUMBER"], ["|"])
        rows.append((t["ACCESSION_NUMBER"], int(t["NONDERIV_TRANS_SK"]), int(s["ISSUERCIK"]), s["ISSUERTRADINGSYMBOL"] or None,
                     "; ".join(x.split("|")[0] for x in own)[:300], own[0].split("|")[1][:120] or None,
                     _d(t["TRANS_DATE"]), t["TRANS_CODE"] or None, _f(t["TRANS_SHARES"]), _f(t["TRANS_PRICEPERSHARE"]),
                     t["TRANS_ACQUIRED_DISP_CD"] == "A", _f(t["SHRS_OWND_FOLWNG_TRANS"]), _d(s["FILING_DATE"])))
        if len(rows) >= 5000:
            _insert(rows)
            rows = []
    _insert(rows)
    return len(subs)


@task("insider.backfill", resource="sec", priority=25, description="Insider trades from SEC quarterly bulk files (resumable)")
def backfill(ctx: TaskContext) -> dict:
    quarters = [q for q in available_quarters() if q >= ctx.payload.get("from", "2016q1")]
    ciks = _our_ciks()
    done = set(ctx.progress.get("done", []))
    filings = ctx.progress.get("filings", 0)
    missing = []
    for q in quarters:
        if q in done:
            continue
        loaded = load_quarter(q, ciks)
        if loaded is None:
            missing.append(q)
            continue
        filings += loaded
        done.add(q)
        ctx.checkpoint(done=sorted(done), filings=filings, last_bulk=q)
    n = query("SELECT count(*) n FROM insider_trades")[0]["n"]
    last = max(done) if done else None
    return {"summary": f"insider trades: {len(done)} quarters loaded (through {last}), {n:,} transactions stored"
                       + (f"; not published yet: {', '.join(missing)}" if missing else ""),
            "quarters": len(done), "transactions": n, "last_bulk": last, "missing": missing}


def _xml_rows(accession: str, cik: int, primary_doc: str, filed: date) -> list[tuple]:
    path = re.sub(r"^xsl[^/]+/", "", primary_doc or "")
    if not path.endswith(".xml"):
        return []
    url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{path}"
    root = ET.fromstring(sec.get_text(url).encode())
    val = lambda el, p: (el.findtext(p + "/value") if el is not None and el.find(p + "/value") is not None
                         else (el.findtext(p) if el is not None else None))
    sym = root.findtext("issuer/issuerTradingSymbol")
    names, role = [], None
    for ro in root.findall("reportingOwner"):
        names.append(ro.findtext("reportingOwnerId/rptOwnerName") or "")
        rel = ro.find("reportingOwnerRelationship")
        if role is None and rel is not None:
            role = rel.findtext("officerTitle") or ("Director" if rel.findtext("isDirector") in ("1", "true") else
                                                    "10% Owner" if rel.findtext("isTenPercentOwner") in ("1", "true") else None)
    rows = []
    for i, tr in enumerate(root.findall("nonDerivativeTable/nonDerivativeTransaction")):
        rows.append((accession, 1_000_000 + i, cik, sym, "; ".join(names)[:300], (role or "")[:120] or None,
                     _d(val(tr, "transactionDate")), tr.findtext("transactionCoding/transactionCode"),
                     _f(val(tr, "transactionAmounts/transactionShares")), _f(val(tr, "transactionAmounts/transactionPricePerShare")),
                     val(tr, "transactionAmounts/transactionAcquiredDisposedCode") == "A",
                     _f(val(tr, "postTransactionAmounts/sharesOwnedFollowingTransaction")), filed))
    return rows


@task("insider.recent", resource="sec", priority=35, description="Parse Form 4 filings newer than the bulk data")
def recent(ctx: TaskContext) -> dict:
    limit = ctx.payload.get("limit", 4000)
    todo = query(
        """SELECT f.accession, f.cik, f.primary_doc, f.filed_at FROM filings f
           WHERE f.form IN ('4','4/A') AND f.filed_at >= COALESCE(
                 (SELECT max(filed_at) + 1 FROM insider_trades WHERE line < 1000000), DATE '2026-04-01')
             AND NOT EXISTS (SELECT 1 FROM insider_trades i WHERE i.accession = f.accession)
           ORDER BY f.filed_at DESC LIMIT %s""", (limit,))
    n = 0
    for i, f in enumerate(todo):
        try:
            n += _insert(_xml_rows(f["accession"], f["cik"], f["primary_doc"], f["filed_at"]))
        except (Permanent, ET.ParseError):
            continue              # missing/odd document: skip this filing, keep going
        if (i + 1) % 200 == 0:
            ctx.checkpoint(processed=i + 1)
    return {"summary": f"insider: parsed {len(todo):,} recent Form 4 filings → {n:,} transactions" if todo else None,
            "filings": len(todo), "transactions": n}
