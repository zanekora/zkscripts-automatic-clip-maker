from __future__ import annotations

import csv
import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from .models import ClipInfo, Report


def write_json_report(report: Report, output_path: Path) -> None:
    def default_serializer(value: Any) -> Any:
        if is_dataclass(value):
            return asdict(value)
        raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")

    output_path.write_text(
        json.dumps(report, default=default_serializer, indent=2),
        encoding="utf-8",
    )


def write_csv_summary(clips: list[ClipInfo], output_path: Path) -> None:
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "name",
                "path",
                "duration_seconds",
                "resolution",
                "fps",
                "estimated_start_iso",
                "estimated_end_iso",
                "black_segment_count",
                "cut_segment_count",
                "scene_segment_count",
                "keep_segment_count",
                "warnings",
            ]
        )
        for clip in clips:
            resolution = ""
            if clip.width is not None and clip.height is not None:
                resolution = f"{clip.width}x{clip.height}"

            writer.writerow(
                [
                    clip.name,
                    clip.path,
                    "" if clip.duration_seconds is None else clip.duration_seconds,
                    resolution,
                    "" if clip.fps is None else round(clip.fps, 3),
                    clip.estimated_start_iso,
                    "" if clip.estimated_end_iso is None else clip.estimated_end_iso,
                    len(clip.black_segments),
                    len(clip.cut_segments),
                    len(clip.scene_segments),
                    len(clip.keep_segments),
                    " | ".join(clip.warnings),
                ]
            )


def write_markdown_report(report: Report, output_path: Path) -> None:
    lines: list[str] = [
        "# Gameplay Review Report",
        "",
        f"- Generated: `{report.generated_at_iso}`",
        f"- Input directory: `{report.input_dir}`",
        f"- Output directory: `{report.output_dir}`",
        f"- Review directory: `{report.review_dir}`",
        f"- Log file: `{report.log_path}`",
        "",
        "## Clip Inventory",
        "",
    ]

    if not report.clips:
        lines.append("No clips found.")
    else:
        for clip in report.clips:
            resolution = (
                f"{clip.width}x{clip.height}"
                if clip.width is not None and clip.height is not None
                else "unknown"
            )
            lines.extend(
                [
                    f"### {clip.name}",
                    "",
                    f"- Path: `{clip.path}`",
                    f"- Duration (s): `{clip.duration_seconds}`",
                    f"- Resolution: `{resolution}`",
                    f"- FPS: `{clip.fps}`",
                    f"- Modified: `{clip.modified_time_iso}`",
                    f"- Embedded creation time: `{clip.creation_time_iso}`",
                    f"- Estimated start: `{clip.estimated_start_iso}`",
                    f"- Estimated end: `{clip.estimated_end_iso}`",
                    f"- Black/dead-space candidates: `{len(clip.black_segments)}`",
                    f"- Visual cut matches: `{len(clip.cut_segments)}`",
                    f"- Scene segments: `{len(clip.scene_segments)}`",
                    f"- Candidate keep segments: `{len(clip.keep_segments)}`",
                    "",
                ]
            )

            if clip.scene_segments:
                lines.append("#### Scene Segments")
                lines.append("")
                for segment in clip.scene_segments:
                    lines.append(
                        f"- start `{segment.start:.3f}s`, end `{segment.end:.3f}s`, duration `{segment.duration:.3f}s`"
                    )
                lines.append("")

            if clip.black_segments:
                lines.append("#### Black / Dead-Space Detections")
                lines.append("")
                for segment in clip.black_segments:
                    lines.append(
                        f"- start `{segment.start:.3f}s`, end `{segment.end:.3f}s`, duration `{segment.duration:.3f}s`"
                    )
                lines.append("")

            if clip.cut_segments:
                lines.append("#### Visual Cut Matches")
                lines.append("")
                for segment in clip.cut_segments:
                    lines.append(
                        f"- start `{segment.start:.3f}s`, end `{segment.end:.3f}s`, duration `{segment.duration:.3f}s`, label `{segment.label}`"
                    )
                lines.append("")

            if clip.keep_segments:
                lines.append("#### Candidate Keep Segments")
                lines.append("")
                for segment in clip.keep_segments:
                    lines.append(
                        f"- keep `{segment.start:.3f}s` to `{segment.end:.3f}s` (`{segment.duration:.3f}s`) because {segment.reason}"
                    )
                lines.append("")

            if clip.warnings:
                lines.append("#### Warnings / Missing Metadata")
                lines.append("")
                for warning in clip.warnings:
                    lines.append(f"- {warning}")
                lines.append("")

    lines.extend(["## Likely Overlaps", ""])
    if not report.overlaps:
        lines.append("No likely overlaps detected.")
    else:
        for overlap in report.overlaps:
            lines.extend(
                [
                    f"- `{overlap.clip_a}` and `{overlap.clip_b}` likely overlap for `{overlap.overlap_seconds}` seconds.",
                    f"  clip A end: `{overlap.clip_a_end_iso}`",
                    f"  clip B start: `{overlap.clip_b_start_iso}`",
                    f"  note: {overlap.note}",
                ]
            )

    lines.extend(["", "## Black / Dead-Space Detections", ""])
    if not any(clip.black_segments for clip in report.clips):
        lines.append("No black/dead-space candidates detected.")
    else:
        for clip in report.clips:
            if not clip.black_segments:
                continue
            lines.append(f"- `{clip.name}`: `{len(clip.black_segments)}` candidate segment(s)")

    lines.extend(["", "## Visual Cut Matches", ""])
    if not any(clip.cut_segments for clip in report.clips):
        lines.append("No visual cut matches detected.")
    else:
        for clip in report.clips:
            if not clip.cut_segments:
                continue
            lines.append(f"- `{clip.name}`: `{len(clip.cut_segments)}` matched segment(s)")

    lines.extend(["", "## Candidate Keep Segments", ""])
    if not any(clip.keep_segments for clip in report.clips):
        lines.append("No candidate keep segments generated.")
    else:
        for clip in report.clips:
            if not clip.keep_segments:
                continue
            lines.append(f"### {clip.name}")
            lines.append("")
            for segment in clip.keep_segments:
                lines.append(
                    f"- `{segment.start:.3f}s` to `{segment.end:.3f}s` (`{segment.duration:.3f}s`) - {segment.reason}"
                )
            lines.append("")

    lines.extend(["## Exported Fight Clips", ""])
    if not report.exported_fight_clips:
        lines.append("No fight clips exported.")
    else:
        for fight_clip in report.exported_fight_clips:
            lines.append(
                f"- `{fight_clip.source_clip_name}` segment `{fight_clip.segment_index}` -> `{fight_clip.output_path}`"
            )

    lines.extend(["", "## Combined Video", ""])
    if report.combined_video is None:
        lines.append("No combined video exported.")
    else:
        lines.append(f"- Output: `{report.combined_video.output_path}`")
        lines.append(f"- Fight clip count: `{report.combined_video.clip_count}`")
        lines.append(f"- Transition mode: `{report.combined_video.transition_mode}`")
        lines.append(
            f"- Transition duration (s): `{report.combined_video.transition_duration_seconds}`"
        )

    lines.extend(["", "## Warnings / Missing Metadata", ""])
    combined_warnings = list(report.warnings)
    for clip in report.clips:
        for warning in clip.warnings:
            combined_warnings.append(f"{clip.name}: {warning}")

    if not combined_warnings:
        lines.append("No warnings.")
    else:
        for warning in combined_warnings:
            lines.append(f"- {warning}")

    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- This pass is report-only and non-destructive.",
            "- Overlap detection is still timing-based and should be manually validated.",
            "- Candidate keep segments are built from contiguous visible gameplay ranges after blocked segments are removed.",
            "- Visual cut matching improves if you place representative reference images in the cut-templates folder and tune the static-screen thresholds.",
        ]
    )

    output_path.write_text("\n".join(lines), encoding="utf-8")
