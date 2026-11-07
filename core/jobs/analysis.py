"""Daily market analysis by Opus (re-plan step B, architecture §17) and automatic scoring of predictions (§5.5)."""
from __future__ import annotations

from datetime import date

from core.ai import claude
from core.ai.market_pack import build
from core.config import ROOT
from core.db import conn, query
from core.tasks.registry import TaskContext, task

SYSTEM = """You are the market analyst of a personal research system. Every evening you read a "market pack" (numbers our
system computed from ~5,400 US stocks, 65 ETFs, FRED economic data and AI-labeled news) and write the daily market
analysis. Your reader is learning investing: write in plain language, explain every technical term the first time
(one short clause), and use real numbers from the pack.

Rules:
- Explain WHY things moved, with evidence (news in the pack, macro data, sector moves). Say clearly what is fact and
  what is your interpretation. If the cause is unclear, say so. You may use web search to check a cause.
- Connect today to the bigger story (recent summaries, rotation, breadth, rates, credit).
- Give no personal buy/sell advice. Describe both sides.
- Predictions: make 2–5 that a computer can check, about things where you have a view (sector/theme ETFs vs SPY,
  big stocks vs SPY, or a symbol's own move over 5–60 trading days). Use honest probabilities (most should be
  55–70%; above 80% only for near-certainties). Avoid repeating open predictions. Each needs one line of reasoning.
- Keep the analysis to about 700–1,000 words with these sections:
  1. What happened  2. Where money moved  3. The story so far  4. What to watch  5. Lesson of the day"""

SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "3–5 sentences: what today meant, for the journal"},
        "analysis_markdown": {"type": "string"},
        "watch": {"type": "array", "items": {"type": "string"}},
        "lesson": {"type": "object", "properties": {"term": {"type": "string"}, "explanation": {"type": "string"}},
                   "required": ["term", "explanation"]},
        "predictions": {"type": "array", "items": {"type": "object", "properties": {
            "kind": {"type": "string", "enum": ["outperform", "move"]},
            "symbol": {"type": "string"},
            "benchmark": {"type": "string", "description": "for outperform; usually SPY"},
            "direction": {"type": "string", "enum": ["up", "down"]},
            "threshold": {"type": "number", "description": "for move: minimum absolute return as a fraction, e.g. 0.03"},
            "horizon_days": {"type": "integer", "minimum": 5, "maximum": 60},
            "probability": {"type": "number", "minimum": 0.5, "maximum": 0.95},
            "statement": {"type": "string"},
            "reasoning": {"type": "string"}},
            "required": ["kind", "symbol", "direction", "horizon_days", "probability", "statement", "reasoning"]}},
    },
    "required": ["summary", "analysis_markdown", "watch", "lesson", "predictions"],
}


def _close(symbol: str, day) -> float | None:
    r = query("SELECT close * adj_factor c FROM daily_prices WHERE symbol=%s AND date <= %s ORDER BY date DESC LIMIT 1",
              (symbol, day))
    return float(r[0]["c"]) if r else None


@task("ai.market_analysis", resource="claude:opus", priority=70, description="Opus writes the daily market analysis and predictions")
def market_analysis(ctx: TaskContext) -> dict:
    day, pack = build(date.fromisoformat(ctx.payload["day"]) if ctx.payload.get("day") else None)
    ans = claude.ask(f"Here is today's market pack.\n\n{pack}\n\nWrite today's analysis.", model="opus",
                     purpose="ai.market_analysis", schema=SCHEMA, system=SYSTEM, tools=["WebSearch"], timeout=1200,
                     task_id=ctx.id)
    d = ans.data
    kept, dropped = 0, []
    with conn() as c:
        c.execute("""INSERT INTO market_journal (date, model, summary, analysis_md, lesson, watch, pack_chars)
                     VALUES (%s, 'opus', %s, %s, %s, %s, %s)
                     ON CONFLICT (date) DO UPDATE SET summary=EXCLUDED.summary, analysis_md=EXCLUDED.analysis_md,
                       lesson=EXCLUDED.lesson, watch=EXCLUDED.watch, pack_chars=EXCLUDED.pack_chars, created_at=now()""",
                  (day, d["summary"], d["analysis_markdown"],
                   _json(d.get("lesson")), _json(d.get("watch")), len(pack)))
        c.execute("DELETE FROM predictions WHERE made_on=%s AND source='opus.market_analysis' AND status='open'", (day,))
        for p in d.get("predictions", [])[:6]:
            sym = p["symbol"].upper().strip()
            bench = (p.get("benchmark") or "SPY").upper().strip() if p["kind"] == "outperform" else None
            sp, bp = _close(sym, day), (_close(bench, day) if bench else None)
            if sp is None or (bench and bp is None):
                dropped.append(sym)
                continue
            c.execute("""INSERT INTO predictions (made_on, source, kind, symbol, benchmark, direction, threshold, horizon_days,
                                                  probability, statement, reasoning, start_price, start_bench)
                         VALUES (%s,'opus.market_analysis',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                      (day, p["kind"], sym, bench, p["direction"], float(p.get("threshold") or 0), int(p["horizon_days"]),
                       float(p["probability"]), p["statement"], p.get("reasoning"), sp, bp))
            kept += 1
    path = ROOT / "reports" / "market" / f"{day}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# Daily market analysis: {day}\n\n> {d['summary']}\n\n{d['analysis_markdown']}\n\n"
                    + "## Predictions\n" + "".join(f"- {p['statement']} ({p['probability']:.0%}, {p['horizon_days']} trading days): "
                                                   f"{p.get('reasoning', '')}\n" for p in d.get("predictions", []))
                    + "\n*Written by Opus from our market pack. Not financial advice.*\n")
    return {"summary": f"market analysis for {day} written ({len(d['analysis_markdown'].split())} words, {kept} predictions"
                       + (f"; dropped unknown symbols {dropped}" if dropped else "") + ")",
            "date": str(day), "predictions": kept, "cost_equiv": ans.cost}


def _json(v):
    import json
    return json.dumps(v) if v is not None else None


@task("predictions.score", priority=56, description="Score predictions whose time is up")
def score(ctx: TaskContext) -> dict:
    right = wrong = void = 0
    for p in query("SELECT * FROM predictions WHERE status='open' ORDER BY made_on"):
        days = query("SELECT date FROM daily_prices WHERE symbol='SPY' AND date > %s ORDER BY date LIMIT %s",
                     (p["made_on"], p["horizon_days"]))
        if len(days) < p["horizon_days"]:
            continue                                    # not due yet
        end = days[-1]["date"]
        sp = query("SELECT close * adj_factor c FROM daily_prices WHERE symbol=%s AND date=%s", (p["symbol"], end))
        if not sp or not p["start_price"]:
            query("UPDATE predictions SET status='void', resolved_on=%s WHERE id=%s RETURNING id", (end, p["id"]))
            void += 1
            continue
        r = float(sp[0]["c"]) / p["start_price"] - 1
        if p["kind"] == "outperform":
            bp = query("SELECT close * adj_factor c FROM daily_prices WHERE symbol=%s AND date=%s", (p["benchmark"], end))
            if not bp or not p["start_bench"]:
                query("UPDATE predictions SET status='void', resolved_on=%s WHERE id=%s RETURNING id", (end, p["id"]))
                void += 1
                continue
            r -= float(bp[0]["c"]) / p["start_bench"] - 1
        ok = r > p["threshold"] if p["direction"] == "up" else r < -p["threshold"]
        query("UPDATE predictions SET status=%s, outcome=%s, resolved_on=%s WHERE id=%s RETURNING id",
              ("right" if ok else "wrong", r, end, p["id"]))
        right, wrong = right + ok, wrong + (not ok)
    stats = query("""SELECT count(*) n, avg((status='right')::int) hit, avg(probability) conf FROM predictions
                     WHERE status IN ('right','wrong')""")[0]
    return {"summary": f"predictions scored today: {right} right, {wrong} wrong, {void} void; all-time "
                       f"{stats['n']} scored, hit rate {(stats['hit'] or 0):.0%} vs stated confidence {(stats['conf'] or 0):.0%}",
            "right": right, "wrong": wrong}

