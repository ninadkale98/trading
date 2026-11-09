"""The self-improving strategy lab (architecture §9, build plan Phase 4). One `lab.cycle` task runs a full round:

  1. retire  live strategies whose live record has clearly gone bad (decay monitor)
  2. propose Opus reads the lab notebook, every strategy's results (backtest + live), the research notes and the feature
             catalog, and proposes new ideas or variations, each with a hypothesis written BEFORE testing
  3. build   Sonnet writes each idea as a strategy file in lab/candidates/; the sandbox validator checks it
  4. smoke   (own process) imports it, runs every method on a small recent market, checks speed and look-ahead;
             failures go back to Sonnet with the error, up to 2 more tries
  5. test    (own process) look-ahead check, signal study and the train backtest with the fixed gates (2016–2022)
  6. decide  fixed rules (below): admit to live dry-run/paper trading as experimental, promote after the unseen-years
             test, or reject. Too many live strategies → the weakest is retired
  7. report  Opus writes what the round found; lessons go to lab/notebook.md and feature requests to lab/requests.md
             (the weekly engineer builds those features, so the next round can use them: the recursion)

Every step is status-driven (ideas.status), so a usage-limit pause or a restart resumes where it stopped.
The AI never edits core/: it writes strategy files only, and the gates, sandbox and look-ahead checks are fixed code.
"""
from __future__ import annotations

import json
import math
import shutil
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from core.ai import claude
from core.config import ROOT
from core.db import execute, query
from core.lab.sandbox import Rejected, validate
from core.log import event
from core.tasks.registry import TaskContext, task

CANDIDATES = ROOT / "lab" / "candidates"
NOTEBOOK = ROOT / "lab" / "notebook.md"
REQUESTS = ROOT / "lab" / "requests.md"
MAX_ACTIVE = 16                 # live strategies (experimental + paper); more → retire the weakest
MIN_LIVE_DAYS = 20              # a newly admitted strategy gets ~a month before the cap can retire it
BUILD_TRIES = 3

# ── fixed decision rules (written before any AI idea was tested) ────────────────────────────────────────────────
#   reject  : build/test error, look-ahead found, or < 30 signals in 7 years (nothing to learn from)
#   admit   : "sign of life" in train: signal-study excess vs the pool > 0 with overlap-adjusted t > 0.5 at 20 or 60
#             days, or backtest excess per trade > 0 with t > 1 that stays > 0 without its best year (added after
#             round 1). Deliberately a LOW bar: the user wants many live
#             experiments (paper money); live results then decide
#   promote : passed the strict train gates AND the unseen 2023–2024 years → strategies/paper/
#   retire  : live ≥ 15 closed trades with average excess vs SPY < 0 and t < −1.5, or weakest when over MAX_ACTIVE


def decide(r: dict) -> tuple[str, str]:
    """(decision, reason) from a test result. decision ∈ reject | admit | validate."""
    if not r.get("ok"):
        return "reject", f"error: {str(r.get('error'))[:200]}"
    ss = {row["horizon_days"]: row for row in r.get("signal_study", [])}
    n = max((row.get("signals") or 0) for row in ss.values()) if ss else 0
    if n < 30:
        return "reject", f"only {n} signals in 2016–2022: too rare to learn from"
    if r.get("passed_train"):
        return "validate", "passed the strict train gates → test on unseen 2023–2024"
    life = []
    for h in (20, 60):
        row = ss.get(h) or {}
        if (row.get("vs_pool") or 0) > 0 and (row.get("t_vs_pool_adj") or 0) > 0.5:
            life.append(f"{h}d: {row['vs_pool']:+.2%} vs pool (t_adj {row['t_vs_pool_adj']:.2f})")
    bt = r.get("backtest") or {}
    lobyo = leave_best_year_out(bt.get("by_year") or [])
    if (bt.get("avg_excess") or 0) > 0 and (bt.get("t_excess") or 0) > 1 and (lobyo is None or lobyo > 0):
        life.append(f"backtest {bt['avg_excess']:+.2%}/trade vs SPY (t {bt['t_excess']:.2f}"
                    + (f", {lobyo:+.2%} without its best year)" if lobyo is not None else ")"))
    if life:
        return "admit", "sign of life: " + "; ".join(life)
    s60 = ss.get(60) or {}
    if all((row.get("vs_pool") or 0) == 0 for row in ss.values()):
        return "reject", "signal study could not measure (signals = pool); backtest showed no edge either"
    return "reject", (f"no edge: 60d {(s60.get('vs_pool') or 0):+.2%} vs pool (t_adj {(s60.get('t_vs_pool_adj') or 0):.2f})"
                      + (f"; backtest without its best year {lobyo:+.2%}" if lobyo is not None else ""))


def leave_best_year_out(by_year: list[dict]) -> float | None:
    """Average excess per trade after dropping the single best year (one great year can carry a whole backtest:
    insider_dip_quality, 2020, lab round 1). None if fewer than 3 years."""
    yrs = [y for y in by_year if (y.get("trades") or 0) > 0 and y.get("avg_excess") is not None]
    if len(yrs) < 3:
        return None
    best = max(yrs, key=lambda y: y["avg_excess"])
    rest = [y for y in yrs if y is not best]
    n = sum(y["trades"] for y in rest)
    return sum(y["avg_excess"] * y["trades"] for y in rest) / n if n else None


def live_stats(md: str | None = None) -> dict[str, dict]:
    from core.execution.run import mode
    md = md or mode()
    rows = query("""SELECT strategy, count(*) n, avg((pnl > 0)::int) win,
                           avg((exit_price/entry_price - 1) - (spy_exit/NULLIF(spy_entry,0) - 1)) ex,
                           stddev_samp((exit_price/entry_price - 1) - (spy_exit/NULLIF(spy_entry,0) - 1)) sd
                    FROM positions_book WHERE mode=%s AND status='closed' GROUP BY strategy""", (md,))
    out = {}
    for r in rows:
        n, ex, sd = int(r["n"]), float(r["ex"] or 0), float(r["sd"] or 0)
        out[r["strategy"]] = {"closed": n, "win_rate": float(r["win"] or 0), "avg_excess": ex,
                              "t": ex / (sd / math.sqrt(n)) if n > 2 and sd > 0 else 0.0}
    for r in query("SELECT strategy, count(*) n FROM positions_book WHERE mode=%s AND status='open' GROUP BY 1", (md,)):
        out.setdefault(r["strategy"], {})["open"] = int(r["n"])
    return out


def strategy_files() -> dict[str, tuple[str, Path]]:
    """name → (stage, path) for every strategy file in every stage folder."""
    out = {}
    for st in ("experimental", "paper", "promoted", "retired"):
        for p in sorted((ROOT / "strategies" / st).glob("*.py")):
            if not p.name.startswith("_"):
                out[p.stem] = (st, p)
    return out


def move(name: str, to_stage: str, reason: str, evidence: dict | None = None, src: Path | None = None) -> Path:
    files = strategy_files()
    from_stage, path = files.get(name, (None, src))
    if path is None:
        raise FileNotFoundError(name)
    dest = ROOT / "strategies" / to_stage / f"{name}.py"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), dest)
    execute("INSERT INTO strategy_moves (strategy, from_stage, to_stage, reason, evidence) VALUES (%s,%s,%s,%s,%s)",
            (name, from_stage or "candidate", to_stage, reason, json.dumps(evidence or {}, default=str)))
    execute("UPDATE ideas SET status=%s, code_path=%s, updated_at=now() WHERE name=%s",
            ({"experimental": "live", "paper": "promoted", "retired": "retired"}.get(to_stage, to_stage),
             str(dest.relative_to(ROOT)), name))
    event("lab", f"{name}: {from_stage or 'candidate'} → {to_stage} ({reason[:160]})")
    return dest


def _latest_train(name: str) -> dict | None:
    r = query("""SELECT metrics FROM backtest_runs WHERE strategy=%s AND period='train' ORDER BY id DESC LIMIT 1""", (name,))
    return r[0]["metrics"] if r else None


def _evidence_score(name: str, live: dict) -> float:
    """For the cap: live t-stat once there are ≥ 10 closed trades, else the train backtest t-stat."""
    lv = live.get(name) or {}
    if (lv.get("closed") or 0) >= 10:
        return float(lv["t"])
    m = _latest_train(name) or {}
    return float(m.get("t_excess") or 0.0)


def retire_decayed(live: dict) -> list[str]:
    out = []
    for name, (st, _p) in strategy_files().items():
        lv = live.get(name) or {}
        if st in ("experimental", "paper", "promoted") and (lv.get("closed") or 0) >= 15 \
                and lv["avg_excess"] < 0 and lv["t"] < -1.5:
            move(name, "retired", f"live decay: {lv['closed']} closed trades, {lv['avg_excess']:+.2%} vs SPY per trade "
                                  f"(t {lv['t']:.2f})", lv)
            out.append(name)
    return out


def enforce_cap(live: dict, protect: set[str]) -> list[str]:
    files = {n: st for n, (st, _p) in strategy_files().items() if st in ("experimental", "paper")}
    recent = {r["strategy"] for r in query("SELECT strategy FROM strategy_moves WHERE to_stage IN ('experimental','paper') "
                                           "AND ts > now() - %s * interval '1 day'", (MIN_LIVE_DAYS * 7 // 5,))}
    out = []
    while len(files) > MAX_ACTIVE:
        pool = [n for n in files if n not in protect and n not in recent]
        if not pool:
            break
        worst = min(pool, key=lambda n: _evidence_score(n, live))
        move(worst, "retired", f"cap of {MAX_ACTIVE} live strategies: weakest evidence "
                               f"(score {_evidence_score(worst, live):.2f})", live.get(worst) or {})
        files.pop(worst)
        out.append(worst)
    return out


# ── context for Opus ─────────────────────────────────────────────────────────────────────────────────────────────
def feature_catalog() -> str:
    from core.features import earnings, fundamentals, news, price, releases
    lines = []
    for mod in (price, earnings, fundamentals, news, releases):
        for k, v in mod.FEATURES.items():
            lines.append(f"- `{k}`: {v}")
    return "\n".join(lines)


def _tail(path: Path, n: int) -> str:
    return path.read_text()[-n:] if path.exists() else "(empty)"


def strategies_overview(live: dict) -> list[dict]:
    from core.strategy.base import load_file
    out = []
    ideas = {r["name"]: r for r in query("SELECT name, results, verdict FROM ideas")}
    for name, (st, path) in strategy_files().items():
        try:
            cls = load_file(path, st)[0]
            desc, hyp, params = cls.description, cls.hypothesis, cls.params
        except Exception as e:                                          # noqa: BLE001
            desc, hyp, params = f"(failed to load: {e})", "", {}
        m = _latest_train(name) or {}
        idea = ideas.get(name) or {}
        ss = {r["horizon_days"]: r for r in (idea.get("results") or {}).get("signal_study", [])}
        out.append({"name": name, "stage": st, "description": desc, "hypothesis": hyp[:400], "params": params,
                    "train_backtest": {k: m.get(k) for k in ("trades", "avg_excess", "t_excess", "excess_vs_twin",
                                                             "t_vs_twin", "win_rate", "avg_hold_days", "passed")},
                    "signal_study_60d": {k: (ss.get(60) or {}).get(k) for k in ("vs_pool", "t_vs_pool_adj", "signals")} if ss else None,
                    "live": live.get(name), "verdict": idea.get("verdict")})
    return out


PROPOSER = """You run the idea lab of a personal research system that trades US stocks for multi-week to multi-month
holds (currently simulated/paper money: wrong bets are fine, learning is the goal). Your job each round: propose new,
TESTABLE, number-based strategy ideas (or variations of existing ones) that use only the listed daily features, and say
which missing data would unlock better ideas.

Principles:
- Learn from the notebook and from every strategy's results: don't repeat failed ideas; vary what showed a sign of
  life; explain the expected mechanism (who is on the other side of the trade and why the edge should persist).
- The user's direction: price-only ideas are weak. AT MOST ONE idea per round may use price/volume features alone;
  every other idea must use non-price evidence: earnings (surprise, reaction, timing), SEC data (fundamentals, insider
  buying), or news (tone, events). Earnings-driven ideas (post-earnings drift, guidance, reactions) are the priority.
  Note coverage: news labels exist only for recent weeks (history backtests will see few signals); earnings-surprise
  history is still sparse; fundamentals and insider data cover 2016+. Mix: some bold, some careful variations.
- Each idea needs a clear entry rule, a ranking score, a stop, and an exit/holding time. Multi-week horizons.
- Rules must be computable from the feature arrays at day t only (no future data). No AI judgment inside rules.
- Names: short snake_case, new (not in the existing list). Hypothesis is written BEFORE testing: say what result would
  prove it wrong.
- Feature requests: data or features we don't have yet that would make ideas possible (e.g. 'analyst estimate
  revisions', 'short interest'); say how to compute them and the likely source."""

PROPOSE_SCHEMA = {"type": "object", "properties": {
    "thinking_md": {"type": "string", "description": "what you looked at and why these ideas (plain language, short)"},
    "ideas": {"type": "array", "items": {"type": "object", "properties": {
        "name": {"type": "string"}, "title": {"type": "string"}, "kind": {"type": "string", "enum": ["new", "variant"]},
        "parent": {"type": "string"}, "hypothesis": {"type": "string"},
        "rules": {"type": "string", "description": "precise rules: eligibility, score, stop, target/trailing, max hold, "
                                                   "earnings handling, features used"}},
        "required": ["name", "title", "kind", "hypothesis", "rules"]}},
    "feature_requests": {"type": "array", "items": {"type": "object", "properties": {
        "feature": {"type": "string"}, "why": {"type": "string"}, "how": {"type": "string"}},
        "required": ["feature", "why", "how"]}}},
    "required": ["thinking_md", "ideas", "feature_requests"]}

BUILDER = """You write one Python strategy file for a backtesting + live trading system. Output ONLY the file content
in the `code` field. The file is checked by a strict validator, then run on real data.

Interface (subclass FeatureStrategy from core.strategy.base; the same code runs in backtests and live):
- class attributes: name (given), version = "1", description (plain language, what it looks for), hypothesis (why it
  might work, as given), params = {...} (all tunable numbers), optional: needs_fundamentals = True if it uses any
  fundamentals/insider/surprise feature, min_adv (dollars/day, default 1_000_000), max_new_per_day (default 3),
  holds_through_earnings = False.
- self.f[name][t] → numpy array with one value per stock for day t (NaN = unknown). self.x(name, t) is the same.
  self.m.close / open / high / low / volume / dollar_volume are (days × stocks) arrays; self.m.symbols the tickers.
  Day t is the decision day (after the close). NEVER read index t+1 or later; slices may end at t+1 (exclusive).
- eligible(self, t) → bool array. Start from super().eligible(t) (common stock, price ≥ $5, liquid) and AND your
  filters. Use earnings_clear(self.f, t) to skip stocks reporting within 2 weeks (required unless the idea is about
  holding through earnings).
- score(self, t) → float array: NaN = not a candidate; higher = better. Vectorized numpy only (no Python loops over
  stocks: ~9,000 stocks × 1,750 days must run in minutes).
- plan(self, t, j) → Signal(self.m.symbols[j], stop=<price below close>, target=None or price, trail_pct=None or
  e.g. 0.12, max_hold=<trading days>, tag=self.name). Entry is the next open.
- optional: exits(self, t, m, held) → list of held symbols to sell at the next open; why(self, t, j) → short text;
  helper_* methods.
- Allowed imports ONLY: numpy as np, math, `from core.backtest.engine import Signal`,
  `from core.strategy.base import FeatureStrategy, earnings_clear, atr_stop` (atr_stop(price, atr_pct, mult=2.0,
  floor=0.04, cap=0.15) → stop price). No file/network/OS access, no while loops, no getattr, no print, no dunder names.
  `with np.errstate(invalid="ignore"):` is allowed around comparisons with NaN.
- Exactly one class. Module docstring: one line on the idea.

Example of a complete, valid file:
```python
{example}
```"""


def _ask_build(idea: dict, error: str | None, previous: str | None, task_id: int) -> str:
    example = (ROOT / "strategies" / "experimental" / "insider_cluster.py")
    example = example if example.exists() else next((ROOT / "strategies").rglob("insider_cluster.py"))
    system = BUILDER.replace("{example}", example.read_text())
    prompt = (f"Strategy name: {idea['name']}\nTitle: {idea['title']}\nHypothesis: {idea['hypothesis']}\n\n"
              f"Rules:\n{idea['rules']}\n\nAvailable features:\n{feature_catalog()}\n")
    if error:
        prompt += f"\n\nYour previous version failed with this error. Fix it.\nERROR:\n{error}\n\nPREVIOUS CODE:\n{previous}\n"
    ans = claude.ask(prompt, model="sonnet", purpose="lab.build", system=system, timeout=600, task_id=task_id,
                     schema={"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]})
    code = ans.data["code"].strip()
    if code.startswith("```"):
        code = code.split("\n", 1)[1].rsplit("```", 1)[0]
    return code + "\n"


def _build(idea: dict, task_id: int, error: str | None = None) -> bool:
    """Write lab/candidates/<name>.py; True if it passes the static validator."""
    CANDIDATES.mkdir(parents=True, exist_ok=True)
    path = CANDIDATES / f"{idea['name']}.py"
    previous = path.read_text() if path.exists() else None
    for _ in range(BUILD_TRIES):
        code = _ask_build(idea, error, previous, task_id)
        execute("UPDATE ideas SET build_attempts = build_attempts + 1, updated_at=now() WHERE id=%s", (idea["id"],))
        try:
            validate(code, idea["name"])
        except Rejected as e:
            error, previous = f"validator: {e}", code
            continue
        path.write_text(code)
        execute("UPDATE ideas SET status='built', code_path=%s, build_error=NULL, updated_at=now() WHERE id=%s",
                (str(path.relative_to(ROOT)), idea["id"]))
        return True
    execute("UPDATE ideas SET status='build_failed', build_error=%s, updated_at=now() WHERE id=%s", (error, idea["id"]))
    return False


def _subprocess(cmd: str, files: list[Path], timeout: int) -> dict:
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        out = Path(tf.name)
    p = subprocess.run([sys.executable, "-m", "core.lab.auto", cmd, "--files", *map(str, files), "--out", str(out)],
                       cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    try:
        res = json.loads(out.read_text()) if out.stat().st_size else {}
    finally:
        out.unlink(missing_ok=True)
    if not res:
        raise RuntimeError(f"lab {cmd} produced no result (exit {p.returncode}): {p.stderr[-800:]}")
    return res


def _commit(message: str) -> None:
    """Commit ONLY the lab's own folders (never anything else in the working tree), then push. Best effort."""
    try:
        paths = ["strategies", "lab", "reports/lab"]
        subprocess.run(["git", "add", "-A", "--", *paths], cwd=ROOT, capture_output=True, timeout=60)
        r = subprocess.run(["git", "commit", "-m", message + "\n\nAutomated by the idea lab (core/jobs/lab.py).",
                            "--", *paths], cwd=ROOT, capture_output=True, text=True, timeout=60)
        if r.returncode == 0:
            subprocess.run(["git", "push", "-q"], cwd=ROOT, capture_output=True, timeout=120)
    except Exception as e:                                              # noqa: BLE001
        event("lab", f"git commit skipped: {e}", level="warn")


REPORTER = """You write the round report of a strategy idea lab for a reader who is learning investing (plain language,
explain terms briefly). For each idea: what it tested, the result in numbers, the decision and why, and what we
learned. Be honest about noise: a t-stat below ~2 is weak evidence, and every extra test raises the bar. Then list
lessons that are concrete and testable (they're appended to the lab notebook, which the next round reads)."""

REPORT_SCHEMA = {"type": "object", "properties": {
    "report_md": {"type": "string"},
    "lessons": {"type": "array", "items": {"type": "object", "properties": {
        "lesson": {"type": "string"}, "evidence": {"type": "string"}, "suggested_test": {"type": "string"}},
        "required": ["lesson", "evidence", "suggested_test"]}}},
    "required": ["report_md", "lessons"]}


@task("lab.baseline", resource="lab", priority=30,
      description="Re-test every live strategy with the current measurement code (after a lab-tool fix)")
def baseline(ctx: TaskContext) -> dict:
    """Same strategy versions, fixed measuring tools: results replace the old ones in `ideas` (hand-written
    strategies get an ideas row with source='human'). Not new tries, so the multiple-testing count doesn't rise."""
    from core.strategy.base import load_file
    live = {n: p for n, (st, p) in strategy_files().items() if st in ("experimental", "paper", "promoted")}
    have = {r["name"] for r in query("SELECT name FROM ideas")}
    for name, path in live.items():
        if name not in have:
            cls = load_file(path, "experimental")[0]
            execute("""INSERT INTO ideas (source, name, title, hypothesis, rules, status, code_path)
                       VALUES ('human', %s, %s, %s, %s, 'live', %s)""",
                    (name, cls.description[:120], cls.hypothesis or "(none written)", cls.description,
                     str(path.relative_to(ROOT))))
    res = _subprocess("test", list(live.values()), timeout=4 * 3600)
    out = {}
    for name in live:
        r = res.get(name, {"ok": False, "error": "no result"})
        dec, why = decide(r)
        execute("UPDATE ideas SET results = results || %s, updated_at=now() WHERE name=%s",
                (json.dumps({"test": r, "baseline_decision": f"{dec}: {why}", "baseline_at": str(date.today())}), name))
        out[name] = f"{dec}: {why}"
    return {"summary": f"baseline re-test of {len(live)} live strategies", "decisions": out}


@task("lab.cycle", resource="lab", priority=30, description="Idea lab round: propose → build → test → admit/retire → report")
def cycle(ctx: TaskContext) -> dict:
    n_ideas = int(ctx.payload.get("ideas", 4))
    live = live_stats()
    rnd = query("SELECT * FROM lab_rounds WHERE finished_at IS NULL AND started_at > now() - interval '3 days' "
                "ORDER BY id DESC LIMIT 1")
    if rnd:
        rid = rnd[0]["id"]
        ctx.log(f"resuming lab round {rid}")
    else:
        rid = query("INSERT INTO lab_rounds DEFAULT VALUES RETURNING id")[0]["id"]
    ctx.checkpoint(round=rid)
    summary = (rnd[0]["summary"] if rnd else {}) or {}

    # 1 ── decay monitor
    if "retired_decay" not in summary:
        summary["retired_decay"] = retire_decayed(live)
        execute("UPDATE lab_rounds SET summary=%s WHERE id=%s", (json.dumps(summary), rid))

    # 2 ── propose
    if not query("SELECT 1 FROM ideas WHERE round_id=%s LIMIT 1", (rid,)):
        tried = [r["name"] + f" ({r['status']}: {(r['verdict'] or '')[:80]})" for r in
                 query("SELECT name, status, verdict FROM ideas ORDER BY id")]
        ss = sorted((ROOT / "lab" / "experiments").glob("*signal-study*.md"))
        pack = {
            "strategies": strategies_overview(live),
            "ideas_tried_before": tried,
            "lab_notebook_recent": _tail(NOTEBOOK, 12000),
            "open_feature_requests": _tail(REQUESTS, 4000),
            "latest_signal_study_report": ss[-1].read_text()[:6000] if ss else None,
            "research_notes": (ROOT / "learning" / "12-what-research-says-about-strategies.md").read_text()[:7000],
            "multiple_testing": {"backtests_run_so_far": query("SELECT count(*) n FROM backtest_runs")[0]["n"]},
        }
        prompt = (f"Feature catalog (all available daily, point-in-time):\n{feature_catalog()}\n\n"
                  f"Lab state (JSON):\n{json.dumps(pack, default=str)}\n\nPropose {n_ideas} ideas for this round.")
        ans = claude.ask(prompt, model="opus", purpose="lab.propose", schema=PROPOSE_SCHEMA, system=PROPOSER,
                         timeout=1500, task_id=ctx.id)
        d = ans.data
        existing = set(strategy_files()) | {r["name"] for r in query("SELECT name FROM ideas")}
        added = 0
        for idea in d["ideas"][: n_ideas + 2]:
            name = "".join(ch for ch in idea["name"].lower().replace("-", "_").replace(" ", "_") if ch.isalnum() or ch == "_")[:40]
            if not name or name in existing or not name[0].isalpha():
                continue
            existing.add(name)
            execute("""INSERT INTO ideas (round_id, name, title, kind, parent, hypothesis, rules)
                       VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                    (rid, name, idea["title"], idea.get("kind", "new"), idea.get("parent") or None, idea["hypothesis"],
                     idea["rules"]))
            added += 1
        execute("UPDATE lab_rounds SET proposal_md=%s, feature_requests=%s WHERE id=%s",
                (d["thinking_md"], json.dumps(d["feature_requests"]), rid))
        if d["feature_requests"]:
            if not REQUESTS.exists():
                REQUESTS.write_text("# Feature requests from the idea lab\n\nWritten by Opus each round; the weekly "
                                    "engineer builds them (core/lab/engineer.py) and marks them done.\n")
            with REQUESTS.open("a") as f:
                f.write(f"\n## Round {rid} ({date.today()})\n" + "".join(
                    f"- [ ] **{x['feature']}**: {x['why']} *How:* {x['how']}\n" for x in d["feature_requests"]))
        ctx.log(f"lab round {rid}: {added} ideas proposed, {len(d['feature_requests'])} feature requests")

    # 3 ── build
    for idea in query("SELECT * FROM ideas WHERE round_id=%s AND status='proposed' ORDER BY id", (rid,)):
        _build(idea, ctx.id)

    # 4 ── smoke (+ up to 2 repair rounds)
    for attempt in range(3):
        built = query("SELECT * FROM ideas WHERE round_id=%s AND status='built' AND NOT (results ? 'smoke_ok') ORDER BY id", (rid,))
        if not built:
            break
        res = _subprocess("smoke", [ROOT / b["code_path"] for b in built], timeout=1800)
        for b in built:
            r = res.get(b["name"], {"ok": False, "error": "no smoke result"})
            if r.get("ok"):
                execute("UPDATE ideas SET results = results || %s, updated_at=now() WHERE id=%s",
                        (json.dumps({"smoke_ok": True, "smoke": r}), b["id"]))
            elif attempt < 2:
                _build(b, ctx.id, error=f"{r.get('error')}\n{r.get('trace', '')}")
            else:
                execute("UPDATE ideas SET status='build_failed', build_error=%s, updated_at=now() WHERE id=%s",
                        (r.get("error"), b["id"]))

    # 5 ── train test (heavy: one process loads 2016–2022 for ~9,000 stocks once and tests every candidate)
    ready = query("SELECT * FROM ideas WHERE round_id=%s AND status='built' AND results ? 'smoke_ok' ORDER BY id", (rid,))
    if ready:
        ctx.log(f"lab round {rid}: train-testing {len(ready)} strategies")
        res = _subprocess("test", [ROOT / b["code_path"] for b in ready], timeout=4 * 3600)
        for b in ready:
            r = res.get(b["name"], {"ok": False, "error": "no test result"})
            execute("UPDATE ideas SET status='tested', results = results || %s, updated_at=now() WHERE id=%s",
                    (json.dumps({"test": r}), b["id"]))

    # 6 ── decide
    to_validate, admitted, rejected = [], [], []
    for b in query("SELECT * FROM ideas WHERE round_id=%s AND status='tested' ORDER BY id", (rid,)):
        r = (b["results"] or {}).get("test", {})
        dec, why = decide(r)
        if dec == "validate":
            to_validate.append((b, why))
            continue
        path = ROOT / b["code_path"]
        if dec == "admit":
            move(b["name"], "experimental", why, {"signal_study": r.get("signal_study"), "backtest": r.get("backtest")}, src=path)
            admitted.append(b["name"])
        else:
            move(b["name"], "retired", why, {"signal_study": r.get("signal_study")}, src=path)
            execute("UPDATE ideas SET status='rejected' WHERE id=%s", (b["id"],))
            rejected.append(b["name"])
        execute("UPDATE ideas SET verdict=%s WHERE id=%s", (f"{dec}: {why}", b["id"]))
    if to_validate:
        res = _subprocess("validate", [ROOT / b["code_path"] for b, _ in to_validate], timeout=2 * 3600)
        for b, why in to_validate:
            v = res.get(b["name"], {})
            stage = "paper" if v.get("passed_validate") else "experimental"
            note = (f"{why}; unseen 2023–2024: {'PASSED' if v.get('passed_validate') else 'not passed'} "
                    f"({(v.get('avg_excess') or 0):+.2%}/trade, {v.get('trades')} trades)")
            move(b["name"], stage, note, {"validate": v}, src=ROOT / b["code_path"])
            execute("UPDATE ideas SET verdict=%s, results = results || %s WHERE id=%s",
                    (f"{'promote' if stage == 'paper' else 'admit'}: {note}", json.dumps({"validate": v}), b["id"]))
            admitted.append(b["name"])
    for b in query("SELECT * FROM ideas WHERE round_id=%s AND status='build_failed'", (rid,)):
        execute("UPDATE ideas SET verdict=%s WHERE id=%s AND verdict IS NULL", (f"build failed: {(b['build_error'] or '')[:200]}", b["id"]))
    capped = enforce_cap(live, protect=set(admitted))

    # 7 ── report
    rows = query("SELECT name, title, kind, parent, hypothesis, rules, status, verdict, build_error, results FROM ideas "
                 "WHERE round_id=%s ORDER BY id", (rid,))
    for r in rows:
        t = (r["results"] or {}).get("test") or {}
        r["results"] = {"signal_study": t.get("signal_study"), "backtest": t.get("backtest"), "gates": t.get("gates"),
                        "validate": (r["results"] or {}).get("validate")}
    pack = {"round": rid, "ideas": rows, "retired_for_decay": summary.get("retired_decay"), "retired_for_cap": capped,
            "live_strategies_now": [n for n, (st, _) in strategy_files().items() if st in ("experimental", "paper")]}
    ans = claude.ask(f"Lab round results (JSON):\n{json.dumps(pack, default=str)}\n\nWrite the round report.",
                     model="opus", purpose="lab.report", schema=REPORT_SCHEMA, system=REPORTER, timeout=1200, task_id=ctx.id)
    d = ans.data
    path = ROOT / "reports" / "lab" / f"{date.today()}-round-{rid}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# Idea lab round {rid} ({date.today()})\n\n{d['report_md']}\n\n## Lessons\n" + "".join(
        f"- **{x['lesson']}** Evidence: {x['evidence']}. Test: {x['suggested_test']}\n" for x in d["lessons"]))
    if not NOTEBOOK.exists():
        NOTEBOOK.write_text("# Lab notebook\n\nLessons from trade reviews and experiments, newest last. The idea lab reads "
                            "this before proposing new tests, so failures are never repeated blindly.\n")
    with NOTEBOOK.open("a") as f:
        f.write(f"\n## Lab round {rid} ({date.today()})\n" + "".join(
            f"- {r['name']}: {r['verdict'] or r['status']}\n" for r in rows) + "".join(
            f"- Lesson: {x['lesson']} *(evidence: {x['evidence']}; test: {x['suggested_test']})*\n" for x in d["lessons"]))
    summary.update({"admitted": admitted, "rejected": rejected, "retired_cap": capped,
                    "build_failed": [r["name"] for r in rows if r["status"] == "build_failed"]})
    execute("UPDATE lab_rounds SET finished_at=now(), report_md=%s, summary=%s WHERE id=%s",
            (d["report_md"], json.dumps(summary), rid))
    _commit(f"lab round {rid}: admitted {', '.join(admitted) or 'none'}; rejected {len(rejected)}")
    if admitted or capped or summary.get("retired_decay"):
        from core.tasks import queue
        queue.enqueue("strategies.plan", {}, priority=55, dedupe_key="strategies.plan")   # re-plan with the new set
    return {"summary": f"lab round {rid}: {len(rows)} ideas → admitted {admitted or 'none'}, rejected {len(rejected)}, "
                       f"build failed {len(summary['build_failed'])}, retired {capped + summary['retired_decay']}",
            "round": rid}
