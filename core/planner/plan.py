"""Daily planner (architecture §10, build plan 2.4). Runs each evening after the market snapshot:

  1. Every strategy (experimental/paper/promoted) looks at the latest day → strategy_candidates
  2. Open positions: time stops, strategy exits, trailing-stop raises → exit plans / updated stops
  3. New entries: sized by risk, inside every Tier-1 hard limit and the exposure dial → trade_plans for the next session

Mode (settings.yaml → trading.mode): 'dry_run' = plans are simulated against real prices (forward test, no orders);
'paper' = the morning job sends them to the Alpaca PAPER account. Real money is never touched by this code.
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from core.backtest.data import load
from core.config import limits, settings
from core.log import event
from core.db import conn, query
from core.features.build import COLUMNS, info_for, universe
from core.strategy.base import load as load_strategies
from core.strategy.base import risk_budget

ET = ZoneInfo("America/New_York")


def mode() -> str:
    return settings().get("trading", {}).get("mode", "dry_run")


def next_session(after: date) -> date:
    from core.ingest import alpaca
    try:
        days = alpaca.trading("/v2/calendar", {"start": (after + timedelta(days=1)).isoformat(),
                                                "end": (after + timedelta(days=10)).isoformat()})
        return date.fromisoformat(days[0]["date"])
    except Exception:
        d = after + timedelta(days=1)
        while d.weekday() >= 5:
            d += timedelta(days=1)
        return d


def live_market(day: date, feature_days: int = 40):
    """Prices for ~15 months (strategies look back) + stored features for the recent days (same code computed them)."""
    syms = universe()["symbol"].tolist()
    m = load(day - timedelta(days=460), day, symbols=syms)
    info = info_for(m.symbols)
    m.is_common = (info["asset_type"] == "common").to_numpy()
    m.sector = info["sector"].to_numpy(dtype=object)
    rows = query(f"SELECT symbol, date, {', '.join(COLUMNS)} FROM features_daily WHERE date > %s AND date <= %s",
                 (day - timedelta(days=feature_days * 2), day))
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    ti, si = m.dates.get_indexer(df["date"]), pd.Index(m.symbols).get_indexer(df["symbol"])
    ok = (ti >= 0) & (si >= 0)
    m.f = {}
    for c in COLUMNS:
        a = np.full(m.close.shape, np.nan, dtype=np.float32)
        a[ti[ok], si[ok]] = pd.to_numeric(df[c], errors="coerce").to_numpy(dtype=np.float32)[ok]
        m.f[c] = a
    # Live planning: the latest earnings calendar is known before tomorrow's order, so it overrides the estimate
    # stored with the features (which could only use calendar snapshots taken on or before that day).
    t = len(m.dates) - 1
    cal = query("SELECT symbol, report_date FROM upcoming_earnings WHERE report_date >= %s", (day,))
    col = m._cols
    for r in cal:
        j = col.get(r["symbol"])
        if j is not None:
            m.f["days_to_earnings_est"][t, j] = (r["report_date"] - day).days
    return m


def account() -> dict:
    """Paper account equity, cash and positions (used in dry-run too, so sizes are realistic)."""
    from core.ingest import alpaca
    a = alpaca.trading("/v2/account")
    pos = {p["symbol"]: p for p in alpaca.trading("/v2/positions")}
    try:
        hist = alpaca.trading("/v2/account/portfolio/history", {"period": "1A", "timeframe": "1D"})
        peak = max([e for e in hist.get("equity", []) if e] + [float(a["equity"])])
    except Exception:
        peak = float(a["equity"])
    return {"equity": float(a["equity"]), "cash": float(a["cash"]), "peak": peak, "positions": pos}


def dry_run_account(day: date, close_of) -> dict:
    """The dry-run book's own money: start (trading.dry_run_start_equity, $100k like the paper account) + closed P&L
    + open positions at today's close. Until 2026-11-11 dry run borrowed the paper account's numbers, which only worked
    while paper sat idle at $100k; with paper trading live the two books must not share one account."""
    start = float(settings().get("trading", {}).get("dry_run_start_equity", 100000))
    realized = float(query("SELECT coalesce(sum(pnl), 0) s FROM positions_book WHERE mode='dry_run' AND status='closed'")[0]["s"])
    cost = value = 0.0
    for b in query("SELECT symbol, shares, entry_price FROM positions_book WHERE mode='dry_run' AND status='open'"):
        px = close_of(b["symbol"])
        cost += b["shares"] * float(b["entry_price"])
        value += b["shares"] * (px if px is not None else float(b["entry_price"]))
    equity = start + realized + value - cost
    return {"equity": equity, "cash": equity - value, "peak": max(start, equity), "positions": {}}


def _exposure_limit(dial: float, md: str) -> float:
    """How much of equity may be invested. While strategies are being tested (dry_run / paper), the user chose to
    invest up to `trading.exposure_override` (1.0) whatever the dial says (2026-11-10), so the dial doesn't starve
    the test of trades. The dial is still computed and recorded, so its value can be measured later. Real money will
    follow the dial unless decided otherwise."""
    override = settings().get("trading", {}).get("exposure_override")
    if override is not None and md in ("dry_run", "paper"):
        return float(override)
    return dial


def plan_day(day: date | None = None, md: str | None = None) -> dict:
    L = limits()
    md = md or mode()
    shadow = md == "dry_run" and mode() != "dry_run"     # the dry-run book running beside paper (run.books)
    day = day or query("SELECT max(date) d FROM features_daily WHERE symbol='SPY'")[0]["d"]
    session = next_session(day)
    if datetime.now(ET) >= datetime(session.year, session.month, session.day, 9, 15, tzinfo=ET):
        # that session already started (orders sent / fills being simulated): never replace its plans mid-session
        return {"summary": f"plan for {session} skipped: the session has started (latest features {day})",
                "skipped": True, "session": str(session)}
    m = live_market(day)
    t = len(m.dates) - 1
    if m.dates[t].date() != day:
        raise RuntimeError(f"prices end {m.dates[t].date()}, expected {day}")
    snap = query("SELECT exposure, regime FROM market_snapshot WHERE date=%s", (day,))
    dial = float(snap[0]["exposure"]) if snap else 0.5
    exposure = _exposure_limit(dial, md)
    if md == "dry_run":
        def _close(sym):
            j = m._cols.get(sym)
            v = float(m.close[t, j]) if j is not None else float("nan")
            return v if np.isfinite(v) else None
        acct = dry_run_account(day, _close)
    else:
        acct = account()
    equity = acct["equity"]
    book = query("SELECT * FROM positions_book WHERE status='open' AND mode=%s", (md,))
    held = {b["symbol"] for b in book} | set(acct["positions"]) if md == "paper" else {b["symbol"] for b in book}
    tiers = {r["symbol"]: r["tier"] for r in query("SELECT symbol, tier FROM liquidity WHERE date=(SELECT max(date) FROM liquidity)")}

    strategies = load_strategies()
    by_name = {s.name: s for s in strategies}
    n_cand = 0
    cands: dict[str, list] = {}
    with conn() as c:
        c.execute("DELETE FROM strategy_candidates WHERE date=%s", (day,))
        for s in strategies:
            try:                                  # one broken (e.g. AI-written) strategy must never stop the plan
                s.prepare(m)
                got = s.candidates(t, held)
            except Exception as e:                # noqa: BLE001
                event("strategy", f"{s.name} failed while planning {day}: {e}", level="error")
                by_name.pop(s.name, None)
                continue
            cands[s.name] = got
            for cd in got:
                c.execute("""INSERT INTO strategy_candidates (date, strategy, stage, symbol, score, close, stop, target, trail_pct,
                                                              max_hold, rationale, facts) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                          (day, s.name, s.stage, cd.symbol, cd.score, float(m.close[t, m.col(cd.symbol)]), cd.stop, cd.target,
                           cd.trail_pct, cd.max_hold, cd.rationale, json.dumps(cd.facts)))
                n_cand += 1

    plans, notes = [], []
    if exposure != dial:
        notes.append(f"exposure: the market dial says {dial:.0%}; testing override invests up to {exposure:.0%} "
                     f"(settings trading.exposure_override)")
    # ── exits and stop updates for open positions ──
    # Earnings: sell before the report unless the strategy is built to hold through it. An exit planned tonight fills at
    # the next open, so a report before the open of the session after that (or any time sooner) means exit now.
    second = next_session(session)
    reports = {r["symbol"]: r for r in query("SELECT symbol, report_date, time_of_day FROM upcoming_earnings "
                                             "WHERE report_date BETWEEN %s AND %s", (day, second))}
    sessions_held = {}
    for b in book:
        j = m._cols.get(b["symbol"])
        if j is None:
            continue
        close = float(m.close[t, j])
        held_days = int(((m.dates > pd.Timestamp(b["entry_date"])) & (m.dates <= m.dates[t])).sum())
        sessions_held[b["symbol"]] = held_days
        reason = None
        if b["max_hold"] and held_days >= b["max_hold"]:
            reason = f"time stop: held {held_days} trading days (max {b['max_hold']})"
        st = by_name.get(b["strategy"])
        rep = reports.get(b["symbol"])
        if reason is None and rep and not (st is not None and st.holds_through_earnings):
            reason = f"earnings on {rep['report_date']:%a %b %d} {rep['time_of_day'] or ''}: sell before the report".strip()
        if reason is None and st is not None:
            try:
                if b["symbol"] in st.exits(t, m, {b["symbol"]}):
                    reason = "strategy exit signal"
            except Exception as e:                # noqa: BLE001
                event("strategy", f"{st.name}.exits failed for {b['symbol']}: {e}", level="error")
        if reason:
            plans.append(dict(strategy=b["strategy"], symbol=b["symbol"], side="sell", shares=b["shares"], limit_price=None,
                              stop=None, target=None, trail_pct=None, max_hold=None, risk_dollars=0, risk_pct=0,
                              position_value=b["shares"] * close, reason=reason, needs_approval=False))
            continue
        high = max(float(b["high_close"] or b["entry_price"]), close)
        new_stop = b["stop"]
        if b["trail_pct"]:
            new_stop = max(b["stop"], high * (1 - b["trail_pct"]))
        if new_stop > b["stop"] + 1e-6 or high > (b["high_close"] or 0):
            with conn() as c:
                c.execute("UPDATE positions_book SET stop=%s, high_close=%s WHERE id=%s", (round(new_stop, 2), high, b["id"]))
            if new_stop > b["stop"] + 1e-6:
                notes.append(f"{b['symbol']}: trailing stop raised {b['stop']:.2f} → {new_stop:.2f}")

    # ── circuit breaker ──
    if equity < acct["peak"] * (1 - L["circuit_breaker_drawdown"]):
        notes.append(f"CIRCUIT BREAKER: equity {equity:,.0f} is more than {L['circuit_breaker_drawdown']:.0%} below peak "
                     f"{acct['peak']:,.0f}; no new entries until you approve resuming")
        return _save(day, session, md, plans, notes, n_cand, exposure)

    # ── new entries ──
    cfg = settings().get("trading", {})
    max_positions = int(cfg.get("max_positions", 20))
    per_strategy_day = int(cfg.get("max_new_per_strategy_per_day", 2))
    min_value = float(cfg.get("min_position_value", 1000))
    open_value = {b["symbol"]: b["shares"] * float(m.close[t, m.col(b["symbol"])]) for b in book if b["symbol"] in m._cols}
    sector_of = dict(zip(m.symbols, m.sector))
    used_sector: dict = {}
    used_strategy: dict = {}
    for b in book:
        v = open_value.get(b["symbol"], 0)
        used_sector[sector_of.get(b["symbol"])] = used_sector.get(sector_of.get(b["symbol"]), 0) + v
        used_strategy[b["strategy"]] = used_strategy.get(b["strategy"], 0) + v
    invested = sum(open_value.values())
    room = max(0.0, exposure * equity - invested)
    slots = max_positions - len(book)
    adv = m.f["adv20"][t]
    planned_syms = set()
    # strategies take turns (one pick each per round) so no single idea fills the book
    queues = {name: list(cs[:per_strategy_day]) for name, cs in cands.items()}
    while slots > 0 and room > 0 and any(queues.values()):
        for name in list(queues):
            if not queues[name] or slots <= 0 or room <= 0:
                continue
            cd = queues[name].pop(0)
            if cd.symbol in held or cd.symbol in planned_syms:
                continue
            st, j = by_name[name], m.col(cd.symbol)
            price = float(m.close[t, j])
            per_share = price - cd.stop
            if per_share <= 0:
                continue
            tier = tiers.get(cd.symbol, "emerging")
            risk_pct = risk_budget(st.stage) * (0.5 if tier == "thin" else 1.0)
            shares = equity * risk_pct / per_share
            caps = {"15% per stock": equity * L["max_position_weight"] / price,
                    "1% of daily volume": (adv[j] * L["liquidity"]["max_position_pct_of_adv"] / price) if np.isfinite(adv[j]) else 0,
                    "25% per sector": max(0.0, equity * L["max_sector_weight"] - used_sector.get(sector_of.get(cd.symbol), 0)) / price,
                    f"{L['max_unproven_strategy_weight']:.0%} per unproven strategy":
                        max(0.0, equity * L["max_unproven_strategy_weight"] - used_strategy.get(name, 0)) / price
                        if st.stage in ("experimental", "paper") else math.inf,
                    "exposure dial / cash": min(room, acct["cash"] if md == "paper" else room) / price}
            binding = min(caps, key=caps.get)
            final = int(min(shares, *caps.values()))
            if final < 1 or final * price < min_value:     # leftover-money crumbs (e.g. 2 shares, $79) teach nothing
                notes.append(f"{name} {cd.symbol}: skipped (${final * price:,.0f} after '{binding}' limit; "
                             f"minimum ${min_value:,.0f})")
                continue
            if shadow and tier == "emerging":     # only the paper plan asks you; the shadow book doesn't buy unasked
                notes.append(f"{name} {cd.symbol}: skipped in the shadow dry run (thin stock needs your approval)")
                continue
            value = final * price
            plans.append(dict(strategy=name, symbol=cd.symbol, side="buy", shares=final,
                              limit_price=round(price * (1 + cfg.get("entry_limit_above_close", 0.01)), 2),
                              stop=round(cd.stop, 2), target=round(cd.target, 2) if cd.target else None,
                              trail_pct=cd.trail_pct, max_hold=cd.max_hold, risk_dollars=final * per_share,
                              risk_pct=final * per_share / equity, position_value=value,
                              reason=f"{cd.rationale[:300]} | size limited by: {binding if final < shares - 1 else 'risk budget'}",
                              needs_approval=(tier == "emerging")))
            planned_syms.add(cd.symbol)
            used_sector[sector_of.get(cd.symbol)] = used_sector.get(sector_of.get(cd.symbol), 0) + value
            used_strategy[name] = used_strategy.get(name, 0) + value
            room -= value
            slots -= 1
    return _save(day, session, md, plans, notes, n_cand, exposure)


def _save(day, session, md, plans, notes, n_cand, exposure) -> dict:
    deadline = datetime(session.year, session.month, session.day, 9, 15, tzinfo=ET)
    with conn() as c:
        c.execute("DELETE FROM trade_plans WHERE trade_date=%s AND mode=%s AND status IN ('planned','waiting_approval')", (session, md))
        for p in plans:
            row = c.execute("""INSERT INTO trade_plans (signal_date, trade_date, mode, strategy, symbol, side, shares, limit_price, stop,
                                   target, trail_pct, max_hold, risk_dollars, risk_pct, position_value, reason, needs_approval, status)
                               VALUES (%(sd)s,%(td)s,%(md)s,%(strategy)s,%(symbol)s,%(side)s,%(shares)s,%(limit_price)s,%(stop)s,
                                       %(target)s,%(trail_pct)s,%(max_hold)s,%(risk_dollars)s,%(risk_pct)s,%(position_value)s,
                                       %(reason)s,%(needs_approval)s,%(status)s)
                               ON CONFLICT (trade_date, strategy, symbol, side, mode) DO NOTHING RETURNING id""",
                            {**p, "sd": day, "td": session, "md": md,
                             "status": "waiting_approval" if p["needs_approval"] else "planned"}).fetchone()
            if row and p["needs_approval"]:
                c.execute("""INSERT INTO approvals (kind, plan_id, title, case_for, case_against, details, deadline)
                             VALUES ('emerging_stock', %s, %s, %s, %s, %s, %s)""",
                          (row["id"], f"Buy {p['shares']} {p['symbol']} ({p['strategy']}): thinly traded stock",
                           p["reason"], "Thin trading: wide spreads, prices jump; the strategy is unproven.",
                           json.dumps({k: p[k] for k in ("shares", "limit_price", "stop", "risk_dollars", "position_value")}),
                           deadline))
    buys = [p for p in plans if p["side"] == "buy"]
    sells = [p for p in plans if p["side"] == "sell"]
    return {"summary": f"plan for {session} ({md}): {len(buys)} buys (${sum(p['position_value'] for p in buys):,.0f}), "
                       f"{len(sells)} exits, from {n_cand} candidates; may invest up to {exposure:.0%}"
                       + (f"; {len(notes)} notes" if notes else ""),
            "session": str(session), "buys": len(buys), "sells": len(sells), "candidates": n_cand, "notes": notes}
