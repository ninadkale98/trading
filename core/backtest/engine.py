"""Daily event-driven backtester (build plan 1.9). Same order logic the live system will use.

Timeline for each trading day t:
  1. Fill entries queued at the previous close (market-on-open or limit), paying trading costs.
  2. Exits during the day, worst case first:
       • a gap through the stop fills at the OPEN (e.g. Intel: stop $85, opened $68.36 → filled ~$68), not at the stop
       • stop and target both touched the same day → assume the stop came first
       • partial profit at target 1, remainder rides a trailing stop
  3. At the close: trailing stops ratchet up, time stops, delisted stocks closed at their last price,
     equity marked to market.
  4. The strategy sees data up to today's close and proposes entries for tomorrow.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from core.backtest.data import Market
from core.config import limits


@dataclass
class Signal:
    symbol: str
    stop: float | None = None              # absolute (adjusted) price; required unless weight sizing
    entry: str = "open"                    # "open" (next open) or "limit"
    limit: float | None = None
    target: float | None = None
    partial: float = 0.0                   # fraction sold at target (0 = sell all at target)
    trail_pct: float | None = None         # trailing stop distance below the highest close, e.g. 0.08
    max_hold: int | None = None            # trading days
    risk_pct: float | None = None          # account risk for this trade (defaults to normal max)
    weight: float | None = None            # alternative: fixed % of equity (benchmarks); no stop needed
    tag: str = ""


@dataclass
class Position:
    symbol: str
    col: int
    shares: float
    entry_price: float
    entry_t: int
    stop: float | None
    target: float | None
    partial: float
    trail_pct: float | None
    max_hold: int | None
    initial_risk: float           # dollars at risk at entry (for R-multiples)
    high_close: float
    tag: str
    realized: float = 0.0         # P&L already booked from partial exits
    cost_basis: float = 0.0


@dataclass
class Config:
    start_cash: float = 100_000.0
    max_positions: int = 20
    cost_bps: dict = field(default_factory=lambda: {"liquid": 5.0, "thin": 15.0, "emerging": 40.0})
    enforce_limits: bool = True
    sector_of: dict | None = None      # symbol → sector, for the sector cap


@dataclass
class Result:
    equity: pd.Series
    trades: pd.DataFrame
    config: Config
    exposure: pd.Series


class Strategy:
    """Base class. `prepare` precomputes indicators (must be causal); `signals` runs at each close."""
    name = "base"
    version = "1"
    params: dict = {}

    def prepare(self, m: Market) -> None: ...

    def signals(self, t: int, m: Market, held: set[str]) -> list[Signal]:
        return []

    def exits(self, t: int, m: Market, held: set[str]) -> list[str]:
        """Symbols to sell at the next open (e.g. trend broken, thesis broken)."""
        return []


def _adv20(m: Market) -> np.ndarray:
    dv = pd.DataFrame(m.dollar_volume)
    return dv.rolling(20, min_periods=5).mean().to_numpy()


def run(strategy: Strategy, m: Market, cfg: Config | None = None) -> Result:
    cfg = cfg or Config()
    L = limits()
    liq = L["liquidity"]
    adv = _adv20(m)
    strategy.prepare(m)

    cash = cfg.start_cash
    positions: dict[str, Position] = {}
    pending: list[tuple[Signal, int, float]] = []      # (signal, column, planned shares)
    pending_exits: set[str] = set()
    trades: list[dict] = []
    equity_curve = np.zeros(len(m.dates))
    exposure = np.zeros(len(m.dates))

    def tier_bps(col: int, t: int) -> float:
        a = adv[t, col]
        if not np.isfinite(a) or a < liq["thin_min_adv"]:
            return cfg.cost_bps["emerging"]
        return cfg.cost_bps["liquid"] if a >= liq["liquid_min_adv"] else cfg.cost_bps["thin"]

    def close_out(p: Position, shares: float, price: float, t: int, reason: str) -> None:
        nonlocal cash
        fill = price * (1 - tier_bps(p.col, t) / 1e4)
        cash += shares * fill
        pnl = shares * (fill - p.entry_price)
        p.realized += pnl
        p.shares -= shares
        if p.shares <= 1e-9:
            total_pnl = p.realized
            trades.append({
                "symbol": p.symbol, "tag": p.tag, "entry_date": m.dates[p.entry_t], "exit_date": m.dates[t],
                "entry_price": p.entry_price, "exit_price": fill, "hold_days": t - p.entry_t,
                "shares": p.cost_basis / p.entry_price if p.entry_price else 0.0, "cost_basis": p.cost_basis,
                "pnl": total_pnl, "ret": total_pnl / p.cost_basis if p.cost_basis else 0.0,
                "r_multiple": total_pnl / p.initial_risk if p.initial_risk > 0 else np.nan, "exit_reason": reason,
            })
            positions.pop(p.symbol, None)

    for t in range(len(m.dates)):
        o, h, l, c = m.open[t], m.high[t], m.low[t], m.close[t]

        # 1 ── entries from yesterday's signals
        for sig, col, planned in pending:
            if sig.symbol in positions or not np.isfinite(o[col]):
                continue
            if sig.entry == "limit":
                if not (l[col] <= sig.limit):
                    continue
                px = min(o[col], sig.limit)
            else:
                px = o[col]
            if sig.stop is not None and px <= sig.stop:
                continue                       # gapped below our stop before we got in: skip
            fill = px * (1 + tier_bps(col, t) / 1e4)
            shares = math.floor(min(planned, cash / fill)) if planned else 0
            if shares <= 0:
                continue
            cash -= shares * fill
            risk = shares * (fill - sig.stop) if sig.stop is not None else 0.0
            positions[sig.symbol] = Position(sig.symbol, col, shares, fill, t, sig.stop, sig.target, sig.partial,
                                             sig.trail_pct, sig.max_hold, risk, fill, sig.tag, 0.0, shares * fill)
        pending = []

        # 2 ── strategy exits at the open, then intraday exits (worst case first)
        for sym in pending_exits:
            p = positions.get(sym)
            if p is not None and np.isfinite(o[p.col]):
                close_out(p, p.shares, o[p.col], t, "signal")
        pending_exits = set()
        for p in list(positions.values()):
            col = p.col
            if not np.isfinite(o[col]):
                continue
            if p.stop is not None and o[col] <= p.stop:
                close_out(p, p.shares, o[col], t, "stop_gap")
                continue
            if p.target is not None and o[col] >= p.target:
                sell = p.shares * p.partial if p.partial else p.shares
                close_out(p, sell, o[col], t, "target_gap")
                if p.symbol in positions:
                    p.target = None
                continue
            hit_stop = p.stop is not None and l[col] <= p.stop
            hit_target = p.target is not None and h[col] >= p.target
            if hit_stop:                       # if both, the stop is assumed to come first
                close_out(p, p.shares, p.stop, t, "stop")
                continue
            if hit_target:
                sell = p.shares * p.partial if p.partial else p.shares
                close_out(p, sell, p.target, t, "target")
                if p.symbol in positions:
                    p.target = None            # remainder now rides the trailing stop

        # 3 ── end of day: trailing stops, time stops, delistings, mark to market
        value = 0.0
        for p in list(positions.values()):
            col = p.col
            px = c[col]
            if not np.isfinite(px):
                px = m.close[max(0, t - 1), col] if t else p.entry_price
            if t >= m.last_index[col] and t < len(m.dates) - 1:
                close_out(p, p.shares, px, t, "delisted")
                continue
            if p.max_hold is not None and t - p.entry_t >= p.max_hold:
                close_out(p, p.shares, px, t, "time")
                continue
            if p.trail_pct and np.isfinite(c[col]):
                p.high_close = max(p.high_close, c[col])
                trail = p.high_close * (1 - p.trail_pct)
                p.stop = trail if p.stop is None else max(p.stop, trail)
            value += p.shares * px
        equity = cash + value
        equity_curve[t] = equity
        exposure[t] = value / equity if equity > 0 else 0.0

        # 4 ── new signals at today's close → orders for tomorrow
        if t == len(m.dates) - 1:
            break
        pending_exits = set(strategy.exits(t, m, set(positions)))
        slots = cfg.max_positions - len(positions)
        if slots <= 0:
            continue
        for sig in strategy.signals(t, m, set(positions)):
            if slots <= 0:
                break
            if sig.symbol in positions or sig.symbol not in m._cols:
                continue
            col = m.col(sig.symbol)
            ref = sig.limit if sig.entry == "limit" else c[col]
            if not np.isfinite(ref) or ref <= 0:
                continue
            if sig.weight is not None:
                shares = equity * sig.weight / ref
            else:
                if sig.stop is None and L["require_stop_loss"]:
                    continue
                per_share = ref - sig.stop
                if per_share <= 0:
                    continue
                risk_pct = min(sig.risk_pct or L["normal_risk_per_trade_max"], L["max_loss_per_trade"])
                shares = equity * risk_pct / per_share
            if cfg.enforce_limits:
                shares = min(shares, equity * L["max_position_weight"] / ref)
                a = adv[t, col]
                if np.isfinite(a) and a > 0:
                    shares = min(shares, a * liq["max_position_pct_of_adv"] / ref)
                if cfg.sector_of:
                    sec = cfg.sector_of.get(sig.symbol)
                    used = sum(p.shares * (c[p.col] if np.isfinite(c[p.col]) else p.entry_price)
                               for p in positions.values() if cfg.sector_of.get(p.symbol) == sec)
                    shares = min(shares, max(0.0, equity * L["max_sector_weight"] - used) / ref)
            if shares >= 1:
                pending.append((sig, col, shares))
                slots -= 1

    # close anything still open at the last price (marked, not a real exit)
    last_t = len(m.dates) - 1
    for p in list(positions.values()):
        px = m.close[last_t, p.col] if np.isfinite(m.close[last_t, p.col]) else p.entry_price
        close_out(p, p.shares, px, last_t, "end_of_test")
    equity_curve[last_t] = cash
    return Result(pd.Series(equity_curve, index=m.dates), pd.DataFrame(trades), cfg, pd.Series(exposure, index=m.dates))
