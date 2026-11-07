"""Claude runner (architecture §12, build plan 3.1): every AI call in the system goes through `ask()`.

Runs headless Claude Code (`claude -p`) on the user's Max plan, with the model chosen per task:
  haiku  → bulk reading/labeling (news triage, fact extraction)
  sonnet → research, company maps, writing strategy code, the skeptic
  opus   → morning plan, evening market analysis, new ideas, conviction proposals

Failure handling (architecture §14): a usage limit pauses that model's queue (ResourceLimited) until it resets;
timeouts/crashes retry later; output that doesn't match the schema retries, then fails. Every call is logged in
`ai_usage`. A per-model daily budget (settings.yaml → ai.daily_budget_usd_equiv) keeps background jobs from
eating the whole plan; the user's own interactive use always has room.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from core.config import ROOT, settings
from core.db import execute, query
from core.tasks.errors import ResourceLimited, RetryLater

ET = ZoneInfo("America/New_York")
WORKDIR = ROOT / "data" / "claude_work"          # empty folder: no project instructions or files get loaded
CLAUDE = os.environ.get("CLAUDE_BIN", "/opt/homebrew/bin/claude")
DEFAULT_SYSTEM = ("You are a careful financial research assistant inside an automated system. Answer only from the "
                  "information given (and tools, if any). Be concise. When asked for JSON, follow the schema exactly.")


@dataclass
class Answer:
    data: dict | None        # structured output when a schema was given
    text: str
    usage: dict
    cost: float
    seconds: float


def resource(model: str) -> str:
    return f"claude:{model}"


def _budget(model: str) -> float | None:
    return (settings().get("ai", {}).get("daily_budget_usd_equiv") or {}).get(model)


def spent_today(model: str) -> float:
    start = datetime.now(ET).replace(hour=0, minute=0, second=0, microsecond=0)
    return float(query("SELECT coalesce(sum(cost_usd_equiv), 0) s FROM ai_usage WHERE model=%s AND ts >= %s",
                       (model, start))[0]["s"])


def _midnight_et() -> datetime:
    d = datetime.now(ET).date() + timedelta(days=1)
    return datetime(d.year, d.month, d.day, 0, 5, tzinfo=ET).astimezone(timezone.utc)


def _log(purpose, model, ok, usage, cost, ms, error=None, task_id=None):
    try:
        execute("""INSERT INTO ai_usage (task_id, purpose, model, ok, input_tokens, output_tokens, cache_read_tokens,
                                         cache_write_tokens, cost_usd_equiv, duration_ms, error)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (task_id, purpose, model, ok, usage.get("input_tokens"), usage.get("output_tokens"),
                 usage.get("cache_read_input_tokens"), usage.get("cache_creation_input_tokens"), cost, ms,
                 (error or "")[:500] or None))
    except Exception:        # logging must never break the call
        pass


_LIMIT = re.compile(r"usage limit|rate limit|limit reached|too many requests|overloaded|quota|credit balance", re.I)
_RESET = re.compile(r"resets? (?:at )?(\d{1,2})(?::(\d{2}))?\s*(am|pm)", re.I)


def _limit_until(msg: str) -> datetime:
    """Parse 'resets 3pm' style hints; otherwise wait an hour."""
    m = _RESET.search(msg or "")
    now = datetime.now(ET)
    if m:
        h = int(m.group(1)) % 12 + (12 if m.group(3).lower() == "pm" else 0)
        t = now.replace(hour=h, minute=int(m.group(2) or 0), second=0, microsecond=0)
        if t <= now:
            t += timedelta(days=1)
        return t.astimezone(timezone.utc) + timedelta(minutes=2)
    return datetime.now(timezone.utc) + timedelta(hours=1)


def ask(prompt: str, *, model: str = "haiku", purpose: str, schema: dict | None = None, system: str | None = None,
        tools: list[str] | None = None, timeout: int = 300, task_id: int | None = None) -> Answer:
    """One Claude call. `tools=None` → no tools at all (pure reading/writing)."""
    budget = _budget(model)
    if budget is not None and spent_today(model) >= budget:
        raise ResourceLimited(resource(model), _midnight_et(), f"daily {model} budget (${budget} equiv) used")
    WORKDIR.mkdir(parents=True, exist_ok=True)
    cmd = [CLAUDE, "-p", "--model", model, "--output-format", "json", "--no-session-persistence", "--strict-mcp-config",
           "--system-prompt", system or DEFAULT_SYSTEM, "--tools", ",".join(tools) if tools else ""]
    if tools:
        cmd += ["--allowedTools", ",".join(tools)]
    if schema:
        cmd += ["--json-schema", json.dumps(schema)]
    t0 = time.time()
    try:
        p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout, cwd=WORKDIR)
    except subprocess.TimeoutExpired:
        _log(purpose, model, False, {}, 0.0, int((time.time() - t0) * 1000), "timeout", task_id)
        raise RetryLater(f"claude {model} timed out after {timeout}s")
    ms = int((time.time() - t0) * 1000)
    try:
        d = json.loads(p.stdout) if p.stdout.strip() else {}
    except json.JSONDecodeError:
        d = {}
    usage, cost = d.get("usage") or {}, float(d.get("total_cost_usd") or 0.0)
    text = str(d.get("result") or "")
    if p.returncode != 0 or d.get("is_error") or not d:
        msg = (text or p.stderr or p.stdout or "no output")[:400]
        _log(purpose, model, False, usage, cost, ms, msg, task_id)
        if _LIMIT.search(msg):
            raise ResourceLimited(resource(model), _limit_until(msg), f"claude {model}: {msg[:160]}")
        if "keychain" in msg.lower() or "not logged in" in msg.lower() or "login" in msg.lower():
            raise ResourceLimited(resource(model), datetime.now(timezone.utc) + timedelta(minutes=30),
                                  f"claude {model} not signed in for background use: {msg[:160]}")
        raise RetryLater(f"claude {model} error: {msg[:200]}")
    data = d.get("structured_output") if schema else None
    if schema and not isinstance(data, dict):
        _log(purpose, model, False, usage, cost, ms, "no structured output", task_id)
        raise RetryLater(f"claude {model}: answer didn't match the schema")
    _log(purpose, model, True, usage, cost, ms, None, task_id)
    return Answer(data, text, usage, cost, ms / 1000)

