"""News understanding with Haiku (re-plan step A, build plan 3.2).

Every headline (plus the start of its summary) is read in batches of ~100. For each item Haiku says which of the
tagged companies it really affects, what kind of event it is, whether it's good or bad for that company (−2…+2),
and how important (1–5). Price-move recaps ("X shares fall 5%") are flagged: they report a move, not new information.
Results go to `news_events` / `news_ai`; daily per-stock news features are built from them.
"""
from __future__ import annotations

from core.ai import claude
from core.db import conn, query
from core.tasks.registry import TaskContext, task

EVENTS = ["earnings_result", "guidance", "analyst_rating", "price_target", "merger_acquisition", "contract_partnership",
          "product", "regulatory_legal", "management", "dividend_buyback", "share_offering", "insider_trade",
          "macro_policy", "sector_industry", "market_recap", "earnings_date_notice", "other"]

SYSTEM = ("You label financial news for a stock research database. For each item decide which of its tagged companies "
          "it is really ABOUT (ignore companies only mentioned in passing), the event type, the likely effect on that "
          "company's value (direction −2 very negative … +2 very positive; 0 neutral or unclear) and importance "
          "(1 trivial … 5 could change the company's value a lot, e.g. guidance cut, big acquisition, FDA decision). "
          "Mark recap=true when the item mainly reports a stock-price move without new information. "
          "For items about no specific company, return no companies and set topic (macro_policy, sector_industry, "
          "market_recap or other). Judge only from the text given.")

SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "id": {"type": "integer"},
            "recap": {"type": "boolean"},
            "topic": {"type": "string", "enum": EVENTS},
            "companies": {"type": "array", "items": {
                "type": "object",
                "properties": {"symbol": {"type": "string"}, "event": {"type": "string", "enum": EVENTS},
                               "direction": {"type": "integer", "minimum": -2, "maximum": 2},
                               "importance": {"type": "integer", "minimum": 1, "maximum": 5}},
                "required": ["symbol", "event", "direction", "importance"]}},
        },
        "required": ["id", "recap", "companies"]}}},
    "required": ["items"],
}

BATCH = 100


def pending(limit: int, days: int) -> list[dict]:
    return query("""SELECT n.id, n.created_at, n.headline, left(coalesce(n.summary, ''), 220) summary, n.symbols
                    FROM news n LEFT JOIN news_ai a ON a.news_id = n.id
                    WHERE a.news_id IS NULL AND n.created_at > now() - make_interval(days => %s)
                      AND n.n_symbols <= 6
                    ORDER BY n.created_at DESC LIMIT %s""", (days, limit))


def label(batch: list[dict], task_id: int | None = None) -> int:
    lines = []
    for r in batch:
        syms = ",".join(r["symbols"]) or "-"
        summ = " ".join((r["summary"] or "").split())
        lines.append(f"{r['id']} | {syms} | {r['headline']}" + (f" | {summ}" if summ and summ != r["headline"] else ""))
    prompt = ("Label each news item (format: id | tagged symbols | headline | summary start).\n\n" + "\n".join(lines))
    ans = claude.ask(prompt, model="haiku", purpose="news.triage", schema=SCHEMA, system=SYSTEM, timeout=240, task_id=task_id)
    by_id = {r["id"]: r for r in batch}
    n_events = 0
    with conn() as c, c.cursor() as cur:
        seen = set()
        for it in ans.data.get("items", []):
            r = by_id.get(it.get("id"))
            if r is None or r["id"] in seen:
                continue
            seen.add(r["id"])
            cur.execute("INSERT INTO news_ai (news_id, model, recap, topic) VALUES (%s, 'haiku', %s, %s) ON CONFLICT DO NOTHING",
                        (r["id"], bool(it.get("recap")), it.get("topic")))
            tagged = set(r["symbols"])
            for co in it.get("companies", []):
                sym = (co.get("symbol") or "").upper()
                if sym not in tagged:          # only companies the news source tagged (no invented tickers)
                    continue
                cur.execute("""INSERT INTO news_events (news_id, symbol, event_type, direction, importance, created_at)
                               VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                            (r["id"], sym, co["event"], int(co["direction"]), int(co["importance"]), r["created_at"]))
                n_events += 1
        # items the model skipped stay unprocessed and are retried in the next run
    return n_events


@task("news.triage", resource="claude:haiku", priority=62, description="Haiku reads new headlines: company, event, direction, importance")
def triage(ctx: TaskContext) -> dict:
    max_items = int(ctx.payload.get("max_items", 2000))
    days = int(ctx.payload.get("days", 3))
    items = pending(max_items, days)
    done = events = 0
    for i in range(0, len(items), BATCH):
        events += label(items[i:i + BATCH], ctx.id)
        done += len(items[i:i + BATCH])
        ctx.checkpoint(done=done, events=events)
    left = query("""SELECT count(*) n FROM news n LEFT JOIN news_ai a ON a.news_id = n.id
                    WHERE a.news_id IS NULL AND n.created_at > now() - make_interval(days => %s) AND n.n_symbols <= 6""",
                 (days,))[0]["n"]
    return {"summary": f"news read by Haiku: {done:,} items → {events:,} company events; {left:,} still waiting",
            "items": done, "events": events, "waiting": left}
