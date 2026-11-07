"""The market pack (architecture §5.5): a compact, organized document of everything that happened, for Opus to read.
Python does the heavy lifting (5,000 stocks → tables); Opus does the understanding."""
from __future__ import annotations

from datetime import date, timedelta

from core.db import query
from core.market.macro_view import macro_table


def _p(v, nd=1):
    return "—" if v is None else f"{v * 100:+.{nd}f}%"


def _table(head: list[str], rows: list[list]) -> str:
    if not rows:
        return "(none)\n"
    return ("| " + " | ".join(head) + " |\n|" + "---|" * len(head) + "\n"
            + "\n".join("| " + " | ".join(str(c) for c in r) + " |" for r in rows) + "\n")


def build(day: date | None = None) -> tuple[date, str]:
    snap_row = query("SELECT date, data FROM market_snapshot " + ("WHERE date <= %s " if day else "") +
                     "ORDER BY date DESC LIMIT 1", (day,) if day else None)
    if not snap_row:
        raise RuntimeError("no market snapshot yet")
    day, s = snap_row[0]["date"], snap_row[0]["data"]
    hist = query("""SELECT date, regime, exposure, (data->'breadth'->>'pct_above_200d')::float a200,
                           (data->'breadth'->>'pct_above_50d')::float a50 FROM market_snapshot
                    WHERE date <= %s ORDER BY date DESC LIMIT 21""", (day,))
    out = [f"# Market pack for {day} (US stocks; numbers computed by our system)\n"]
    out.append(f"**Regime (rule-based):** {s['regime']}. Exposure dial suggests {s['exposure']:.0%} invested.\n")
    b = s.get("breadth") or {}
    out.append("## Breadth (stocks trading ≥ $1M/day)\n")
    rows = [[h["date"], f"{(h['a200'] or 0):.0%}", f"{(h['a50'] or 0):.0%}", f"{h['exposure']:.0%}"] for h in hist[:1] + hist[5:6] + hist[20:21]]
    out.append(_table(["Date", "% above 200-day", "% above 50-day", "Exposure dial"], rows))
    out.append(f"Today: {b.get('advancers')} up / {b.get('decliners')} down; median stock {_p(b.get('median_ret_1d'))} today, "
               f"{_p(b.get('median_ret_20d'))} over 20 days; {b.get('near_52w_high')} near 52-week highs, {b.get('near_52w_low')} near lows.\n")

    def grp(name, title):
        rows = [[r["symbol"], r["name"], _p(r.get("ret_1d")), _p(r.get("ret_5d")), _p(r.get("ret_20d")), _p(r.get("ret_60d")),
                 _p(r.get("rel_20d")), r.get("quadrant") or ""] for r in s["groups"].get(name, [])]
        return f"## {title}\n" + _table(["ETF", "What", "Day", "Week", "Month", "3 months", "vs SPY month", "Rotation"], rows)

    for g, t in (("index", "Indexes"), ("style", "Styles"), ("sector", "Sectors"), ("theme", "Themes"),
                 ("rates_credit", "Bonds and credit"), ("commodity_fx", "Commodities, dollar, bitcoin, fear gauge"),
                 ("global", "World markets")):
        out.append(grp(g, t))
    sig = s.get("signals") or {}
    out.append("## Risk signals (spreads, ~1 month)\n" + _table(["Signal", "Value"], [[k, _p(v)] for k, v in sig.items()]))
    out.append("## Inside sectors (median stock)\n" + _table(
        ["Sector", "Stocks", "Month", "3 months", "% above 50-day", "Avg RS rank"],
        [[r["sector"], r["stocks"], _p(r["median_ret_20d"]), _p(r["median_ret_60d"]),
          f"{(r['pct_above_50d'] or 0):.0%}", r["avg_rs_rank"]] for r in s.get("sectors", [])]))

    mac = macro_table()
    out.append("## Economy (FRED; 'before' = a month earlier for daily data, else previous release)\n" + _table(
        ["Measure", "Date", "Latest", "Before", "Year ago"],
        [[r["label"], r["date"], _fmt(r, r["value"]), _fmt(r, r["prev"]), _fmt(r, r["year_ago"])] for r in mac]))

    since = day - timedelta(days=1)
    movers = query("""
        WITH m AS (SELECT f.symbol, s.sector, f.ret_1d, f.rvol, f.market_cap FROM features_daily f
                   JOIN stocks s ON s.symbol = f.symbol AND s.is_universe AND s.asset_type = 'common'
                   WHERE f.date = %s AND f.adv20 >= 10000000 AND f.ret_1d IS NOT NULL),
             top AS ((SELECT * FROM m ORDER BY ret_1d DESC LIMIT 15) UNION ALL (SELECT * FROM m ORDER BY ret_1d ASC LIMIT 15))
        SELECT top.*, (SELECT n.headline FROM news_events e JOIN news n ON n.id = e.news_id
                       WHERE e.symbol = top.symbol AND e.created_at >= %s::date - 1 AND e.created_at < %s::date + 1
                       ORDER BY e.importance DESC, e.created_at DESC LIMIT 1) AS why
        FROM top ORDER BY ret_1d DESC""", (day, day, day))
    out.append("## Biggest movers today (stocks trading ≥ $10M/day) with their most important news\n" + _table(
        ["Stock", "Sector", "Day", "Rel. volume", "Mkt cap $B", "Top news"],
        [[r["symbol"], r["sector"], _p(r["ret_1d"]), f"{r['rvol'] or 0:.1f}×",
          f"{(r['market_cap'] or 0) / 1e9:.0f}", (r["why"] or "(no labeled news)")[:140]] for r in movers]))

    major = query("""SELECT e.symbol, e.event_type, e.direction, e.importance, n.headline FROM news_events e
                     JOIN news n ON n.id = e.news_id JOIN news_ai a ON a.news_id = e.news_id
                     WHERE e.created_at >= %s AND e.created_at < %s::date + 1 AND e.importance >= 4 AND NOT coalesce(a.recap, false)
                     ORDER BY e.importance DESC, abs(e.direction) DESC, e.created_at DESC LIMIT 40""", (since, day))
    out.append("## Major company news (importance 4–5, last trading day)\n" + _table(
        ["Stock", "Event", "Effect", "Importance", "Headline"],
        [[r["symbol"], r["event_type"], f"{r['direction']:+d}", r["importance"], r["headline"][:150]] for r in major]))

    macro_news = query("""SELECT a.topic, n.headline FROM news_ai a JOIN news n ON n.id = a.news_id
                          WHERE a.topic IN ('macro_policy', 'sector_industry') AND n.created_at >= %s AND n.created_at < %s::date + 1
                          ORDER BY n.created_at DESC LIMIT 30""", (since, day))
    out.append("## Economy, policy and industry headlines\n" + "".join(f"- [{r['topic']}] {r['headline'][:170]}\n" for r in macro_news) or "(none)\n")

    leaders = s.get("leaders") or []
    out.append("## Leaders (liquid uptrends near 52-week highs, strongest first)\n" + _table(
        ["Stock", "Sector", "Month", "3 months", "RS rank"],
        [[r["symbol"], r["sector"], _p(r.get("ret_20d")), _p(r.get("ret_60d")), r.get("rs_rank")] for r in leaders[:15]]))

    earn = query("""SELECT u.symbol, u.report_date, u.time_of_day, f.market_cap FROM upcoming_earnings u
                    JOIN features_daily f ON f.symbol = u.symbol AND f.date = %s
                    WHERE u.report_date <= %s::date + 8 AND f.market_cap >= 20e9 ORDER BY u.report_date, f.market_cap DESC LIMIT 40""",
                 (day, day))
    out.append("## Big companies reporting earnings in the next ~week\n" + _table(
        ["Stock", "Date", "When", "Mkt cap $B"],
        [[r["symbol"], r["report_date"], r["time_of_day"] or "", f"{(r['market_cap'] or 0) / 1e9:.0f}"] for r in earn]))

    journal = query("SELECT date, summary FROM market_journal WHERE date < %s ORDER BY date DESC LIMIT 5", (day,))
    out.append("## Our recent daily summaries (oldest first)\n" + ("".join(f"**{r['date']}:** {r['summary']}\n\n" for r in reversed(journal)) or "(none yet: this is the first)\n"))

    preds = query("""SELECT id, made_on, statement, probability, horizon_days, status, outcome FROM predictions
                     WHERE status = 'open' OR resolved_on >= %s::date - 7 ORDER BY made_on DESC LIMIT 30""", (day,))
    out.append("## Our predictions (open, and recently scored)\n" + _table(
        ["#", "Made", "Prediction", "Prob.", "Days", "Status", "Outcome"],
        [[r["id"], r["made_on"], r["statement"][:120], f"{r['probability']:.0%}", r["horizon_days"], r["status"],
          _p(r["outcome"]) if r["outcome"] is not None else ""] for r in preds]))
    return day, "\n".join(out)


def _fmt(r, v):
    if v is None:
        return "—"
    if r["unit"] == "%":
        return f"{v:.2f}%"
    if r["unit"] == "k":
        return f"{v:,.0f}k"
    return f"{v:,.2f}" if abs(v) < 100 else f"{v:,.0f}"
