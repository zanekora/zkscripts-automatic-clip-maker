from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .models import BlackSegment, ClipInfo
from .utils import iso_from_timestamp, parse_fraction_fps, parse_iso_datetime, safe_float


def run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def extract_metadata(ffprobe_path: str, file_path: Path) -> ClipInfo:
    command = [
        ffprobe_path,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(file_path),
    ]
    result = run_command(command)
    if result.returncode != 0:
        detail = result.stderr.strip() or "unknown error"
        raise RuntimeError(f"ffprobe failed for '{file_path.name}': {detail}")

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Failed to parse ffprobe JSON for '{file_path.name}': {exc}") from exc

    format_info = payload.get("format", {})
    streams = payload.get("streams", [])
    video_stream = next((stream for stream in streams if stream.get("codec_type") == "video"), None)

    duration_seconds = safe_float(format_info.get("duration"))
    width = video_stream.get("width") if video_stream else None
    height = video_stream.get("height") if video_stream else None
    fps = parse_fraction_fps(video_stream.get("avg_frame_rate") if video_stream else None)

    tags = format_info.get("tags", {}) or {}
    stream_tags = (video_stream.get("tags", {}) if video_stream else {}) or {}
    creation_time = tags.get("creation_time") or stream_tags.get("creation_time")
    parsed_creation = parse_iso_datetime(creation_time)

    warnings: list[str] = []
    stat = file_path.stat()
    modified_time_iso = iso_from_timestamp(stat.st_mtime)
    file_signature = f"{stat.st_size}:{int(stat.st_mtime)}"

    if parsed_creation is not None:
        estimated_start = parsed_creation
        creation_time_iso = parsed_creation.isoformat()
    else:
        modified_time = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).astimezone()
        creation_time_iso = None
        if duration_seconds is not None:
            estimated_start = modified_time - timedelta(seconds=duration_seconds)
            warnings.append(
                "Missing embedded creation_time; estimated start from modified time minus duration."
            )
        else:
            estimated_start = modified_time
            warnings.append(
                "Missing embedded creation_time and duration; using modified time as estimated start."
            )

    estimated_end_iso = None
    if duration_seconds is not None:
        estimated_end_iso = (estimated_start + timedelta(seconds=duration_seconds)).isoformat()
    else:
        warnings.append("Missing duration; could not estimate clip end time.")

    return ClipInfo(
        path=str(file_path.resolve()),
        name=file_path.name,
        extension=file_path.suffix.lower(),
        size_bytes=stat.st_size,
        modified_time_iso=modified_time_iso,
        creation_time_iso=creation_time_iso,
        duration_seconds=duration_seconds,
        width=width,
        height=height,
        fps=fps,
        estimated_start_iso=estimated_start.isoformat(),
        estimated_end_iso=estimated_end_iso,
        file_signature=file_signature,
        warnings=warnings,
    )


def detect_black_segments(
    ffmpeg_path: str,
    file_path: Path,
    min_duration: float,
    pixel_threshold: float,
    picture_threshold: float,
) -> list[BlackSegment]:
    filter_expression = (
        f"blackdetect=d={min_duration}:pix_th={pixel_threshold}:pic_th={picture_threshold}"
    )
    command = [
        ffmpeg_path,
        "-hide_banner",
        "-i",
        str(file_path),
        "-vf",
        filter_expression,
        "-an",
        "-f",
        "null",
        "-",
    ]

    result = run_command(command)
    combined_output = f"{result.stdout}\n{result.stderr}"
    pattern = re.compile(
        r"black_start:(?P<start>\d+(?:\.\d+)?)\s+black_end:(?P<end>\d+(?:\.\d+)?)\s+black_duration:(?P<duration>\d+(?:\.\d+)?)"
    )

    segments: list[BlackSegment] = []
    for match in pattern.finditer(combined_output):
        segments.append(
            BlackSegment(
                start=float(match.group("start")),
                end=float(match.group("end")),
                duration=float(match.group("duration")),
            )
        )

    return segments
