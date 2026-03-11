from __future__ import annotations

import logging
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

from .ffmpeg_tools import run_command
from .models import ClipInfo, CombinedVideoOutput, ExportConfig, ExportedFightClip, KeepSegment


def sanitize_name(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in ("-", "_") else "_" for char in value)
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_") or "clip"


def export_fight_clip(
    ffmpeg_path: str,
    clip: ClipInfo,
    segment: KeepSegment,
    segment_index: int,
    output_path: Path,
    export_config: ExportConfig,
) -> ExportedFightClip:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    command = [
        ffmpeg_path,
        "-hide_banner",
        "-y",
        "-i",
        clip.path,
        "-ss",
        f"{segment.start:.3f}",
        "-to",
        f"{segment.end:.3f}",
        "-map",
        "0:v:0?",
        "-map",
        "0:a:0?",
        "-c:v",
        export_config.video_codec,
        "-preset",
        export_config.preset,
        "-crf",
        str(export_config.crf),
        "-c:a",
        export_config.audio_codec,
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    result = run_command(command)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown ffmpeg error"
        raise RuntimeError(f"Fight clip export failed for '{clip.name}': {detail}")

    return ExportedFightClip(
        source_clip_name=clip.name,
        segment_index=segment_index,
        start=segment.start,
        end=segment.end,
        duration=segment.duration,
        output_path=str(output_path.resolve()),
    )


def export_fight_clips(
    ffmpeg_path: str,
    clips: list[ClipInfo],
    output_dir: Path,
    export_config: ExportConfig,
) -> list[ExportedFightClip]:
    fight_dir = output_dir / export_config.fight_subdir_name
    fight_dir.mkdir(parents=True, exist_ok=True)

    exported: list[ExportedFightClip] = []
    for clip in clips:
        if not clip.keep_segments:
            continue

        base_name = sanitize_name(Path(clip.name).stem)
        for index, segment in enumerate(clip.keep_segments, start=1):
            output_path = fight_dir / f"{base_name}_fight_{index:03d}.mp4"
            logging.info("Exporting fight clip %s", output_path.name)
            exported.append(
                export_fight_clip(
                    ffmpeg_path=ffmpeg_path,
                    clip=clip,
                    segment=segment,
                    segment_index=index,
                    output_path=output_path,
                    export_config=export_config,
                )
            )

    return exported


def apply_fade_envelope(
    ffmpeg_path: str,
    input_path: Path,
    output_path: Path,
    duration_seconds: float,
    export_config: ExportConfig,
) -> None:
    if duration_seconds <= 0:
        shutil.copy2(input_path, output_path)
        return

    fade_duration = min(export_config.transition_duration_seconds, max(0.0, duration_seconds / 3))
    if fade_duration <= 0 or duration_seconds <= fade_duration:
        shutil.copy2(input_path, output_path)
        return

    fade_out_start = max(0.0, duration_seconds - fade_duration)
    video_filter = (
        f"fade=t=in:st=0:d={fade_duration:.3f},"
        f"fade=t=out:st={fade_out_start:.3f}:d={fade_duration:.3f}"
    )

    command = [
        ffmpeg_path,
        "-hide_banner",
        "-y",
        "-i",
        str(input_path),
        "-map",
        "0:v:0?",
        "-map",
        "0:a:0?",
        "-vf",
        video_filter,
        "-c:v",
        export_config.video_codec,
        "-preset",
        export_config.preset,
        "-crf",
        str(export_config.crf),
        "-c:a",
        export_config.audio_codec,
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    result = run_command(command)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown ffmpeg error"
        raise RuntimeError(f"Failed to create transition clip '{input_path.name}': {detail}")


def export_combined_video(
    ffmpeg_path: str,
    exported_fight_clips: list[ExportedFightClip],
    output_dir: Path,
    export_config: ExportConfig,
) -> CombinedVideoOutput | None:
    if not exported_fight_clips:
        return None

    combined_output_path = output_dir / export_config.combined_filename
    combined_output_path.parent.mkdir(parents=True, exist_ok=True)

    with TemporaryDirectory(prefix="gameplay_pipeline_concat_") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        concat_entries: list[str] = []

        for clip_index, clip in enumerate(exported_fight_clips, start=1):
            source_path = Path(clip.output_path)
            concat_path = source_path

            if export_config.transition_mode == "fade":
                concat_path = temp_dir / f"transition_{clip_index:03d}.mp4"
                apply_fade_envelope(
                    ffmpeg_path=ffmpeg_path,
                    input_path=source_path,
                    output_path=concat_path,
                    duration_seconds=clip.duration,
                    export_config=export_config,
                )

            concat_entries.append(f"file '{concat_path.as_posix()}'")

        concat_file = temp_dir / "fight_concat.txt"
        concat_file.write_text("\n".join(concat_entries), encoding="utf-8")

        command = [
            ffmpeg_path,
            "-hide_banner",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-c",
            "copy",
            str(combined_output_path),
        ]
        result = run_command(command)
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "unknown ffmpeg error"
            raise RuntimeError(f"Combined video export failed: {detail}")

    return CombinedVideoOutput(
        output_path=str(combined_output_path.resolve()),
        clip_count=len(exported_fight_clips),
        transition_mode=export_config.transition_mode,
        transition_duration_seconds=export_config.transition_duration_seconds,
    )
