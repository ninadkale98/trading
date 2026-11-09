"""The weekly engineer: Claude Code (Opus) improving the SYSTEM itself, the second level of the self-improving loop.

The idea lab can only write strategy files. When it needs data or features we don't have, it writes a feature request
(lab/requests.md). Once a week the engineer picks the most valuable item (feature requests, recurring errors, trade
review lessons, open build-plan items), implements it on its own git branch in a separate worktree OUTSIDE the repo,
writes tests and commits there. Then FIXED checks run (not the AI):

  • protected paths untouched (money, risk, gates, the checks themselves, secrets, services, strategies)
  • no file deleted, no existing migration edited
  • full test suite passes; every live strategy still passes the smoke check
  • if features changed: the feature look-ahead check passes (values for day t don't change when later days are removed)

**Nothing is merged automatically.** System code changes are reviewed first: the run ends as `ready` (all checks
green) or `needs_review` (a check failed), with a report in reports/engineer/. The user says "merge engineer #N" in
chat (→ `tradebot engineer-merge N`), or "reject engineer #N". Merging rebases onto main, re-runs the tests, fast-
forwards main, pushes, and restarts the services.
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path

from core.config import ROOT
from core.db import execute, query
from core.log import event

WORKTREES = Path.home() / ".tradebot" / "worktrees"      # outside the repo, so edits to the repo itself can be denied
PY = ROOT / ".venv" / "bin" / "python"

PROTECTED = (
    "core/execution/", "core/planner/", "core/backtest/", "core/lab/", "core/jobs/lab.py", "core/jobs/engineer.py",
    "core/jobs/trading.py", "core/ai/claude.py", "core/ingest/alpaca.py", "core/config.py", "core/daemon.py",
    "core/db/__init__.py", "core/tasks/", "config/", "scripts/", "pyproject.toml", "CLAUDE.md", ".env", ".gitignore",
    "tests/test_trading.py", "tests/test_lab.py", "strategies/",
)

SYSTEM = """You are the weekly ENGINEER of an automated stock research and paper-trading system (repo in the current
directory, a git worktree on its own branch). The system's goal: understand the market and find strategies that work
for multi-week holds. The user is learning; docs are plain language. Read CLAUDE.md, docs/architecture.md and
docs/build-plan.md first.

Your job this session: pick ONE improvement (two only if both are small) with the biggest value, implement it fully,
test it, document it, and commit it on the current branch. Your branch is reviewed before it's merged. Sources, in
rough priority: open feature requests from the idea lab (they unlock new strategy ideas), recurring errors, lessons
from trade reviews, open build-plan items.

Rules (fixed checks run after you):
- Commit on the current branch only. Never push, merge, rebase, switch branches, restart services or run launchctl.
- Do not edit these protected paths (money, risk, gates, the checks, services, strategies): {protected}
  If the best fix needs one, write the proposal in your summary instead and pick something else to build.
- Never delete files; never edit an existing migration (add a new numbered one in core/db/migrations/ if needed).
- New features must be point-in-time: the value for day t may use only data known by the close of day t (filing and
  report dates, not period-end dates). An automatic check recomputes features with later days removed.
- New features go in core/features/ with a plain-language entry in that module's FEATURES dict (that's how the lab
  learns they exist); new data loaders as tasks in core/jobs/ (+ core/schedules.py), respecting each source's limits.
- Database: for exploring use read-only queries (psql "$TRADEBOT_RO_DSN"). Never modify or delete stored data.
  Never read .env or print secrets. No broker or order actions of any kind.
- Run the tests with: PYTHONPATH=$PWD {py} -m pytest -q   (all must pass). Add tests for what you build.
- Keep docs in sync per CLAUDE.md (architecture, build-plan build log, learning/ + glossary for new concepts), and
  tick the feature request in lab/requests.md ([x] with a note) when you build one.
- Finish within about an hour of work. End your final message with a section starting with the line `SUMMARY:` that
  explains to the user in plain language what you built, why, how it was tested, and anything a reviewer should check."""


def _git(*args, cwd: Path = ROOT, check: bool = True, timeout: int = 120) -> str:
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if check and p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {p.stderr.strip()[:400]}")
    return p.stdout.strip()


def brief() -> str:
    """Everything the engineer should weigh, assembled fresh each week."""
    req = ROOT / "lab" / "requests.md"
    open_req = [ln for ln in req.read_text().splitlines() if ln.startswith("- [ ]")] if req.exists() else []
    errors = query("""SELECT kind, left(message, 200) msg, count(*) n FROM events
                      WHERE level='error' AND ts > now() - interval '7 days' GROUP BY 1, 2 ORDER BY n DESC LIMIT 15""")
    failed = query("""SELECT type, left(coalesce(last_error, ''), 200) err, count(*) n FROM tasks
                      WHERE status='failed' AND finished_at > now() - interval '7 days' GROUP BY 1, 2 ORDER BY n DESC LIMIT 10""")
    review = query("SELECT week_start, lessons FROM trade_reviews ORDER BY week_start DESC LIMIT 2")
    past = query("SELECT id, started_at::date d, status, goal FROM engineer_runs ORDER BY id DESC LIMIT 8")
    plan = (ROOT / "docs" / "build-plan.md").read_text()
    open_items = [ln.strip() for ln in plan.splitlines() if ln.strip().startswith("- [ ]")][:40]
    nb = ROOT / "lab" / "notebook.md"
    return "\n".join([
        "# This week's engineer brief", "",
        "## Open feature requests from the idea lab", *(open_req or ["(none)"]), "",
        "## Errors in the last 7 days (kind | message | count)",
        *([f"- {e['kind']} | {e['msg']} | {e['n']}" for e in errors] or ["(none)"]), "",
        "## Failed tasks in the last 7 days", *([f"- {f['type']}: {f['err']} ({f['n']}×)" for f in failed] or ["(none)"]), "",
        "## Latest trade-review lessons", json.dumps(review, default=str)[:4000], "",
        "## Lab notebook (recent)", nb.read_text()[-5000:] if nb.exists() else "(empty)", "",
        "## Open build-plan items (first 40)", *open_items, "",
        "## Previous engineer runs (don't redo these; unmerged ones are still waiting for review)",
        *([f"- #{p['id']} {p['d']} {p['status']}: {p['goal']}" for p in past] or ["(none)"]),
    ])


def _run_claude(wt: Path, prompt: str) -> str:
    from core.ai.claude import _LIMIT, CLAUDE, _limit_until, _log
    from core.tasks.errors import ResourceLimited
    settings = {"permissions": {"deny": [
        f"Edit({ROOT}/**)", f"Write({ROOT}/**)", "Read(**/.env)", "Read(**/.env.*)",
        "Bash(git push:*)", "Bash(git merge:*)", "Bash(git rebase:*)", "Bash(git checkout:*)", "Bash(git switch:*)",
        "Bash(git reset:*)", "Bash(launchctl:*)", "Bash(sudo:*)", "Bash(curl:*)", "Bash(wget:*)", "Bash(rm -rf:*)",
        "Bash(tradebot approve:*)", "Bash(tradebot reject:*)", "WebFetch"]}}
    env = {**os.environ, "PYTHONPATH": str(wt), "TRADEBOT_ENGINEER": "1",
           "TRADEBOT_RO_DSN": os.environ.get("TRADEBOT_RO_DSN", "postgresql:///market?user=tradebot_ro")}
    cmd = [CLAUDE, "-p", "--model", "opus", "--output-format", "json", "--no-session-persistence", "--strict-mcp-config",
           "--append-system-prompt", SYSTEM.replace("{protected}", ", ".join(PROTECTED)).replace("{py}", str(PY)),
           "--permission-mode", "acceptEdits", "--allowedTools", "Read,Edit,Write,Glob,Grep,Bash,WebSearch",
           "--settings", json.dumps(settings), "--max-budget-usd", "40"]
    t0 = datetime.now(timezone.utc)
    try:
        p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=2 * 3600, cwd=wt, env=env)
    except subprocess.TimeoutExpired:
        return "(engineer session timed out after 2 hours)"
    ms = int((datetime.now(timezone.utc) - t0).total_seconds() * 1000)
    try:
        d = json.loads(p.stdout) if p.stdout.strip() else {}
    except json.JSONDecodeError:
        d = {}
    text = str(d.get("result") or p.stderr[-2000:] or "")
    bad = p.returncode != 0 or bool(d.get("is_error"))
    _log("engineer.weekly", "opus", not bad, d.get("usage") or {}, float(d.get("total_cost_usd") or 0), ms,
         text[:400] if bad else None)
    if bad and _LIMIT.search(text):
        raise ResourceLimited("claude:opus", _limit_until(text), f"engineer: {text[:160]}")
    return text


def checks(wt: Path, changed: list[str], deleted: list[str]) -> dict:
    env = {**os.environ, "PYTHONPATH": str(wt)}
    out: dict = {}
    prot = [f for f in changed + deleted if any(f == p.rstrip("/") or f.startswith(p) for p in PROTECTED)]
    out["protected_paths"] = {"ok": not prot, "files": prot}
    mig_edit = [f for f in changed if f.startswith("core/db/migrations/")          # existed on main = edited, not added
                and subprocess.run(["git", "cat-file", "-e", f"main:{f}"], cwd=wt, capture_output=True).returncode == 0]
    out["no_deletes_or_migration_edits"] = {"ok": not deleted and not mig_edit, "deleted": deleted,
                                            "migrations_edited": mig_edit}
    t = subprocess.run([str(PY), "-m", "pytest", "-q", "-x"], cwd=wt, env=env, capture_output=True, text=True, timeout=1800)
    out["tests"] = {"ok": t.returncode == 0, "tail": (t.stdout + t.stderr)[-1500:]}
    strategies = sorted(str(p) for st in ("experimental", "paper", "promoted") for p in (wt / "strategies" / st).glob("*.py"))
    s = subprocess.run([str(PY), "-m", "core.lab.auto", "smoke", "--files", *strategies], cwd=wt, env=env,
                       capture_output=True, text=True, timeout=1800)
    try:
        sm = json.loads(s.stdout[s.stdout.index("{"):])
        bad = {k: v.get("error") for k, v in sm.items() if not v.get("ok")}
    except ValueError:
        bad = {"(smoke)": (s.stderr or s.stdout)[-600:]}
    out["strategies_smoke"] = {"ok": not bad, "failed": bad}
    if any(f.startswith("core/features/") for f in changed):
        la = subprocess.run([str(PY), "-m", "core.lab.auto", "features-lookahead"], cwd=wt, env=env,
                            capture_output=True, text=True, timeout=3600)
        try:
            out["features_lookahead"] = json.loads(la.stdout[la.stdout.index("{"):])
        except ValueError:
            out["features_lookahead"] = {"ok": False, "problems": [(la.stderr or la.stdout)[-600:]]}
    return out


def _remove_worktree(wt: Path) -> None:
    if wt.exists():
        subprocess.run(["git", "worktree", "remove", "--force", str(wt)], cwd=ROOT, capture_output=True)
    subprocess.run(["git", "worktree", "prune"], cwd=ROOT, capture_output=True)


def run_week() -> dict:
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    branch = f"auto/engineer-{stamp}"
    wt = WORKTREES / branch.replace("/", "-")
    WORKTREES.mkdir(parents=True, exist_ok=True)
    _git("worktree", "add", "-b", branch, str(wt), "main")
    rid = query("INSERT INTO engineer_runs (branch) VALUES (%s) RETURNING id", (branch,))[0]["id"]
    try:
        text = _run_claude(wt, brief() + "\n\nStart now.")
        if _git("status", "--porcelain", cwd=wt):       # anything left uncommitted is committed for review
            _git("add", "-A", cwd=wt)
            _git("commit", "-qm", "engineer: uncommitted work at session end", cwd=wt, check=False)
        changed = [x for x in _git("diff", "--name-only", "--diff-filter=AMR", f"main...{branch}", cwd=wt).splitlines() if x]
        deleted = [x for x in _git("diff", "--name-only", "--diff-filter=D", f"main...{branch}", cwd=wt).splitlines() if x]
        summary = text.split("SUMMARY:", 1)[-1].strip() if "SUMMARY:" in text else text[-3000:]
        goal = summary.splitlines()[0][:300] if summary else ""
        if not changed and not deleted:
            status, chk = "no_change", {}
        else:
            chk = checks(wt, changed, deleted)
            status = "ready" if all(v.get("ok") for v in chk.values()) else "needs_review"
        failed = [k for k, v in chk.items() if not v.get("ok")]
        execute("""UPDATE engineer_runs SET status=%s, goal=%s, summary_md=%s, files=%s, checks=%s, commit_sha=%s,
                   finished_at=now() WHERE id=%s""",
                (status, goal, summary, json.dumps(changed + deleted), json.dumps(chk, default=str),
                 _git("rev-parse", branch, cwd=wt), rid))
        path = ROOT / "reports" / "engineer" / f"{date.today()}-run-{rid}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# Engineer run #{rid} ({date.today()}): {status}\n\nBranch `{branch}` (not merged: say "
                        f"\"merge engineer #{rid}\" or \"reject engineer #{rid}\")\n\n"
                        f"Files: {', '.join(changed + deleted) or 'none'}\n\n"
                        + (f"**Checks that failed:** {', '.join(failed)}\n\n" if failed else "All automatic checks passed.\n\n")
                        + summary + "\n")
        event("engineer", f"run #{rid}: {status}, {len(changed)} files, waiting for review: {goal[:120]}",
              level="warn" if status == "needs_review" else "info")
        return {"summary": f"engineer run #{rid}: {status} (awaiting review); {goal[:160]}", "status": status,
                "branch": branch}
    except Exception:
        execute("UPDATE engineer_runs SET status='failed', finished_at=now() WHERE id=%s AND finished_at IS NULL", (rid,))
        raise
    finally:
        _remove_worktree(wt)                            # the branch keeps the work


def merge(run_id: int) -> str:
    """Run by the user (or by Claude in chat when the user says "merge engineer #N"): rebase onto main, re-test,
    fast-forward main, push, restart services."""
    r = query("SELECT * FROM engineer_runs WHERE id=%s", (run_id,))
    if not r:
        return f"no engineer run #{run_id}"
    branch = r[0]["branch"]
    if _git("rev-parse", "--abbrev-ref", "HEAD") != "main":
        return "main repo isn't on the main branch; switch first"
    if _git("status", "--porcelain", "--untracked-files=no"):
        return "main has uncommitted changes; commit or stash them first"
    wt = WORKTREES / (branch.replace("/", "-") + "-merge")
    _git("worktree", "add", str(wt), branch)
    try:
        if subprocess.run(["git", "rebase", "main"], cwd=wt, capture_output=True).returncode != 0:
            subprocess.run(["git", "rebase", "--abort"], cwd=wt, capture_output=True)
            return "rebase onto main hit conflicts; resolve by hand"
        t = subprocess.run([str(PY), "-m", "pytest", "-q", "-x"], cwd=wt, env={**os.environ, "PYTHONPATH": str(wt)},
                           capture_output=True, text=True, timeout=1800)
        if t.returncode != 0:
            return "tests fail after rebasing onto main:\n" + (t.stdout + t.stderr)[-1200:]
    finally:
        _remove_worktree(wt)
    _git("merge", "--ff-only", branch)
    _git("push", "-q", check=False, timeout=180)
    execute("UPDATE engineer_runs SET status='merged' WHERE id=%s", (run_id,))
    files = r[0]["files"] or []
    uid = os.getuid()
    if any(f.startswith("core/") or f.startswith("strategies/") for f in files):
        subprocess.run(["launchctl", "kickstart", "-k", f"gui/{uid}/com.ninad.tradebot"], capture_output=True)
    if any(f.startswith("dashboard/") for f in files):
        subprocess.run(["launchctl", "kickstart", "-k", f"gui/{uid}/com.ninad.tradebot.dashboard"], capture_output=True)
    event("engineer", f"run #{run_id} merged into main ({branch})")
    return f"merged {branch} into main and pushed; services restarted where needed"


def reject(run_id: int, reason: str = "") -> str:
    execute("UPDATE engineer_runs SET status='rejected', summary_md = coalesce(summary_md,'') || %s WHERE id=%s",
            (f"\n\nRejected: {reason}" if reason else "\n\nRejected.", run_id))
    return f"engineer run #{run_id} rejected (branch kept for reference)"
