from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import (
    AnalysisConfig,
    AppConfig,
    BlackdetectConfig,
    ExportConfig,
    SceneDetectionConfig,
    VisualCutDetectionConfig,
)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"Config file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Config file is not valid JSON: {path} ({exc})") from exc


def load_app_config(config_path: Path) -> AppConfig:
    raw = _load_json(config_path)

    try:
        paths = raw["paths"]
        ffmpeg = raw["ffmpeg"]
        analysis = raw["analysis"]
        blackdetect = analysis["blackdetect"]
        scene_detection = analysis["scene_detection"]
        visual_cut_detection = analysis["visual_cut_detection"]
        export = raw["export"]
    except KeyError as exc:
        raise RuntimeError(f"Missing required config key: {exc}") from exc

    return AppConfig(
        input_dir=str(paths["input"]),
        output_dir=str(paths["output"]),
        review_dir=str(paths["review"]),
        logs_dir=str(paths["logs"]),
        ffmpeg_path=str(ffmpeg["ffmpeg_path"]),
        ffprobe_path=str(ffmpeg["ffprobe_path"]),
        analysis=AnalysisConfig(
            supported_extensions=tuple(str(item).lower() for item in analysis["supported_extensions"]),
            overlap_warning_min_seconds=float(analysis["overlap_warning_min_seconds"]),
            minimum_keep_segment_seconds=float(analysis["minimum_keep_segment_seconds"]),
            merge_gap_seconds=float(analysis["merge_gap_seconds"]),
            reuse_analysis_by_default=bool(analysis["reuse_analysis_by_default"]),
            blackdetect=BlackdetectConfig(
                enabled=bool(blackdetect["enabled"]),
                min_duration=float(blackdetect["min_duration"]),
                pixel_threshold=float(blackdetect["pixel_threshold"]),
                picture_threshold=float(blackdetect["picture_threshold"]),
            ),
            scene_detection=SceneDetectionConfig(
                enabled=bool(scene_detection["enabled"]),
                threshold=float(scene_detection["threshold"]),
                min_scene_length_seconds=float(scene_detection["min_scene_length_seconds"]),
            ),
            visual_cut_detection=VisualCutDetectionConfig(
                enabled=bool(visual_cut_detection["enabled"]),
                templates_dir=str(visual_cut_detection["templates_dir"]),
                sample_interval_seconds=float(visual_cut_detection["sample_interval_seconds"]),
                template_similarity_threshold=float(visual_cut_detection["template_similarity_threshold"]),
                min_template_match_duration_seconds=float(
                    visual_cut_detection["min_template_match_duration_seconds"]
                ),
                sticky_region_match_enabled=bool(visual_cut_detection["sticky_region_match_enabled"]),
                sticky_region_min_consecutive_hits=int(
                    visual_cut_detection["sticky_region_min_consecutive_hits"]
                ),
                sticky_region_release_seconds=float(
                    visual_cut_detection["sticky_region_release_seconds"]
                ),
                flash_transition_enabled=bool(visual_cut_detection["flash_transition_enabled"]),
                flash_brightness_delta_threshold=float(
                    visual_cut_detection["flash_brightness_delta_threshold"]
                ),
                flash_changed_pixel_ratio_threshold=float(
                    visual_cut_detection["flash_changed_pixel_ratio_threshold"]
                ),
                flash_follow_window_seconds=float(
                    visual_cut_detection["flash_follow_window_seconds"]
                ),
                flash_terminal_tail_enabled=bool(visual_cut_detection["flash_terminal_tail_enabled"]),
                terminal_region_detector_enabled=bool(
                    visual_cut_detection["terminal_region_detector_enabled"]
                ),
                terminal_region_start_fraction=float(
                    visual_cut_detection["terminal_region_start_fraction"]
                ),
                terminal_region_edge_density_threshold=float(
                    visual_cut_detection["terminal_region_edge_density_threshold"]
                ),
                terminal_region_text_like_threshold=float(
                    visual_cut_detection["terminal_region_text_like_threshold"]
                ),
                terminal_region_min_duration_seconds=float(
                    visual_cut_detection["terminal_region_min_duration_seconds"]
                ),
                static_screen_enabled=bool(visual_cut_detection["static_screen_enabled"]),
                static_motion_threshold=float(visual_cut_detection["static_motion_threshold"]),
                static_edge_density_threshold=float(visual_cut_detection["static_edge_density_threshold"]),
                static_text_like_threshold=float(visual_cut_detection["static_text_like_threshold"]),
                min_static_duration_seconds=float(visual_cut_detection["min_static_duration_seconds"]),
            ),
        ),
        export=ExportConfig(
            export_fight_clips=bool(export["export_fight_clips"]),
            export_combined_video=bool(export["export_combined_video"]),
            fight_subdir_name=str(export["fight_subdir_name"]),
            combined_filename=str(export["combined_filename"]),
            video_codec=str(export["video_codec"]),
            audio_codec=str(export["audio_codec"]),
            crf=int(export["crf"]),
            preset=str(export["preset"]),
            transition_mode=str(export["transition_mode"]).lower(),
            transition_duration_seconds=float(export["transition_duration_seconds"]),
        ),
    )
