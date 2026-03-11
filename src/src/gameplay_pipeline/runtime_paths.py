from __future__ import annotations

import sys
from pathlib import Path


def get_app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def resolve_from_app_root(path_value: str | Path) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return get_app_root() / path


def find_local_executable(executable_name: str) -> Path | None:
    candidate = get_app_root() / executable_name
    if candidate.exists():
        return candidate
    return None
