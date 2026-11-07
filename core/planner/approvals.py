"""Approval queue (architecture §10.8): the user approves / trims / rejects escalated trades on the dashboard or in
chat ("approve #3, half size"). No answer by the deadline → the safe default (no trade)."""
from __future__ import annotations

from core.db import conn, query


def pending() -> list[dict]:
    return query("""SELECT a.*, p.symbol, p.strategy, p.shares, p.limit_price, p.stop, p.position_value, p.risk_dollars, p.trade_date
                    FROM approvals a LEFT JOIN trade_plans p ON p.id = a.plan_id
                    WHERE a.status = 'pending' ORDER BY a.deadline""")


def decide(approval_id: int, approve: bool, size: float = 1.0, comment: str | None = None) -> str:
    if not 0 < size <= 1:
        raise ValueError("size must be between 0 and 1 (1 = as planned, 0.5 = half)")
    with conn() as c:
        a = c.execute("SELECT * FROM approvals WHERE id=%s FOR UPDATE", (approval_id,)).fetchone()
        if a is None:
            raise ValueError(f"no approval #{approval_id}")
        if a["status"] != "pending":
            return f"#{approval_id} is already {a['status']}"
        c.execute("UPDATE approvals SET status=%s, size_factor=%s, comment=%s, decided_at=now() WHERE id=%s",
                  ("approved" if approve else "rejected", size if approve else None, comment, approval_id))
        if a["plan_id"]:
            if approve:
                c.execute("""UPDATE trade_plans SET status='planned', shares=GREATEST(1, floor(shares * %s)::int),
                               position_value=position_value * %s, risk_dollars=risk_dollars * %s, updated_at=now()
                             WHERE id=%s AND status='waiting_approval'""", (size, size, size, a["plan_id"]))
            else:
                c.execute("UPDATE trade_plans SET status='rejected', updated_at=now() WHERE id=%s", (a["plan_id"],))
    return f"#{approval_id} {'approved' + (f' at {size:.0%} size' if size < 1 else '') if approve else 'rejected'}"
