from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .models import BlackSegment, ClipInfo, DetectedSegment, KeepSegment, SceneSegment


def _clip_from_dict(payload: dict[str, Any]) -> ClipInfo:
    return ClipInfo(
        path=str(payload["path"]),
        name=str(payload["name"]),
        extension=str(payload["extension"]),
        size_bytes=int(payload["size_bytes"]),
        modified_time_iso=str(payload["modified_time_iso"]),
        creation_time_iso=payload.get("creation_time_iso"),
        duration_seconds=payload.get("duration_seconds"),
        width=payload.get("width"),
        height=payload.get("height"),
        fps=payload.get("fps"),
        estimated_start_iso=str(payload["estimated_start_iso"]),
        estimated_end_iso=payload.get("estimated_end_iso"),
        file_signature=str(payload.get("file_signature", "")),
        black_segments=[BlackSegment(**item) for item in payload.get("black_segments", [])],
        active_fight_segments=[DetectedSegment(**item) for item in payload.get("active_fight_segments", [])],
        cut_segments=[
            DetectedSegment(**item)
            for item in payload.get("cut_segments", payload.get("loading_segments", []))
        ],
        scene_segments=[SceneSegment(**item) for item in payload.get("scene_segments", [])],
        keep_segments=[KeepSegment(**item) for item in payload.get("keep_segments", [])],
        debug_notes=[str(item) for item in payload.get("debug_notes", [])],
        warnings=[str(item) for item in payload.get("warnings", [])],
    )


def load_clip_cache(cache_path: Path) -> dict[str, ClipInfo]:
    if not cache_path.exists():
        return {}

    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}

    entries = payload.get("clips", {})
    cache: dict[str, ClipInfo] = {}
    for path, clip_payload in entries.items():
        try:
            cache[path] = _clip_from_dict(clip_payload)
        except Exception:
            continue
    return cache


def save_clip_cache(cache_path: Path, clips: list[ClipInfo]) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "clips": {clip.path: asdict(clip) for clip in clips},
    }
    cache_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
