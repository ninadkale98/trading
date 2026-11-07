"""PostgreSQL access: a shared connection pool and a tiny migration runner."""
from __future__ import annotations

import atexit
import threading
from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from core.config import settings

_pool: ConnectionPool | None = None
_lock = threading.Lock()
MIGRATIONS = Path(__file__).parent / "migrations"


def pool() -> ConnectionPool:
    global _pool
    with _lock:
        if _pool is None:
            _pool = ConnectionPool(
                settings()["database"]["dsn"], min_size=1, max_size=12,
                kwargs={"row_factory": dict_row, "autocommit": False}, open=True,
            )
            atexit.register(close)
    return _pool


def close() -> None:
    global _pool
    if _pool is not None:
        _pool.close(timeout=2)
        _pool = None


@contextmanager
def conn():
    """Connection inside a transaction: commits on success, rolls back on error."""
    with pool().connection() as c:
        yield c


def query(sql: str, params=None) -> list[dict]:
    with conn() as c:
        return c.execute(sql, params).fetchall()


def execute(sql: str, params=None) -> int:
    with conn() as c:
        return c.execute(sql, params).rowcount


def migrate() -> list[str]:
    """Apply core/db/migrations/NNN_*.sql in order, each once, each in its own transaction."""
    applied = []
    with psycopg.connect(settings()["database"]["dsn"], autocommit=True) as c:
        c.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())")
        done = {r[0] for r in c.execute("SELECT version FROM schema_migrations")}
    for f in sorted(MIGRATIONS.glob("*.sql")):
        if f.stem in done:
            continue
        with psycopg.connect(settings()["database"]["dsn"]) as c:
            c.execute(f.read_text())
            c.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (f.stem,))
            c.commit()
        applied.append(f.stem)
    return applied
