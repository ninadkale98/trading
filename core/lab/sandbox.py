"""Safety check for AI-written strategy code (architecture §9 safety boundary), run BEFORE the code is ever imported.

A strategy file may only: import numpy / math and the strategy helpers, define ONE FeatureStrategy subclass, and do
arithmetic on the feature arrays it's given. It may not touch files, the network, the database, the process, or
anything with double underscores; no `while` loops (a hang would stall the planner); and it may not index the future
(e.g. `close[t + 1]`). The runtime look-ahead check in core/lab/lookahead.py backs this up.
"""
from __future__ import annotations

import ast
import re

ALLOWED_IMPORTS = {
    "numpy": None, "math": None,                                          # None = any name / the module itself
    "core.backtest.engine": {"Signal"},
    "core.strategy.base": {"FeatureStrategy", "earnings_clear", "atr_stop"},
}
BANNED_CALLS = {"open", "exec", "eval", "compile", "__import__", "globals", "locals", "vars", "getattr", "setattr",
                "delattr", "input", "breakpoint", "exit", "quit", "help", "memoryview", "print"}
BANNED_NP = {"load", "save", "savez", "savez_compressed", "savetxt", "loadtxt", "genfromtxt", "fromfile", "tofile",
             "memmap", "ctypeslib", "lib", "testing", "distutils", "f2py", "DataSource", "fromregex"}
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{2,40}$")


class Rejected(ValueError):
    pass


def _uses_t(node: ast.AST) -> bool:
    return any(isinstance(n, ast.Name) and n.id == "t" for n in ast.walk(node))


def _terms(node: ast.AST, sign: int = 1):
    """Flatten a +/- expression into (sign, term) pairs."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub)):
        yield from _terms(node.left, sign)
        yield from _terms(node.right, sign if isinstance(node.op, ast.Add) else -sign)
    elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        yield from _terms(node.operand, -sign)
    else:
        yield sign, node


def _offset(node: ast.AST) -> float | None:
    """How many days past t an index expression can reach (None = not a `t`-relative index). Other names are assumed
    to be lookback lengths ≥ 1, so `t - w + 1` reaches at most day t (offset 0), while `t + k` is unknown → infinity."""
    terms = list(_terms(node))
    if not any(sg > 0 and isinstance(n, ast.Name) and n.id == "t" for sg, n in terms):
        return None
    const, neg_unknown, pos_unknown = 0.0, 0, False
    for sg, n in terms:
        if isinstance(n, ast.Name) and n.id == "t":
            continue
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            const += sg * n.value
        elif sg < 0:
            neg_unknown += 1
        else:
            pos_unknown = True
    return float("inf") if pos_unknown else const - neg_unknown


def _check_subscript(sl: ast.AST) -> str | None:
    items = sl.elts if isinstance(sl, ast.Tuple) else [sl]
    for it in items:
        if isinstance(it, ast.Slice):
            lo, hi = it.lower, it.upper
            if hi is not None and (_offset(hi) or 0) > 1:
                return "slice reaches past day t"
            if lo is not None and _uses_t(lo) and hi is None:
                return "open-ended slice from day t onward reads the future"
            if lo is not None and (_offset(lo) or 0) > 0:
                return "slice starts after day t"
        elif (_offset(it) or 0) > 0:
            return "index past day t reads the future"
    return None


def validate(code: str, expected_name: str) -> dict:
    """Raise Rejected with a readable reason, or return {'class': ClassName}."""
    if not NAME_RE.match(expected_name):
        raise Rejected(f"bad strategy name {expected_name!r}")
    if len(code) > 20_000:
        raise Rejected("file too long (max 20,000 characters)")
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        raise Rejected(f"syntax error: {e}") from None

    classes = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            continue                                                    # docstring
        if isinstance(node, ast.ClassDef):
            classes.append(node)
            continue
        if isinstance(node, ast.Assign) and all(isinstance(t, ast.Name) for t in node.targets) \
                and isinstance(node.value, (ast.Constant, ast.Tuple, ast.List, ast.Dict, ast.UnaryOp, ast.BinOp)):
            continue                                                    # module-level constants
        raise Rejected(f"line {node.lineno}: only imports, constants and one class are allowed at module level")

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name not in ALLOWED_IMPORTS:
                    raise Rejected(f"line {node.lineno}: import of {a.name!r} is not allowed")
        elif isinstance(node, ast.ImportFrom):
            allowed = ALLOWED_IMPORTS.get(node.module or "", False)
            if allowed is False or node.level:
                raise Rejected(f"line {node.lineno}: import from {node.module!r} is not allowed")
            for a in node.names:
                if allowed is not None and a.name not in allowed:
                    raise Rejected(f"line {node.lineno}: {node.module}.{a.name} is not allowed")
        elif isinstance(node, (ast.While, ast.AsyncFunctionDef, ast.Await, ast.Global, ast.Nonlocal, ast.AsyncWith)):
            raise Rejected(f"line {node.lineno}: {type(node).__name__} is not allowed")
        elif isinstance(node, ast.With):
            ok = all(isinstance(w.context_expr, ast.Call) and isinstance(w.context_expr.func, ast.Attribute)
                     and w.context_expr.func.attr == "errstate" and w.optional_vars is None for w in node.items)
            if not ok:
                raise Rejected(f"line {node.lineno}: only `with np.errstate(...)` is allowed")
        elif isinstance(node, ast.Name) and (node.id in BANNED_CALLS or node.id.startswith("__")):
            raise Rejected(f"line {node.lineno}: {node.id!r} is not allowed")
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("_"):
                raise Rejected(f"line {node.lineno}: private attribute {node.attr!r} is not allowed")
            if node.attr in BANNED_NP:
                raise Rejected(f"line {node.lineno}: numpy.{node.attr} (file/system access) is not allowed")
        elif isinstance(node, ast.Subscript):
            why = _check_subscript(node.slice)
            if why:
                raise Rejected(f"line {node.lineno}: {why} (look-ahead): {ast.unparse(node)}")
        elif isinstance(node, ast.Constant) and isinstance(node.value, bytes):
            raise Rejected(f"line {node.lineno}: byte strings are not allowed")

    strat = [c for c in classes if any(isinstance(b, ast.Name) and b.id == "FeatureStrategy" for b in c.bases)]
    if len(classes) != 1 or len(strat) != 1:
        raise Rejected("the file must define exactly one class, a subclass of FeatureStrategy")
    cls = strat[0]
    attrs = {t.id: n.value for n in cls.body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)}
    methods = {n.name for n in cls.body if isinstance(n, ast.FunctionDef)}
    name = attrs.get("name")
    if not (isinstance(name, ast.Constant) and name.value == expected_name):
        raise Rejected(f"class attribute name must be {expected_name!r}")
    for need in ("description", "hypothesis"):
        v = attrs.get(need)
        if not (isinstance(v, ast.Constant) and isinstance(v.value, str) and len(v.value) > 20):
            raise Rejected(f"class attribute {need!r} must be a plain-language string (over 20 characters)")
    for need in ("score", "plan"):
        if need not in methods:
            raise Rejected(f"method {need}(self, t[, j]) is required")
    bad = methods - {"eligible", "score", "plan", "why", "exits", "facts_to_show"} - {m for m in methods if m.startswith("helper_")}
    if bad:
        raise Rejected(f"unexpected methods {sorted(bad)}: allowed are eligible, score, plan, why, exits, facts_to_show, helper_*")
    return {"class": cls.name}

