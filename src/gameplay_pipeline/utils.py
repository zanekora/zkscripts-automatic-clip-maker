from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional


def iso_from_timestamp(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).astimezone().isoformat()


def parse_iso_datetime(value: str | None) -> Optional[datetime]:
    if not value:
        return None

    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone()


def safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_fraction_fps(value: str | None) -> Optional[float]:
    if not value:
        return None

    if "/" not in value:
        return safe_float(value)

    numerator, denominator = value.split("/", 1)
    numerator_float = safe_float(numerator)
    denominator_float = safe_float(denominator)
    if numerator_float is None or denominator_float in (None, 0.0):
        return None

    return numerator_float / denominator_float
