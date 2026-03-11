from __future__ import annotations

import argparse
import logging
import shutil
import sys
from pathlib import Path
from typing import Literal

from .analysis import analyze_clips
from .config import load_app_config
from .exporter import export_combined_video, export_fight_clips
from .logging_utils import setup_logging
from .runtime_paths import find_local_executable, get_app_root, resolve_from_app_root
from .reporting import write_csv_summary, write_json_report, write_markdown_report
from .models import ClipInfo, OverlapInfo, Report


def validate_executable(command: str, label: str) -> str | None:
    local_candidate = find_local_executable(f"{command}.exe") if Path(command).name == command else None
    if local_candidate is not None:
        return str(local_candidate.resolve())

    candidate = Path(command)
    if candidate.exists():
        return str(candidate.resolve())

    resolved = shutil.which(command)
    if resolved:
        return resolved

    logging.error(
        "%s executable not found: %s. Add it to PATH or pass an explicit path.",
        label,
        command,
    )
    return None


def resolve_reprocess_mode(requested_mode: str, has_existing_cache: bool) -> Literal["auto", "all"]:
    if requested_mode in {"auto", "all"}:
        return requested_mode

    if requested_mode == "ask":
        if not has_existing_cache or not sys.stdin.isatty():
            return "auto"

        response = input(
            "Cached analysis exists for prior clips. Reprocess all clips again? [y/N]: "
        ).strip().lower()
        return "all" if response in {"y", "yes"} else "auto"

    return "auto"


def write_partial_outputs(
    clips: list[ClipInfo],
    overlaps: list[OverlapInfo],
    warnings: list[str],
    input_dir: Path,
    output_dir: Path,
    review_dir: Path,
    log_path: Path,
    ffmpeg_path: str,
    ffprobe_path: str,
) -> None:
    partial_report = Report(
        generated_at_iso="in-progress",
        input_dir=str(input_dir),
        output_dir=str(output_dir),
        review_dir=str(review_dir),
        log_path=str(log_path),
        ffmpeg_path=ffmpeg_path,
        ffprobe_path=ffprobe_path,
        clips=clips,
        overlaps=overlaps,
        exported_fight_clips=[],
        combined_video=None,
        warnings=warnings + ["Partial report: run still in progress."],
    )
    write_json_report(partial_report, output_dir / "clip_report.json")
    write_csv_summary(clips, output_dir / "clip_summary.csv")
    write_markdown_report(partial_report, review_dir / "review_report.md")


def export_partial_clip_outputs(
    current_clip: ClipInfo,
    output_dir: Path,
    ffmpeg_path: str,
    export_config,
) -> None:
    if not current_clip.keep_segments:
        return

    preview_output_dir = output_dir / "_in_progress"
    export_fight_clips(
        ffmpeg_path=ffmpeg_path,
        clips=[current_clip],
        output_dir=preview_output_dir,
        export_config=export_config,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Non-destructive gameplay clip analysis pipeline (v1)."
    )
    parser.add_argument("--config", default="config/defaults.json", help="Path to JSON config file.")
    parser.add_argument("--input", help="Input directory containing raw clips.")
    parser.add_argument("--output", help="Directory for machine-readable outputs.")
    parser.add_argument("--review", help="Directory for human-readable review outputs.")
    parser.add_argument("--logs", help="Directory for log output.")
    parser.add_argument("--ffmpeg", help="Path to ffmpeg executable.")
    parser.add_argument("--ffprobe", help="Path to ffprobe executable.")
    parser.add_argument(
        "--black-min-duration",
        type=float,
        help="Override blackdetect minimum segment duration in seconds.",
    )
    parser.add_argument(
        "--black-pixel-threshold",
        type=float,
        help="Override blackdetect pix_th threshold.",
    )
    parser.add_argument(
        "--black-picture-threshold",
        type=float,
        help="Override blackdetect pic_th threshold.",
    )
    parser.add_argument(
        "--skip-blackdetect",
        action="store_true",
        help="Disable black/dead-space detection for this run.",
    )
    parser.add_argument(
        "--skip-scenedetect",
        action="store_true",
        help="Disable scene detection for this run.",
    )
    parser.add_argument(
        "--skip-visual-cut-detection",
        "--skip-loading-detection",
        action="store_true",
        help="Disable visual cut detection for this run.",
    )
    parser.add_argument(
        "--scene-threshold",
        type=float,
        help="Override PySceneDetect content threshold.",
    )
    parser.add_argument(
        "--min-scene-length",
        type=float,
        help="Override minimum scene length in seconds.",
    )
    parser.add_argument(
        "--min-keep-segment-length",
        type=float,
        help="Override minimum candidate keep segment length in seconds.",
    )
    parser.add_argument(
        "--merge-gap-seconds",
        type=float,
        help="Merge nearby candidate gameplay ranges if the blocked gap is below this threshold.",
    )
    parser.add_argument(
        "--cut-templates",
        "--loading-templates",
        dest="cut_templates",
        help="Folder of reference images used to identify spans that should be cut.",
    )
    parser.add_argument(
        "--template-similarity-threshold",
        "--loading-similarity-threshold",
        dest="template_similarity_threshold",
        type=float,
        help="Template similarity threshold for reference-image matching.",
    )
    parser.add_argument(
        "--static-motion-threshold",
        type=float,
        help="Lower values make static-screen detection stricter.",
    )
    parser.add_argument(
        "--static-edge-threshold",
        type=float,
        help="Higher values require more edge-dense UI/text before a static segment is cut.",
    )
    parser.add_argument(
        "--static-text-threshold",
        type=float,
        help="Higher values require more text-like row density before a static segment is cut.",
    )
    parser.add_argument(
        "--min-static-duration",
        type=float,
        help="Minimum duration for static/text-heavy segments to be cut.",
    )
    parser.add_argument(
        "--flash-brightness-threshold",
        type=float,
        help="Brightness delta threshold for sudden flash-transition detection.",
    )
    parser.add_argument(
        "--flash-change-threshold",
        type=float,
        help="Changed-pixel ratio threshold for sudden flash-transition detection.",
    )
    parser.add_argument(
        "--flash-follow-window",
        type=float,
        help="How long after a flash the tool should watch for a result/menu state and then cut from the flash onward.",
    )
    parser.add_argument(
        "--reprocess-mode",
        choices=["ask", "auto", "all"],
        default="ask",
        help="How to handle clips that already have cached analysis.",
    )
    parser.add_argument(
        "--cache-file",
        default="intermediate/analysis_cache.json",
        help="Path to the reusable analysis cache file.",
    )
    parser.add_argument(
        "--clip-at-a-time",
        action="store_true",
        help="Write partial reports after each clip finishes analysis so progress is visible sooner.",
    )
    parser.add_argument(
        "--export-fights",
        action="store_true",
        help="Export each candidate keep segment as its own fight clip.",
    )
    parser.add_argument(
        "--export-combined",
        action="store_true",
        help="Export one combined highlight video from exported fight clips.",
    )
    parser.add_argument(
        "--transition-mode",
        choices=["none", "fade"],
        help="Combined video transition style.",
    )
    parser.add_argument(
        "--transition-duration",
        type=float,
        help="Combined video transition duration in seconds.",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging.")
    return parser


def main() -> int:
    args = build_parser().parse_args()

    app_root = get_app_root()
    config_path = resolve_from_app_root(args.config).resolve()
    try:
        app_config = load_app_config(config_path)
    except RuntimeError as exc:
        print(f"Configuration error: {exc}")
        return 1

    if args.input:
        app_config.input_dir = args.input
    if args.output:
        app_config.output_dir = args.output
    if args.review:
        app_config.review_dir = args.review
    if args.logs:
        app_config.logs_dir = args.logs
    if args.ffmpeg:
        app_config.ffmpeg_path = args.ffmpeg
    if args.ffprobe:
        app_config.ffprobe_path = args.ffprobe
    if args.black_min_duration is not None:
        app_config.analysis.blackdetect.min_duration = args.black_min_duration
    if args.black_pixel_threshold is not None:
        app_config.analysis.blackdetect.pixel_threshold = args.black_pixel_threshold
    if args.black_picture_threshold is not None:
        app_config.analysis.blackdetect.picture_threshold = args.black_picture_threshold
    if args.skip_blackdetect:
        app_config.analysis.blackdetect.enabled = False
    if args.skip_scenedetect:
        app_config.analysis.scene_detection.enabled = False
    if args.skip_visual_cut_detection:
        app_config.analysis.visual_cut_detection.enabled = False
    if args.scene_threshold is not None:
        app_config.analysis.scene_detection.threshold = args.scene_threshold
    if args.min_scene_length is not None:
        app_config.analysis.scene_detection.min_scene_length_seconds = args.min_scene_length
    if args.min_keep_segment_length is not None:
        app_config.analysis.minimum_keep_segment_seconds = args.min_keep_segment_length
    if args.merge_gap_seconds is not None:
        app_config.analysis.merge_gap_seconds = args.merge_gap_seconds
    if args.cut_templates:
        app_config.analysis.visual_cut_detection.templates_dir = args.cut_templates
    if args.template_similarity_threshold is not None:
        app_config.analysis.visual_cut_detection.template_similarity_threshold = args.template_similarity_threshold
    if args.static_motion_threshold is not None:
        app_config.analysis.visual_cut_detection.static_motion_threshold = args.static_motion_threshold
    if args.static_edge_threshold is not None:
        app_config.analysis.visual_cut_detection.static_edge_density_threshold = args.static_edge_threshold
    if args.static_text_threshold is not None:
        app_config.analysis.visual_cut_detection.static_text_like_threshold = args.static_text_threshold
    if args.min_static_duration is not None:
        app_config.analysis.visual_cut_detection.min_static_duration_seconds = args.min_static_duration
    if args.flash_brightness_threshold is not None:
        app_config.analysis.visual_cut_detection.flash_brightness_delta_threshold = args.flash_brightness_threshold
    if args.flash_change_threshold is not None:
        app_config.analysis.visual_cut_detection.flash_changed_pixel_ratio_threshold = args.flash_change_threshold
    if args.flash_follow_window is not None:
        app_config.analysis.visual_cut_detection.flash_follow_window_seconds = args.flash_follow_window
    if args.export_fights:
        app_config.export.export_fight_clips = True
    if args.export_combined:
        app_config.export.export_combined_video = True
        app_config.export.export_fight_clips = True
    if args.transition_mode:
        app_config.export.transition_mode = args.transition_mode
    if args.transition_duration is not None:
        app_config.export.transition_duration_seconds = args.transition_duration

    input_dir = resolve_from_app_root(app_config.input_dir).resolve()
    output_dir = resolve_from_app_root(app_config.output_dir).resolve()
    review_dir = resolve_from_app_root(app_config.review_dir).resolve()
    logs_dir = resolve_from_app_root(app_config.logs_dir).resolve()
    cache_path = resolve_from_app_root(args.cache_file).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    review_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    log_path = logs_dir / "gameplay_pipeline.log"
    setup_logging(log_path, verbose=args.verbose)

    logging.info("Starting gameplay pipeline analysis.")
    logging.info("App root: %s", app_root)
    logging.info("Config file: %s", config_path)
    logging.info("Input directory: %s", input_dir)
    logging.info("Output directory: %s", output_dir)
    logging.info("Review directory: %s", review_dir)
    logging.info("Log path: %s", log_path)
    logging.info("Cache path: %s", cache_path)

    if not input_dir.exists() or not input_dir.is_dir():
        logging.error("Input directory does not exist or is not a directory: %s", input_dir)
        return 1

    ffprobe_resolved = validate_executable(app_config.ffprobe_path, "ffprobe")
    if ffprobe_resolved is None:
        return 1
    app_config.ffprobe_path = ffprobe_resolved

    if (
        app_config.analysis.blackdetect.enabled
        or app_config.export.export_fight_clips
        or app_config.export.export_combined_video
    ):
        ffmpeg_resolved = validate_executable(app_config.ffmpeg_path, "ffmpeg")
        if ffmpeg_resolved is None:
            return 1
        app_config.ffmpeg_path = ffmpeg_resolved

    reprocess_mode = resolve_reprocess_mode(
        requested_mode=args.reprocess_mode,
        has_existing_cache=cache_path.exists(),
    )
    logging.info("Reprocess mode: %s", reprocess_mode)

    per_clip_callback = None
    if args.clip_at_a_time:
        def per_clip_callback(clips, overlaps, warnings, current_clip):
            write_partial_outputs(
                clips=clips,
                overlaps=overlaps,
                warnings=warnings,
                input_dir=input_dir,
                output_dir=output_dir,
                review_dir=review_dir,
                log_path=log_path,
                ffmpeg_path=app_config.ffmpeg_path,
                ffprobe_path=app_config.ffprobe_path,
            )
            if app_config.export.export_fight_clips or app_config.export.export_combined_video:
                export_partial_clip_outputs(
                    current_clip=current_clip,
                    output_dir=output_dir,
                    ffmpeg_path=app_config.ffmpeg_path,
                    export_config=app_config.export,
                )

    try:
        report = analyze_clips(
            app_config=app_config,
            input_dir=input_dir,
            output_dir=output_dir,
            review_dir=review_dir,
            log_path=log_path,
            cache_path=cache_path,
            reprocess_mode=reprocess_mode,
            per_clip_callback=per_clip_callback,
        )
    except FileNotFoundError as exc:
        logging.exception("Missing executable or file: %s", exc)
        return 1
    except Exception:
        logging.exception("Pipeline failed.")
        return 1

    if app_config.export.export_fight_clips:
        try:
            report.exported_fight_clips = export_fight_clips(
                ffmpeg_path=app_config.ffmpeg_path,
                clips=report.clips,
                output_dir=output_dir,
                export_config=app_config.export,
            )
            logging.info("Exported %d fight clip(s).", len(report.exported_fight_clips))
        except Exception:
            logging.exception("Fight clip export failed.")
            return 1

    if app_config.export.export_combined_video:
        try:
            report.combined_video = export_combined_video(
                ffmpeg_path=app_config.ffmpeg_path,
                exported_fight_clips=report.exported_fight_clips,
                output_dir=output_dir,
                export_config=app_config.export,
            )
            if report.combined_video is not None:
                logging.info("Exported combined video: %s", report.combined_video.output_path)
        except Exception:
            logging.exception("Combined video export failed.")
            return 1

    json_path = output_dir / "clip_report.json"
    csv_path = output_dir / "clip_summary.csv"
    markdown_path = review_dir / "review_report.md"

    write_json_report(report, json_path)
    write_csv_summary(report.clips, csv_path)
    write_markdown_report(report, markdown_path)

    logging.info("Wrote JSON report: %s", json_path)
    logging.info("Wrote CSV summary: %s", csv_path)
    logging.info("Wrote Markdown review report: %s", markdown_path)
    logging.info("Analysis complete.")
    return 0
