from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import (
    ActiveFightDetectionConfig,
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
        active_fight_detection = analysis["active_fight_detection"]
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
            segmentation_mode=str(analysis["segmentation_mode"]).lower(),
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
                fullscreen_templates_dir=str(visual_cut_detection["fullscreen_templates_dir"]),
                partial_templates_dir=str(visual_cut_detection["partial_templates_dir"]),
                terminal_templates_dir=str(visual_cut_detection["terminal_templates_dir"]),
                cut_weight=float(visual_cut_detection["cut_weight"]),
                terminal_cut_weight=float(visual_cut_detection["terminal_cut_weight"]),
                sample_interval_seconds=float(visual_cut_detection["sample_interval_seconds"]),
                template_similarity_threshold=float(visual_cut_detection["template_similarity_threshold"]),
                min_template_match_duration_seconds=float(
                    visual_cut_detection["min_template_match_duration_seconds"]
                ),
                template_only_cut_requires_static=bool(
                    visual_cut_detection["template_only_cut_requires_static"]
                ),
                unscoped_template_enabled=bool(
                    visual_cut_detection["unscoped_template_enabled"]
                ),
                small_template_late_match_enabled=bool(
                    visual_cut_detection["small_template_late_match_enabled"]
                ),
                small_template_max_coverage=float(
                    visual_cut_detection["small_template_max_coverage"]
                ),
                small_template_extra_similarity=float(
                    visual_cut_detection["small_template_extra_similarity"]
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
                flash_bright_pixel_ratio_threshold=float(
                    visual_cut_detection["flash_bright_pixel_ratio_threshold"]
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
                terminal_region_min_template_hits=int(
                    visual_cut_detection["terminal_region_min_template_hits"]
                ),
                terminal_template_min_unique_matches=int(
                    visual_cut_detection["terminal_template_min_unique_matches"]
                ),
                terminal_large_template_min_coverage=float(
                    visual_cut_detection["terminal_large_template_min_coverage"]
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
            active_fight_detection=ActiveFightDetectionConfig(
                enabled=bool(active_fight_detection["enabled"]),
                templates_dir=str(active_fight_detection["templates_dir"]),
                protection_weight=float(active_fight_detection["protection_weight"]),
                sample_interval_seconds=float(active_fight_detection["sample_interval_seconds"]),
                similarity_threshold=float(active_fight_detection["similarity_threshold"]),
                min_match_duration_seconds=float(active_fight_detection["min_match_duration_seconds"]),
                leading_keep_seconds=float(active_fight_detection["leading_keep_seconds"]),
                trailing_keep_seconds=float(active_fight_detection["trailing_keep_seconds"]),
                min_consecutive_hits=int(active_fight_detection["min_consecutive_hits"]),
                release_after_misses=int(active_fight_detection["release_after_misses"]),
                require_dynamic_frame=bool(active_fight_detection["require_dynamic_frame"]),
                max_static_changed_pixel_ratio=float(active_fight_detection["max_static_changed_pixel_ratio"]),
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
