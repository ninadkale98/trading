"""SEC EDGAR client. Free, no account; requires a name + email header (SEC_USER_AGENT in .env)
and ≤ 10 requests/second."""
from __future__ import annotations

import httpx

from core.config import secret, settings
from core.ingest.http import RateLimiter, request

_limiter = RateLimiter(settings()["sec"]["requests_per_second"], "sec")
_client: httpx.Client | None = None
RESOURCE = "sec"


def client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(timeout=httpx.Timeout(60.0, connect=15.0),
                               headers={"User-Agent": secret("SEC_USER_AGENT"), "Accept-Encoding": "gzip, deflate"})
    return _client


def get_json(url: str) -> dict:
    return request(client(), _limiter, RESOURCE, "GET", url).json()


def get_text(url: str) -> str:
    return request(client(), _limiter, RESOURCE, "GET", url).text


def company_tickers() -> list[dict]:
    d = get_json("https://www.sec.gov/files/company_tickers_exchange.json")
    return [dict(zip(d["fields"], row)) for row in d["data"]]


def submissions(cik: int) -> dict:
    return get_json(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")


def company_facts(cik: int) -> dict:
    return get_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json")


def current_filings(form: str = "8-K", start: int = 0, count: int = 100) -> list[dict]:
    """EDGAR's live list of the newest filings (updated within minutes; the daily index only appears late at night).
    Each: accession, cik, form, filed_at (date str), accepted_at (ISO with offset), items ("2.02,9.01")."""
    import html as _html
    import re
    text = get_text("https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=" + form +
                    f"&company=&dateb=&owner=include&start={start}&count={count}&output=atom")
    out = []
    for e in re.findall(r"<entry>(.*?)</entry>", text, re.S):
        title = re.search(r"<title>(.*?)</title>", e, re.S)
        acc = re.search(r"accession-number=([\d-]+)", e)
        cik = re.search(r"\((\d{10})\)", title.group(1) if title else "")
        if not (title and acc and cik):
            continue
        summ = _html.unescape(re.search(r"<summary[^>]*>(.*?)</summary>", e, re.S).group(1)) if "<summary" in e else ""
        filed = re.search(r"Filed:</b>\s*(\d{4}-\d{2}-\d{2})", summ)
        upd = re.search(r"<updated>(.*?)</updated>", e)
        out.append({"accession": acc.group(1), "cik": int(cik.group(1)), "form": title.group(1).split(" - ")[0].strip(),
                    "filed_at": filed.group(1) if filed else None, "accepted_at": upd.group(1) if upd else None,
                    "items": ",".join(re.findall(r"Item (\d+\.\d+)", summ)) or None})
    return out


def filing_documents(cik: int, accession: str) -> list[dict]:
    """The documents inside one filing (from its index page): seq, description, type (e.g. EX-99.1), url."""
    import re
    nod = accession.replace("-", "")
    page = get_text(f"https://www.sec.gov/Archives/edgar/data/{cik}/{nod}/{accession}-index.htm")
    docs = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S | re.I):
        cells = [re.sub(r"<[^>]+>", "", c).replace("&nbsp;", " ").strip()
                 for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S | re.I)]
        href = re.search(r'href="([^"]+)"', row)
        if len(cells) >= 4 and href:
            url = href.group(1).replace("/ix?doc=", "")
            docs.append({"seq": cells[0], "description": cells[1], "type": cells[3].upper(),
                         "url": "https://www.sec.gov" + url if url.startswith("/") else url})
    return docs
