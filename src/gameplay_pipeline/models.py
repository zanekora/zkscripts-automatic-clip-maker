from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(slots=True)
class BlackdetectConfig:
    enabled: bool = True
    min_duration: float = 0.75
    pixel_threshold: float = 0.10
    picture_threshold: float = 0.98


@dataclass(slots=True)
class AnalysisConfig:
    supported_extensions: tuple[str, ...]
    segmentation_mode: str
    overlap_warning_min_seconds: float
    minimum_keep_segment_seconds: float
    merge_gap_seconds: float
    reuse_analysis_by_default: bool
    blackdetect: BlackdetectConfig
    scene_detection: "SceneDetectionConfig"
    visual_cut_detection: "VisualCutDetectionConfig"
    active_fight_detection: "ActiveFightDetectionConfig"


@dataclass(slots=True)
class SceneDetectionConfig:
    enabled: bool = True
    threshold: float = 27.0
    min_scene_length_seconds: float = 2.0


@dataclass(slots=True)
class VisualCutDetectionConfig:
    enabled: bool = True
    fullscreen_templates_dir: str = "presets/fullscreen_templates"
    partial_templates_dir: str = "presets/partial_templates"
    terminal_templates_dir: str = "presets/terminal_templates"
    cut_weight: float = 1.0
    terminal_cut_weight: float = 1.15
    sample_interval_seconds: float = 0.5
    template_similarity_threshold: float = 0.85
    min_template_match_duration_seconds: float = 2.0
    template_only_cut_requires_static: bool = True
    unscoped_template_enabled: bool = False
    small_template_late_match_enabled: bool = True
    small_template_max_coverage: float = 0.12
    small_template_extra_similarity: float = 0.05
    sticky_region_match_enabled: bool = True
    sticky_region_min_consecutive_hits: int = 2
    sticky_region_release_seconds: float = 1.5
    flash_transition_enabled: bool = True
    flash_brightness_delta_threshold: float = 35.0
    flash_changed_pixel_ratio_threshold: float = 0.45
    flash_bright_pixel_ratio_threshold: float = 0.45
    flash_follow_window_seconds: float = 2.0
    flash_terminal_tail_enabled: bool = True
    terminal_region_detector_enabled: bool = True
    terminal_region_start_fraction: float = 0.7
    terminal_region_min_template_hits: int = 2
    terminal_template_min_unique_matches: int = 2
    terminal_large_template_min_coverage: float = 0.08
    terminal_region_edge_density_threshold: float = 0.05
    terminal_region_text_like_threshold: float = 0.012
    terminal_region_min_duration_seconds: float = 1.0
    static_screen_enabled: bool = True
    static_motion_threshold: float = 3.0
    static_edge_density_threshold: float = 0.09
    static_text_like_threshold: float = 0.025
    min_static_duration_seconds: float = 3.0


@dataclass(slots=True)
class ActiveFightDetectionConfig:
    enabled: bool = True
    templates_dir: str = "presets/infight_templates"
    protection_weight: float = 1.25
    sample_interval_seconds: float = 0.2
    similarity_threshold: float = 0.78
    min_match_duration_seconds: float = 1.0
    leading_keep_seconds: float = 0.5
    trailing_keep_seconds: float = 1.5
    min_consecutive_hits: int = 2
    release_after_misses: int = 3
    require_dynamic_frame: bool = True
    max_static_changed_pixel_ratio: float = 0.10


@dataclass(slots=True)
class ExportConfig:
    export_fight_clips: bool = False
    export_combined_video: bool = False
    fight_subdir_name: str = "fights"
    combined_filename: str = "combined_highlights.mp4"
    video_codec: str = "libx264"
    audio_codec: str = "aac"
    crf: int = 18
    preset: str = "medium"
    transition_mode: str = "fade"
    transition_duration_seconds: float = 0.35


@dataclass(slots=True)
class AppConfig:
    input_dir: str
    output_dir: str
    review_dir: str
    logs_dir: str
    ffmpeg_path: str
    ffprobe_path: str
    analysis: AnalysisConfig
    export: ExportConfig


@dataclass(slots=True)
class BlackSegment:
    start: float
    end: float
    duration: float


@dataclass(slots=True)
class ClipInfo:
    path: str
    name: str
    extension: str
    size_bytes: int
    modified_time_iso: str
    creation_time_iso: Optional[str]
    duration_seconds: Optional[float]
    width: Optional[int]
    height: Optional[int]
    fps: Optional[float]
    estimated_start_iso: str
    estimated_end_iso: Optional[str]
    file_signature: str = ""
    black_segments: list[BlackSegment] = field(default_factory=list)
    active_fight_segments: list["DetectedSegment"] = field(default_factory=list)
    cut_segments: list["DetectedSegment"] = field(default_factory=list)
    scene_segments: list["SceneSegment"] = field(default_factory=list)
    keep_segments: list["KeepSegment"] = field(default_factory=list)
    debug_notes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SceneSegment:
    start: float
    end: float
    duration: float


@dataclass(slots=True)
class KeepSegment:
    start: float
    end: float
    duration: float
    reason: str


@dataclass(slots=True)
class DetectedSegment:
    start: float
    end: float
    duration: float
    label: str


@dataclass(slots=True)
class ExportedFightClip:
    source_clip_name: str
    segment_index: int
    start: float
    end: float
    duration: float
    output_path: str


@dataclass(slots=True)
class CombinedVideoOutput:
    output_path: str
    clip_count: int
    transition_mode: str
    transition_duration_seconds: float


@dataclass(slots=True)
class OverlapInfo:
    clip_a: str
    clip_b: str
    clip_a_end_iso: str
    clip_b_start_iso: str
    overlap_seconds: float
    note: str


@dataclass(slots=True)
class Report:
    generated_at_iso: str
    input_dir: str
    output_dir: str
    review_dir: str
    log_path: str
    ffmpeg_path: str
    ffprobe_path: str
    clips: list[ClipInfo]
    overlaps: list[OverlapInfo]
    exported_fight_clips: list[ExportedFightClip]
    combined_video: CombinedVideoOutput | None
    warnings: list[str]
