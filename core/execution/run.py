"""Execution (architecture §11, build plan 2.5): turns trade plans into fills, in one of two modes.

dry_run: after the close, each plan for today is simulated against today's real bar (same rules as the backtester:
         fill at the open only if it's at or below our limit; stop and target checked during the day, a gap through
         the stop fills at the open). This is a true forward test with no orders sent.
paper:   at 9:20 am ET, plans are sent to the Alpaca PAPER account as limit orders with an attached stop-loss
         (plus a take-profit when the plan has a fixed target and no trailing stop). A sync job records fills, and
         raises the broker stop when our trailing stop moves up. Never real money.
"""
from __future__ import annotations

from datetime import date

from core.config import settings
from core.db import conn, query
from core.ingest import alpaca
from core.execution.journal import entry_context, exit_context, update_excursions
from core.log import event

COST_BPS = {"liquid": 5.0, "thin": 15.0, "emerging": 40.0}


def _tier(symbol: str) -> str:
    r = query("SELECT tier FROM liquidity WHERE symbol=%s ORDER BY date DESC LIMIT 1", (symbol,))
    return r[0]["tier"] if r else "emerging"


def _bar(symbol: str, day: date) -> dict | None:
    r = query("SELECT open, high, low, close FROM daily_prices WHERE symbol=%s AND date=%s", (symbol, day))
    return r[0] if r else None


def _spy(day: date) -> float | None:
    r = query("SELECT close FROM daily_prices WHERE symbol='SPY' AND date=%s", (day,))
    return float(r[0]["close"]) if r else None


def _close_position(c, b: dict, day: date, price: float, reason: str, cost: bool = True) -> float:
    fill = price * (1 - COST_BPS[_tier(b["symbol"])] / 1e4) if cost else price
    pnl = (fill - b["entry_price"]) * b["shares"]
    hi_lo = c.execute("SELECT max(high) hi, min(low) lo FROM daily_prices WHERE symbol=%s AND date BETWEEN %s AND %s",
                      (b["symbol"], b["entry_date"], day)).fetchone()
    c.execute("""UPDATE positions_book SET status='closed', exit_date=%s, exit_price=%s, exit_reason=%s, pnl=%s, spy_exit=%s,
                   exit_context=%s, mfe=COALESCE(%s / entry_price - 1, mfe), mae=COALESCE(%s / entry_price - 1, mae) WHERE id=%s""",
              (day, fill, reason, pnl, _spy(day), exit_context(b["symbol"], day, reason),
               max(hi_lo["hi"] or 0, price) if hi_lo else None, min(hi_lo["lo"] or price, price) if hi_lo else None, b["id"]))
    return pnl


# ── dry run ─────────────────────────────────────────────────────────────────────────────────────────────────────
def simulate_session(day: date) -> dict:
    """Apply today's real prices to dry-run plans and open dry-run positions."""
    filled = expired = exits = 0
    pnl = 0.0
    with conn() as c:
        for p in query("SELECT * FROM trade_plans WHERE mode='dry_run' AND trade_date=%s AND status='planned' ORDER BY side DESC", (day,)):
            bar = _bar(p["symbol"], day)
            if bar is None:
                c.execute("UPDATE trade_plans SET status='expired', error='no price bar', updated_at=now() WHERE id=%s", (p["id"],))
                expired += 1
                continue
            if p["side"] == "sell":
                b = c.execute("SELECT * FROM positions_book WHERE mode='dry_run' AND symbol=%s AND status='open'", (p["symbol"],)).fetchall()
                if b:
                    pnl += _close_position(c, b[0], day, float(bar["open"]), p["reason"] or "exit plan")
                    exits += 1
                c.execute("UPDATE trade_plans SET status='simulated', fill_price=%s, filled_shares=%s, updated_at=now() WHERE id=%s",
                          (bar["open"], p["shares"], p["id"]))
                continue
            if bar["open"] > p["limit_price"] or (p["stop"] and bar["open"] <= p["stop"]):
                c.execute("UPDATE trade_plans SET status='expired', error=%s, updated_at=now() WHERE id=%s",
                          ("opened above our limit" if bar["open"] > p["limit_price"] else "opened below the stop", p["id"]))
                expired += 1
                continue
            fill = float(bar["open"]) * (1 + COST_BPS[_tier(p["symbol"])] / 1e4)
            c.execute("UPDATE trade_plans SET status='simulated', fill_price=%s, filled_shares=%s, updated_at=now() WHERE id=%s",
                      (fill, p["shares"], p["id"]))
            c.execute("""INSERT INTO positions_book (mode, plan_id, strategy, symbol, shares, entry_date, entry_price, stop, target,
                                                     trail_pct, high_close, max_hold, spy_entry, entry_context)
                         VALUES ('dry_run',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                      (p["id"], p["strategy"], p["symbol"], p["shares"], day, fill, p["stop"], p["target"], p["trail_pct"],
                       fill, p["max_hold"], _spy(day), entry_context(p)))
            filled += 1
        # stops and targets during the day (entries made today included, like the backtester)
        for b in c.execute("SELECT * FROM positions_book WHERE mode='dry_run' AND status='open'").fetchall():  # same transaction: sees today's entries
            bar = _bar(b["symbol"], day)
            if bar is None:
                continue
            if bar["open"] <= b["stop"] and b["entry_date"] < day:
                pnl += _close_position(c, b, day, float(bar["open"]), "stop (gapped below)")
            elif bar["low"] <= b["stop"]:
                pnl += _close_position(c, b, day, float(b["stop"]), "stop")
            elif b["target"] and not b["trail_pct"] and bar["high"] >= b["target"]:
                pnl += _close_position(c, b, day, float(max(b["target"], bar["open"])), "target")
            else:
                continue
            exits += 1
    return {"filled": filled, "expired": expired, "exits": exits, "realized_pnl": round(pnl, 2)}


# ── paper ───────────────────────────────────────────────────────────────────────────────────────────────────────
def submit_paper(day: date) -> dict:
    sent, errors = 0, []
    for p in query("""SELECT * FROM trade_plans WHERE mode='paper' AND trade_date=%s AND status='planned'
                      ORDER BY side DESC""", (day,)):
        try:
            if p["side"] == "sell":
                for o in alpaca.trading("/v2/orders", {"status": "open", "symbols": p["symbol"], "nested": "true"}):
                    alpaca.trading_send("DELETE", f"/v2/orders/{o['id']}")
                body = {"symbol": p["symbol"], "qty": str(p["shares"]), "side": "sell", "type": "market",
                        "time_in_force": "day", "client_order_id": f"tb-{p['id']}"}
            else:
                body = {"symbol": p["symbol"], "qty": str(p["shares"]), "side": "buy", "type": "limit",
                        "limit_price": f"{p['limit_price']:.2f}", "time_in_force": "day", "client_order_id": f"tb-{p['id']}",
                        "order_class": "oto", "stop_loss": {"stop_price": f"{p['stop']:.2f}"}}
                if p["target"] and not p["trail_pct"]:
                    body["order_class"] = "bracket"
                    body["take_profit"] = {"limit_price": f"{p['target']:.2f}"}
            o = alpaca.trading_send("POST", "/v2/orders", body)
            query("UPDATE trade_plans SET status='submitted', broker_order_id=%s, updated_at=now() WHERE id=%s RETURNING id",
                  (o["id"], p["id"]))
            sent += 1
        except Exception as e:  # one bad order must not stop the others
            errors.append(f"{p['symbol']}: {e}")
            query("UPDATE trade_plans SET status='error', error=%s, updated_at=now() WHERE id=%s RETURNING id", (str(e)[:300], p["id"]))
    if errors:
        event("trading", f"{len(errors)} paper order(s) failed: {'; '.join(errors)[:300]}", level="warn")
    return {"sent": sent, "errors": errors}


def sync_paper(day: date) -> dict:
    """Record fills, open book entries, close positions whose stop/target filled, and raise broker stops."""
    fills = closes = raised = 0
    with conn() as c:
        for p in query("SELECT * FROM trade_plans WHERE mode='paper' AND status IN ('submitted','partially_filled')"):
            o = alpaca.trading(f"/v2/orders/{p['broker_order_id']}", {"nested": "true"})
            st = o["status"]
            if st in ("filled", "partially_filled"):
                qty, px = int(float(o["filled_qty"])), float(o["filled_avg_price"] or 0)
                c.execute("UPDATE trade_plans SET status=%s, fill_price=%s, filled_shares=%s, updated_at=now() WHERE id=%s",
                          (st, px, qty, p["id"]))
                if st == "filled" and p["side"] == "buy":
                    stop_leg = next((leg for leg in (o.get("legs") or []) if leg.get("type") in ("stop", "stop_limit")), None)
                    c.execute("""INSERT INTO positions_book (mode, plan_id, strategy, symbol, shares, entry_date, entry_price, stop,
                                     target, trail_pct, high_close, max_hold, spy_entry, stop_order_id, broker_stop, entry_context)
                                 VALUES ('paper',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                              (p["id"], p["strategy"], p["symbol"], qty, day, px, p["stop"], p["target"], p["trail_pct"], px,
                               p["max_hold"], _spy(day), stop_leg["id"] if stop_leg else None, p["stop"], entry_context(p)))
                    fills += 1
                elif st == "filled" and p["side"] == "sell":
                    for b in c.execute("SELECT * FROM positions_book WHERE mode='paper' AND symbol=%s AND status='open'",
                                       (p["symbol"],)).fetchall():
                        _close_position(c, b, day, px, p["reason"] or "exit plan", cost=False)
                        closes += 1
            elif st in ("canceled", "expired", "rejected"):
                c.execute("UPDATE trade_plans SET status=%s, error=%s, updated_at=now() WHERE id=%s",
                          ("cancelled" if st == "canceled" else st if st == "expired" else "error", f"broker: {st}", p["id"]))
        held = {x["symbol"]: x for x in alpaca.trading("/v2/positions")}
        for b in query("SELECT * FROM positions_book WHERE mode='paper' AND status='open'"):
            if b["symbol"] not in held:          # stop or target filled at the broker
                acts = alpaca.trading("/v2/account/activities/FILL", {"after": b["entry_date"].isoformat()})
                sells = [a for a in acts if a["symbol"] == b["symbol"] and a["side"] == "sell"]
                px = float(sells[0]["price"]) if sells else float(b["stop"])
                reason = "stop" if px <= (b["broker_stop"] or b["stop"]) * 1.001 else "target"
                _close_position(c, b, day, px, reason, cost=False)
                closes += 1
            elif b["stop_order_id"] and b["stop"] > (b["broker_stop"] or 0) + 0.005:
                try:
                    alpaca.trading_send("PATCH", f"/v2/orders/{b['stop_order_id']}", {"stop_price": f"{b['stop']:.2f}"})
                    c.execute("UPDATE positions_book SET broker_stop=%s WHERE id=%s", (b["stop"], b["id"]))
                    raised += 1
                except Exception as e:
                    event("trading", f"couldn't raise stop for {b['symbol']}: {e}", level="warn")
    return {"fills": fills, "closes": closes, "stops_raised": raised}


def expire_approvals() -> int:
    rows = query("""UPDATE approvals SET status='expired', decided_at=now() WHERE status='pending' AND deadline < now()
                    RETURNING plan_id""")
    for r in rows:
        if r["plan_id"]:
            query("UPDATE trade_plans SET status='expired', error='no approval before the deadline (safe default: no trade)', "
                  "updated_at=now() WHERE id=%s RETURNING id", (r["plan_id"],))
    return len(rows)


def mode() -> str:
    return settings().get("trading", {}).get("mode", "dry_run")

