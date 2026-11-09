"""Daily briefing (architecture §17): the user's 10–15 minute read, published 9:30 pm ET (dashboard Review page and
reports/daily/YYYY-MM-DD.md). Built from data the system already produced; Opus's analysis supplies the story."""
from __future__ import annotations

from core.config import ROOT
from core.db import query
from core.execution.run import mode
from core.tasks.registry import TaskContext, task


def _p(v, nd=1):
    return "—" if v is None else f"{v * 100:+.{nd}f}%"


def build(day=None) -> tuple[str, str]:
    day = day or query("SELECT max(date) d FROM market_snapshot")[0]["d"]
    snap = query("SELECT regime, exposure, data FROM market_snapshot WHERE date=%s", (day,))[0]
    j = query("SELECT summary, watch, lesson FROM market_journal WHERE date=%s", (day,))
    md_ = mode()
    spy = query("""SELECT (data->'groups'->'index'->0->>'ret_1d')::float r1 FROM market_snapshot WHERE date=%s""", (day,))[0]["r1"]
    book = query("""SELECT b.*, p.close AS last FROM positions_book b
                    LEFT JOIN LATERAL (SELECT close, adj_factor FROM daily_prices WHERE symbol=b.symbol AND date<=%s
                                       ORDER BY date DESC LIMIT 1) p ON true
                    WHERE b.mode=%s AND b.status='open' ORDER BY b.entry_date""", (day, md_))
    closed = query("SELECT * FROM positions_book WHERE mode=%s AND status='closed' AND exit_date=%s", (md_, day))
    plans = query("""SELECT * FROM trade_plans WHERE signal_date=%s AND mode=%s ORDER BY side DESC, strategy""", (day, md_))
    appr = query("SELECT * FROM approvals WHERE status='pending' ORDER BY deadline")
    news_n = query("SELECT count(*) n FROM news_ai WHERE processed_at::date = %s::date", (day,))[0]["n"]
    scored = query("SELECT * FROM predictions WHERE resolved_on=%s", (day,))
    open_pred = query("SELECT count(*) n FROM predictions WHERE status='open'")[0]["n"]
    major = query("""SELECT * FROM (
                       SELECT DISTINCT ON (e.symbol) e.symbol, e.direction, e.importance, n.headline, coalesce(f.market_cap, 0) cap
                       FROM news_events e JOIN news n ON n.id=e.news_id JOIN news_ai a ON a.news_id=e.news_id
                       LEFT JOIN features_daily f ON f.symbol=e.symbol AND f.date=%s
                       WHERE n.created_at >= %s::date - 1
                         AND n.created_at < greatest(%s::date + 1, now())     -- morning refresh: overnight + weekend news too
                         AND e.importance >= 4 AND NOT coalesce(a.recap,false)
                       ORDER BY e.symbol, e.importance DESC, n.created_at DESC) x
                     ORDER BY cap DESC, importance DESC LIMIT 8""", (day, day, day))   # one line per stock, biggest first
    reads = query("""SELECT r.symbol, r.guidance, r.tone, r.eps_surprise, r.rev_surprise, r.guidance_detail
                     FROM earnings_reads r LEFT JOIN features_daily f ON f.symbol=r.symbol AND f.date=%s
                     WHERE r.status='ok' AND r.mode='live' AND r.filed_at BETWEEN %s AND %s::date + 1
                     ORDER BY coalesce(f.market_cap, 0) DESC""", (day, day, day))
    earn = query("""SELECT u.symbol, u.report_date, u.time_of_day FROM upcoming_earnings u
                    JOIN features_daily f ON f.symbol=u.symbol AND f.date=%s
                    WHERE u.report_date <= %s::date + 3 AND coalesce(f.market_cap, 0) >= 20e9 ORDER BY u.report_date LIMIT 12""",
                 (day, day))

    unreal = sum(((b["last"] or b["entry_price"]) - b["entry_price"]) * b["shares"] for b in book)
    realized = sum(c["pnl"] or 0 for c in closed)
    buys = [p for p in plans if p["side"] == "buy"]
    sells = [p for p in plans if p["side"] == "sell"]
    L = [f"# Daily briefing: {day}", "",
         f"*Mode: **{'dry run (simulated trades, no orders)' if md_ == 'dry_run' else 'paper trading (Alpaca practice account)'}***", "",
         "## 1. The day in 5 lines",
         f"- **Market:** {snap['regime']}. S&P 500 {_p(spy)} today; exposure dial {snap['exposure']:.0%}.",
         f"- **Our book:** {len(book)} open positions, unrealized {unreal:+,.0f} USD; closed today: {len(closed)} ({realized:+,.0f} USD).",
         f"- **System:** read {news_n:,} news items; " + ("wrote the market analysis; " if j else "market analysis not written yet; ")
         + f"planned {len(buys)} buys and {len(sells)} exits for the next session.",
         f"- **Needs you:** {len(appr)} approval request(s)." if appr else "- **Needs you:** nothing today.",
         f"- **Predictions:** {open_pred} open" + (f", {len(scored)} scored today" if scored else "") + ".", ""]
    L += ["## 2. Decisions needed"]
    L += [f"- **#{a['id']} {a['title']}** (deadline {a['deadline']:%a %H:%M} ET). For: {a['case_for'] or ''}. "
          f"Against: {a['case_against'] or ''}. Reply in chat: \"approve #{a['id']}\", \"approve #{a['id']} half size\" or \"reject #{a['id']}\"."
          for a in appr] or ["- None."]
    L += ["", "## 3. Top findings"]
    if j:
        L += [f"> {j[0]['summary']}", "", "Full write-up: the Market analysis (reports/market).", ""]
    L += [f"- **{m['symbol']}** ({'+' if m['direction'] > 0 else ''}{m['direction']}, importance {m['importance']}): {m['headline'][:150]}" for m in major]
    if reads:
        g = {k: [r for r in reads if r["guidance"] == k] for k in ("raised", "lowered", "withdrawn")}
        L += ["", f"**Earnings releases read** (Haiku, names hidden): {len(reads)}; guidance raised {len(g['raised'])}, "
                  f"lowered {len(g['lowered'])}, withdrawn {len(g['withdrawn'])}."
              + (" Largest companies with a change:" if any(g.values()) else "")]
        for r in (g["raised"] + g["lowered"] + g["withdrawn"])[:8]:
            sur = ", ".join(f"{k.split('_')[0]} surprise {r[k]:+.1%}" for k in ("eps_surprise", "rev_surprise") if r[k] is not None)
            L += [f"- **{r['symbol']}** guidance {r['guidance']}, tone {r['tone']:+d}{'; ' + sur if sur else ''}: "
                  f"{(r['guidance_detail'] or '')[:160]}"]
    L += ["", "## 4. Portfolio" + (" (simulated)" if md_ == "dry_run" else ""),
          "| Stock | Strategy | Since | Entry | Last | P&L | Stop |", "|---|---|---|---|---|---|---|"]
    L += [f"| {b['symbol']} | {b['strategy']} | {b['entry_date']} | {b['entry_price']:.2f} | {(b['last'] or 0):.2f} | "
          f"{((b['last'] or b['entry_price']) / b['entry_price'] - 1) * 100:+.1f}% | {b['stop']:.2f} |" for b in book] or ["| (no open positions) | | | | | | |"]
    if closed:
        L += ["", "Closed today: " + "; ".join(f"{c['symbol']} {c['exit_reason']} {c['pnl']:+,.0f} USD" for c in closed)]
    L += ["", "## 5. What the system learned"]
    L += [f"- Prediction #{s['id']}: \"{s['statement']}\" → **{s['status']}** ({_p(s['outcome'])})" for s in scored] or ["- No predictions due today."]
    if j and j[0]["lesson"]:
        L += [f"- Lesson of the day: **{j[0]['lesson'].get('term')}**: {j[0]['lesson'].get('explanation')}"]
    L += ["", "## 6. Tomorrow",
          "| Action | Stock | Strategy | Shares | Limit | Stop | Value |", "|---|---|---|---|---|---|---|"]
    L += [f"| {p['side']} | {p['symbol']} | {p['strategy']} | {p['shares']} | {p['limit_price'] or 'market'} | {p['stop'] or ''} | "
          f"{p['position_value'] or 0:,.0f} |" for p in plans] or ["| (nothing planned) | | | | | | |"]
    if earn:
        L += ["", "Big companies reporting soon: " + ", ".join(f"{e['symbol']} {e['report_date']:%a} {e['time_of_day'] or ''}".strip() for e in earn)]
    if j and j[0]["watch"]:
        L += ["", "Watch: " + " · ".join(j[0]["watch"][:5])]
    L += ["", "*Generated by the system from its own data. Not financial advice.*"]
    return str(day), "\n".join(L)


@task("briefing.daily", priority=60, description="Publish the daily briefing (dashboard + reports/daily)")
def daily(ctx: TaskContext) -> dict:
    day, text = build()
    path = ROOT / "reports" / "daily" / f"{day}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return {"summary": f"daily briefing for {day} published ({len(text.split())} words)", "date": day}
