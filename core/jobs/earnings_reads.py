"""Earnings release reader (build plan 4.1).

Companies publish their quarterly results as a press release attached to an 8-K (item 2.02, usually exhibit 99.1).
This module:
  1. `sec.earnings_poll` (every 20 min on weekdays): reads EDGAR's live 8-K feed, so a release filed at 4:05 pm is
     known minutes later instead of at the 10:15 pm daily index. New item 2.02 filings go into `filings`.
  2. `earnings.read` (chained after the poll): for each new release of a stock we could trade, fetch the press
     release, mask the company's name, ticker, web addresses and calendar years, and have Claude extract: revenue, EPS,
     guidance (raised / maintained / lowered / …), tone (−2…+2), one-offs, positives/negatives. The surprise vs the
     consensus estimate is computed from our own calendar snapshots (known before the release), not by the model.
  3. `earnings.read_history` (hourly, low priority): the same for past releases 2016+, in a fixed random order so any
     partial fill is a fair sample of all years. History reads are marked mode='history': masking hides the name and
     year, but the model may still recognise a famous company, so these are research material and forward tests decide.
Results: `earnings_reads`; features `release_tone`, `guidance_change`, `rev_surprise` (core/features/releases.py).
"""
from __future__ import annotations

import html
import json
import re
from datetime import date, datetime, timedelta

from core.ai import claude
from core.config import settings
from core.db import conn, execute, query
from core.ingest import sec
from core.tasks import queue
from core.tasks.errors import Permanent
from core.tasks.registry import TaskContext, task

MAX_CHARS = 24_000              # the narrative + guidance come first; long financial tables at the end are cut
LIVE_DAYS = 3                   # a read within 3 days of filing counts as 'live' (no hindsight possible)
MIN_ADV, MIN_PRICE = 1e6, 5.0   # only stocks a strategy could actually trade (same as the lab's sample)
GUIDANCE = ["raised", "maintained", "lowered", "initiated", "withdrawn", "mixed", "none"]


def model() -> str:
    return (settings().get("earnings_reads") or {}).get("model", "haiku")


# ── text preparation ──────────────────────────────────────────────────────────────────────────────────────────────

def _cell(c: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", c)).replace("\xa0", " ").split())


def _row(m: re.Match) -> str:
    cells = [_cell(c) for c in re.findall(r"(?is)<t[dh][^>]*>(.*?)</t[dh]>", m.group(0))]
    cells = [c for c in cells if c and c not in ("$", "%", ")")]
    return "\n" + " | ".join(cells) + "\n" if cells else "\n"


def html_to_text(raw: str) -> str:
    """Plain text; each table row on one line ('Revenue | 90,400 | 83,600'), so tables cost few tokens."""
    t = re.sub(r"(?is)<(script|style|head)[^>]*>.*?</\1>", " ", raw)
    t = re.sub(r"(?is)<tr[^>]*>.*?</tr>", _row, t)
    t = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h\d|table)>", "\n", t)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t)).replace("\xa0", " ")
    t = re.sub(r"[ \t\r\f\v]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n\n", t).strip()


_SUFFIX = re.compile(r"[,.]?\s+(inc|incorporated|corp|corporation|co|company|holdings?|group|ltd|limited|plc|n\.?v|"
                     r"s\.?a|ag|se|lp|l\.?p|llc|trust|bancorp|technologies|international|"
                     r"(class [a-c] )?(common|ordinary|subordinate voting|voting) (stock|shares)|common|"
                     r"american depositary shares?|ads|depositary shares?|shares of beneficial interest)\.?$", re.I)
_COMMON_WORDS = {"american", "general", "first", "united", "national", "international", "advanced", "global", "new",
                 "western", "eastern", "southern", "northern", "applied", "digital", "pacific", "atlantic", "capital",
                 "royal", "great", "central", "community", "universal", "federal", "standard", "premier", "select",
                 "bank", "the", "us", "u.s.", "north", "south", "east", "west", "energy", "health", "home", "life",
                 "data", "power", "real", "trust", "financial", "medical", "summit", "liberty", "union", "city"}


def name_variants(name: str, text: str = "") -> list[str]:
    """Ways the release may name the company: the full legal name, without suffixes ('Common Stock', 'Inc.'), its
    distinctive first word ('Fulgent'), and short names the release defines itself: (“Fulgent,” or the “Company”)."""
    out, n = [], (name or "").strip()
    while n and n not in out:
        out.append(n)
        n2 = _SUFFIX.sub("", n).strip(" ,.")
        if n2 == n:
            break
        n = n2
    first = n.split()[0].strip(",.") if n.split() else ""
    if len(first) >= 4 and first.lower() not in _COMMON_WORDS:
        out.append(first)
    for d in re.findall(r"\(\s*(?:the\s+)?[“\"]([^”\"]{2,40}?)[,]?[”\"]", text[:6000]):
        d = d.strip(" ,.")
        if d.lower() not in ("company", "we", "us", "our", "the company", "registrant") and len(d) >= 3:
            out.append(d)
    return [v for v in dict.fromkeys(out) if len(v) >= 3]


def mask(text: str, name: str, symbol: str, year: int) -> str:
    """Hide what identifies the company and the calendar date: names → 'the Company', ticker → 'TICKER', URLs and
    e-mails removed, years → Y0 (filing year), Y-1, Y+1 … so 'fiscal 2027 guidance' keeps its meaning."""
    for v in sorted(name_variants(name, text), key=len, reverse=True):
        text = re.sub(r"(?i)\b" + re.escape(v) + r"(?:['’]s)?\b", "the Company", text)
    if symbol:
        sym = re.escape(symbol.replace(".", "-")).replace(r"\-", r"[.\-]?")
        text = re.sub(r"(?i)((?:nasdaq|nyse|amex|american|tsx|otc\w*)(?:\s*\w+)?\s*:\s*)" + sym + r"\b", r"\1TICKER", text)
        if len(symbol) >= 3:                     # bare 1–2 letter tickers (ON, IT, A) are ordinary words
            text = re.sub(r"\b" + sym + r"\b", "TICKER", text)
    # executives: "Jane Q. Doe, Chief Executive Officer" → hide the full name and the surname everywhere
    title = r"(?:Chair|Chairman|Chairwoman|Chief|President|CEO|CFO|COO|Founder|Co-Founder|Executive|Senior|Vice|Treasurer|Head|General Counsel|Director)"
    for full in set(re.findall(r"\b([A-Z][a-z'’-]+(?: [A-Z]\.?)?(?: [A-Z][a-z'’-]+){1,2}),?\s+(?:the\s+|our\s+)?(?:Company'?s?\s+)?" + title, text)):
        for v in (full, full.split()[-1]):
            if len(v) >= 3 and v.lower() not in _COMMON_WORDS:
                text = re.sub(r"\b" + re.escape(v) + r"\b", "[executive]", text)
    text = re.sub(r"(?i)\b(?:https?://|www\.)\S+", "[link]", text)
    text = re.sub(r"(?i)\b[\w-]+\.(?:com|net|io|ai|co)\b", "[link]", text)
    text = re.sub(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b", "[email]", text)

    def _yr(m):
        d = int(m.group(0)) - year
        return "Y0" if d == 0 else f"Y{d:+d}"
    text = re.sub(r"\b(?:19[89]\d|20[0-4]\d)\b", _yr, text)
    text = re.sub(r"\b(?:FY|Q[1-4]\s?)'?(\d{2})\b", lambda m: m.group(0)[:-2] + "YY", text)   # FY26 / Q3'26
    return text


def pick_release(docs: list[dict]) -> dict | None:
    """Exhibit 99.1 (the press release); else the first other EX-99.x document."""
    ex = [d for d in docs if d["type"].startswith("EX-99") and d["url"].lower().endswith((".htm", ".html", ".txt"))]
    ex.sort(key=lambda d: (d["type"] != "EX-99.1", d["type"]))
    return ex[0] if ex else None


# ── the Claude call ───────────────────────────────────────────────────────────────────────────────────────────────

SYSTEM = (
    "You read company earnings press releases for a stock research database. The company's name, ticker and the "
    "calendar years are masked (Y0 = the year the release was filed, Y-1 the year before, Y+1 the next). Report only "
    "what the text says; never guess or use outside knowledge of which company this is. Numbers: use the quarter just "
    "reported (not year-to-date) and the units the release states, converted to millions for revenue. Guidance: "
    "compare the company's outlook with its PREVIOUS outlook as the release describes it ('raises', 'reaffirms', "
    "'lowers', 'now expects … compared with … previously'). Use 'initiated' when it gives an outlook without a previous "
    "one to compare, 'mixed' when some items go up and others down, 'none' when there is no outlook. Tone (−2…+2): how "
    "good the quarter and outlook are for the company's value as presented, discounting routine boilerplate "
    "('record', 'strong momentum') unless the numbers back it.")

SCHEMA = {
    "type": "object",
    "properties": {
        "is_results_release": {"type": "boolean", "description": "true if this reports a completed quarter's or year's results"},
        "fiscal_period": {"type": "string", "description": "e.g. 'Q3 FY Y0' as written, with masked years"},
        "currency": {"type": "string", "description": "ISO code of the reported numbers, e.g. USD"},
        "revenue_millions": {"type": ["number", "null"], "description": "total revenue / net sales for the quarter, in millions"},
        "revenue_growth_pct": {"type": ["number", "null"], "description": "year-over-year revenue growth in percent, if stated or directly computable"},
        "eps_gaap": {"type": ["number", "null"], "description": "diluted GAAP EPS for the quarter (negative for a loss)"},
        "eps_adjusted": {"type": ["number", "null"], "description": "adjusted / non-GAAP diluted EPS for the quarter, if given"},
        "guidance": {"type": "string", "enum": GUIDANCE},
        "guidance_detail": {"type": "string", "description": "one sentence: what the outlook says and how it changed"},
        "tone": {"type": "integer", "minimum": -2, "maximum": 2},
        "one_offs": {"type": "string", "description": "unusual items that distort this quarter (charges, gains, acquisitions), or ''"},
        "positives": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
        "negatives": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
    },
    "required": ["is_results_release", "fiscal_period", "currency", "revenue_millions", "eps_gaap", "eps_adjusted",
                 "guidance", "guidance_detail", "tone", "one_offs", "positives", "negatives"],
}


def estimates(symbol: str, filed_at: date) -> dict:
    """Consensus estimates from the latest calendar snapshot taken on or before the filing day, for a report dated
    within 4 days of it (Finnhub has revenue estimates; either source for EPS)."""
    rows = query("""SELECT source, eps_estimate, revenue_estimate FROM earnings_calendar
                    WHERE symbol=%s AND as_of <= %s AND as_of >= %s - 10 AND report_date BETWEEN %s - 4 AND %s + 4
                    ORDER BY as_of DESC, (source = 'finnhub') DESC""", (symbol, filed_at, filed_at, filed_at, filed_at))
    eps = next((r["eps_estimate"] for r in rows if r["eps_estimate"] is not None), None)
    rev = next((r["revenue_estimate"] for r in rows if r["revenue_estimate"]), None)
    return {"eps_estimate": eps, "revenue_estimate": rev}


def surprises(a: dict, est: dict) -> tuple[float | None, float | None]:
    """EPS surprise vs |estimate| (adjusted EPS when given; skipped for tiny estimates) and revenue surprise (USD
    reporters only; a gap over 50% is treated as a unit mismatch, not a surprise)."""
    eps = a.get("eps_adjusted") if a.get("eps_adjusted") is not None else a.get("eps_gaap")
    e_s = r_s = None
    e = est.get("eps_estimate")
    if eps is not None and e is not None and abs(e) >= 0.02:
        x = (eps - e) / abs(e)
        e_s = x if abs(x) <= 5 else None
    rev, re_ = a.get("revenue_millions"), est.get("revenue_estimate")
    if rev and re_ and re_ > 0 and (a.get("currency") or "USD").upper() == "USD":
        x = rev * 1e6 / re_ - 1
        r_s = x if abs(x) <= 0.5 else None
    return e_s, r_s


def read_one(ev: dict, mode: str, task_id: int | None = None) -> str:
    """Read one release and store the result. Returns the status."""
    base = {"accession": ev["accession"], "symbol": ev["symbol"], "cik": ev["cik"], "accepted_at": ev["accepted_at"],
            "filed_at": ev["filed_at"], "mode": mode, "model": None}
    try:
        doc = pick_release(sec.filing_documents(ev["cik"], ev["accession"]))
    except Permanent as e:
        _store({**base, "status": "error", "error": f"index: {e}"[:300]})
        return "error"
    if not doc:
        _store({**base, "status": "no_release"})
        return "no_release"
    try:
        text = html_to_text(sec.get_text(doc["url"]))
    except Permanent as e:
        _store({**base, "status": "error", "doc_url": doc["url"], "error": f"doc: {e}"[:300]})
        return "error"
    masked = mask(text, ev.get("name") or "", ev["symbol"], ev["filed_at"].year)[:MAX_CHARS]
    mdl = model()
    ans = claude.ask("Earnings press release (masked):\n\n" + masked, model=mdl, purpose=f"earnings.read.{mode}",
                     schema=SCHEMA, system=SYSTEM, timeout=240, task_id=task_id)
    a = ans.data
    est = estimates(ev["symbol"], ev["filed_at"])
    e_s, r_s = surprises(a, est)
    g = a.get("revenue_growth_pct")
    _store({**base, "model": mdl, "status": "ok" if a.get("is_results_release") else "not_results",
            "doc_url": doc["url"], "chars": len(text), "fiscal_period": a.get("fiscal_period"),
            "currency": a.get("currency"), "revenue_musd": a.get("revenue_millions"),
            "revenue_yoy": g / 100 if g is not None else None, "eps_gaap": a.get("eps_gaap"),
            "eps_adj": a.get("eps_adjusted"), "guidance": a.get("guidance"), "guidance_detail": a.get("guidance_detail"),
            "tone": a.get("tone"), "one_offs": a.get("one_offs"), "positives": json.dumps(a.get("positives") or []),
            "negatives": json.dumps(a.get("negatives") or []), **est, "eps_surprise": e_s, "rev_surprise": r_s,
            "raw": json.dumps(a)})
    return "ok" if a.get("is_results_release") else "not_results"


COLS = ["accession", "symbol", "cik", "accepted_at", "filed_at", "mode", "model", "status", "doc_url", "chars",
        "fiscal_period", "currency", "revenue_musd", "revenue_yoy", "eps_gaap", "eps_adj", "guidance", "guidance_detail",
        "tone", "one_offs", "positives", "negatives", "eps_estimate", "revenue_estimate", "eps_surprise", "rev_surprise",
        "raw", "error"]


def _store(r: dict) -> None:
    vals = [r.get(c) for c in COLS]
    execute(f"""INSERT INTO earnings_reads ({', '.join(COLS)}) VALUES ({', '.join(['%s'] * len(COLS))})
                ON CONFLICT (accession) DO UPDATE SET {', '.join(f'{c}=EXCLUDED.{c}' for c in COLS[1:])}, read_at=now()""",
            vals)


# ── what to read ──────────────────────────────────────────────────────────────────────────────────────────────────

_EVENT_SQL = """SELECT e.accession, e.symbol, e.cik, e.accepted_at, e.filed_at, s.name
                FROM earnings_events e JOIN stocks s ON s.symbol = e.symbol
                LEFT JOIN earnings_reads r ON r.accession = e.accession
                CROSS JOIN LATERAL (SELECT avg(p.close * p.volume) adv, (array_agg(p.close ORDER BY p.date DESC))[1] px
                                    FROM (SELECT close, volume, date FROM daily_prices p
                                          WHERE p.symbol = e.symbol AND p.date < e.filed_at
                                          ORDER BY date DESC LIMIT 20) p) l
                WHERE r.accession IS NULL AND l.adv >= %s AND l.px >= %s AND {where}
                ORDER BY {order} LIMIT %s"""


def pending_live(limit: int) -> list[dict]:
    return query(_EVENT_SQL.format(where="e.filed_at >= current_date - %s", order="e.accepted_at DESC NULLS LAST"),
                 (MIN_ADV, MIN_PRICE, LIVE_DAYS, limit))


def pending_history(limit: int) -> list[dict]:
    # fixed random order (md5 of the accession) → any partial fill is an even sample across 2016–today
    return query(_EVENT_SQL.format(where="e.filed_at >= '2016-01-01' AND e.filed_at < current_date - %s",
                                   order="md5(e.accession)"), (MIN_ADV, MIN_PRICE, LIVE_DAYS, limit))


def _locked(key: int, fn):
    import psycopg
    with psycopg.connect(settings()["database"]["dsn"], autocommit=True) as lock:   # held for the whole run
        if not lock.execute("SELECT pg_try_advisory_lock(%s)", (key,)).fetchone()[0]:
            return {"summary": None, "skipped": "already running"}
        return fn()


def _read_batch(ctx: TaskContext, items: list[dict], mode: str) -> dict:
    counts: dict[str, int] = {}
    for i, ev in enumerate(items):
        st = read_one(ev, mode, ctx.id)
        counts[st] = counts.get(st, 0) + 1
        ctx.checkpoint(done=i + 1, of=len(items), **counts)
    return counts


@task("sec.earnings_poll", resource="sec", priority=64,
      description="Live EDGAR 8-K feed: find earnings releases (item 2.02) minutes after filing")
def earnings_poll(ctx: TaskContext) -> dict:
    ours = {r["cik"] for r in query("SELECT DISTINCT cik FROM stocks WHERE is_universe AND cik IS NOT NULL")}
    known = set()
    new = []
    stop_before = datetime.now().astimezone() - timedelta(hours=int(ctx.payload.get("hours", 30)))
    for page in range(int(ctx.payload.get("max_pages", 8))):
        rows = sec.current_filings("8-K", start=page * 100)
        if not rows:
            break
        accs = [r["accession"] for r in rows]
        known |= {r["accession"] for r in query("SELECT accession FROM filings WHERE accession = ANY(%s)", (accs,))}
        for r in rows:
            if r["cik"] in ours and r["items"] and "2.02" in r["items"] and r["accession"] not in known:
                new.append(r)
                known.add(r["accession"])
        oldest = min((datetime.fromisoformat(r["accepted_at"]) for r in rows if r["accepted_at"]), default=None)
        if oldest is None or oldest < stop_before:
            break
    if new:
        with conn() as c, c.cursor() as cur:
            cur.executemany("""INSERT INTO filings (accession, cik, form, filed_at, accepted_at, items)
                               VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (accession) DO NOTHING""",
                            [(r["accession"], r["cik"], r["form"], r["filed_at"], r["accepted_at"], r["items"]) for r in new])
    if pending_live(1):
        queue.enqueue("earnings.read", {}, priority=63, resource=claude.resource(model()), dedupe_key="earnings.read")
    return {"summary": f"EDGAR live feed: {len(new)} new earnings releases" if new else None, "new": len(new)}


@task("earnings.read", resource="claude:haiku", priority=63,
      description="Claude reads new earnings press releases: guidance, tone, numbers; surprise vs estimates")
def read_live(ctx: TaskContext) -> dict:
    def run():
        items = pending_live(int(ctx.payload.get("max_items", 300)))
        c = _read_batch(ctx, items, "live")
        return {"summary": f"earnings releases read: {sum(c.values())} ({c})" if items else None, **c}
    return _locked(424301, run)


@task("earnings.read_history", resource="claude:haiku", priority=18,
      description="Past earnings releases (2016+), a slow random-order backfill in spare capacity")
def read_history(ctx: TaskContext) -> dict:
    def run():
        items = pending_history(int(ctx.payload.get("max_items", 20)))
        c = _read_batch(ctx, items, "history")
        left = query("SELECT count(*) n FROM earnings_events e LEFT JOIN earnings_reads r USING (accession) "
                     "WHERE r.accession IS NULL AND e.filed_at >= '2016-01-01'")[0]["n"]
        return {"summary": f"history earnings reads: {sum(c.values())} ({c}); ≤{left:,} releases unread", **c}
    return _locked(424302, run)


def coverage() -> list[dict]:
    """Reads per year and mode (for the CLI / dashboard)."""
    return query("""SELECT extract(year FROM filed_at)::int AS year, mode, status, count(*) n
                    FROM earnings_reads GROUP BY 1, 2, 3 ORDER BY 1, 2, 3""")


if __name__ == "__main__":       # quick manual check: python -m core.jobs.earnings_reads ACCESSION
    import sys
    ev = query("SELECT e.accession, e.symbol, e.cik, e.accepted_at, e.filed_at, s.name FROM earnings_events e "
               "JOIN stocks s ON s.symbol = e.symbol WHERE e.accession = %s", (sys.argv[1],))[0]
    print(read_one(ev, "live" if ev["filed_at"] >= date.today() - timedelta(days=LIVE_DAYS) else "history"))
    print(json.dumps(query("SELECT * FROM earnings_reads WHERE accession=%s", (sys.argv[1],))[0], default=str, indent=1))
