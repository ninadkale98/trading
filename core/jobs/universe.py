"""Universe: every Alpaca listing (active + delisted), classified; ~5,000 common stocks flagged as our universe.
Architecture §3. SEC's official ticker list is used to confirm real operating companies."""
from __future__ import annotations

import json
import re
from collections import Counter

from core.config import settings
from core.db import conn
from core.ingest import alpaca, sec
from core.tasks.registry import TaskContext, task

MAIN_EXCHANGES = {"NASDAQ", "NYSE", "AMEX", "ARCA", "BATS"}
_PATTERNS = [
    ("warrant", re.compile(r"\bwarrants?\b|\bwts?\b", re.I)),
    ("unit", re.compile(r"\bunits?\b", re.I)),
    ("right", re.compile(r"\brights?\b", re.I)),
    ("preferred", re.compile(r"preferred|preference|\bpfd\b|\bprf\b|depositary shares? \(?(each )?(1/\d+|represent)|% series|"
                             r"perpetual|floating rate|non[- ]?cum", re.I)),
    ("spac", re.compile(r"acquisition corp|acquisition company|acquisition co\b|acquisition ltd|blank check|\bspac\b", re.I)),
    ("special", re.compile(r"tender offer|dividend security|contingent value|\bcvr\b|escrow|liquidating trust", re.I)),
    ("debt", re.compile(r"\bnotes? due\b|\bnotes?\b \d|debentures?|\bbonds?\b|% senior|subordinated", re.I)),
    ("etf", re.compile(r"\betfs?\b|\betn\b|index fund|\bishares\b|\bspdr\b|proshares|direxion|exchange[- ]traded|"
                       r"\bfund\b|\bportfolio\b|\bstrategy shares\b|\bbitcoin trust\b|\bether trust\b", re.I)),
]


def sec_symbol(alpaca_symbol: str) -> str:
    return alpaca_symbol.replace(".", "-").replace("/", "-")


def classify(a: dict, sec_row: dict | None) -> str:
    name = a.get("name") or ""
    sym = a["symbol"]
    if a.get("exchange") not in MAIN_EXCHANGES:
        return "otc"
    for kind, rx in _PATTERNS:
        if rx.search(name):
            return kind
    if sec_row and re.search(r"-P[A-Z]?$|-P$", sec_row["ticker"]):
        return "preferred"
    if re.search(r"\.(U|WS|W|R)$|\.P[A-Z]?$", sym):
        return {"U": "unit", "WS": "warrant", "W": "warrant", "R": "right"}.get(sym.rsplit(".", 1)[1], "preferred")
    if re.search(r"\.PR[A-Z]?$", sym):
        return "preferred"
    if not name.strip() or not re.fullmatch(r"[A-Z]{1,5}(\.[A-Z])?", sym):
        return "other"             # blank names / odd symbols (test, temporary or special securities)
    if sec_row and sec_row.get("exchange") in ("Nasdaq", "NYSE", "CBOE"):
        return "common"
    if a.get("exchange") in {"NASDAQ", "NYSE", "AMEX"}:
        return "common"            # real company stock not (or no longer) on SEC's ticker list, incl. delisted names
    if a.get("exchange") in {"ARCA", "BATS"}:
        return "etf"               # funds dominate these exchanges and most aren't in SEC's company list
    return "other"


@task("universe.refresh", resource="alpaca", priority=80, description="Refresh the list of all stocks and our universe")
def refresh(ctx: TaskContext) -> dict:
    sec_rows = {r["ticker"]: r for r in sec.company_tickers()}
    refs = set(settings()["data"]["reference_symbols"])
    kinds: Counter = Counter()
    universe = 0
    with conn() as c:
        for status in ("active", "inactive"):
            for a in alpaca.assets(status):
                if a.get("class") != "us_equity":
                    continue
                srow = sec_rows.get(sec_symbol(a["symbol"])) if status == "active" else None
                kind = classify(a, srow)
                if a["symbol"] in refs and kind != "common":
                    kind = "etf"
                is_universe = status == "active" and bool(a.get("tradable")) and (
                    kind == "common" or a["symbol"] in refs)
                kinds[(status, kind)] += 1
                universe += is_universe
                c.execute(
                    """INSERT INTO stocks (alpaca_id, symbol, name, exchange, status, tradable, asset_type, is_universe, cik, attributes,
                                           delisted_seen)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, CASE WHEN %s = 'inactive' THEN now() END)
                       ON CONFLICT (alpaca_id) DO UPDATE SET symbol=EXCLUDED.symbol, name=EXCLUDED.name, exchange=EXCLUDED.exchange,
                         status=EXCLUDED.status, tradable=EXCLUDED.tradable, asset_type=EXCLUDED.asset_type,
                         is_universe=EXCLUDED.is_universe, cik=COALESCE(EXCLUDED.cik, stocks.cik), attributes=EXCLUDED.attributes,
                         last_seen=now(), updated_at=now(),
                         delisted_seen=CASE WHEN EXCLUDED.status='inactive' THEN COALESCE(stocks.delisted_seen, now()) ELSE NULL END""",
                    (a["id"], a["symbol"], a.get("name"), a.get("exchange"), status, a.get("tradable"), kind, is_universe,
                     srow["cik"] if srow else None, json.dumps(a.get("attributes") or []), status),
                )
    active_common = kinds[("active", "common")]
    delisted_common = kinds[("inactive", "common")]
    return {
        "summary": f"universe: {universe} stocks ({active_common} active common + reference ETFs); {delisted_common} delisted common stocks kept for backtests",
        "universe": universe, "counts": {f"{s}:{k}": n for (s, k), n in sorted(kinds.items())},
    }
