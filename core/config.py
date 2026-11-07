"""Configuration: .env secrets + config/settings.yaml + config/limits.yaml."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def _load_env(path: Path) -> None:
    """Minimal .env reader. Existing environment variables win. Values are never logged."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        val = val.strip().strip('"').strip("'")
        os.environ.setdefault(key, val)


_load_env(ROOT / ".env")


@lru_cache
def settings() -> dict:
    return yaml.safe_load((ROOT / "config" / "settings.yaml").read_text())


@lru_cache
def limits() -> dict:
    return yaml.safe_load((ROOT / "config" / "limits.yaml").read_text())


def secret(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(f"Missing {name} in .env")
    return val
