from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal

from .cache import load_clip_cache, save_clip_cache
from .ffmpeg_tools import detect_black_segments, extract_metadata
from .models import AppConfig, ClipInfo, DetectedSegment, KeepSegment, OverlapInfo, Report, SceneSegment
from .runtime_paths import resolve_from_app_root
from .utils import parse_iso_datetime


def find_video_files(input_dir: Path, supported_extensions: tuple[str, ...]) -> list[Path]:
    return sorted(
        path
        for path in input_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in supported_extensions
    )


def sort_clips(clips: list[ClipInfo]) -> list[ClipInfo]:
    return sorted(
        clips,
        key=lambda clip: (
            parse_iso_datetime(clip.estimated_start_iso)
            or datetime.max.replace(tzinfo=timezone.utc).astimezone(),
            clip.name.lower(),
        ),
    )


def find_likely_overlaps(clips: list[ClipInfo], minimum_overlap_seconds: float) -> list[OverlapInfo]:
    parsed: list[tuple[ClipInfo, datetime, datetime | None]] = []
    for clip in clips:
        start = parse_iso_datetime(clip.estimated_start_iso)
        end = parse_iso_datetime(clip.estimated_end_iso)
        if start is None:
            continue
        parsed.append((clip, start, end))

    parsed.sort(key=lambda item: item[1])

    overlaps: list[OverlapInfo] = []
    for index, (clip_a, _, end_a) in enumerate(parsed[:-1]):
        clip_b, start_b, _ = parsed[index + 1]
        if end_a is None:
            continue

        overlap_seconds = round((end_a - start_b).total_seconds(), 3)
        if overlap_seconds < minimum_overlap_seconds:
            continue

        overlaps.append(
            OverlapInfo(
                clip_a=clip_a.name,
                clip_b=clip_b.name,
                clip_a_end_iso=end_a.isoformat(),
                clip_b_start_iso=start_b.isoformat(),
                overlap_seconds=overlap_seconds,
                note="Likely overlap detected from estimated adjacent clip timing.",
            )
        )

    return overlaps


def detect_scene_segments(
    file_path: Path,
    threshold: float,
    min_scene_length_seconds: float,
) -> list[SceneSegment]:
    try:
        from scenedetect import SceneManager, open_video
        from scenedetect.detectors import ContentDetector
    except ImportError as exc:
        raise RuntimeError(
            "Scene detection dependencies are missing. Install requirements.txt, which includes PySceneDetect and OpenCV."
        ) from exc

    video = open_video(str(file_path))
    scene_manager = SceneManager()
    scene_manager.add_detector(
        ContentDetector(
            threshold=threshold,
            min_scene_len=max(1, int(min_scene_length_seconds * 30)),
        )
    )
    scene_manager.detect_scenes(video=video, show_progress=False)
    scene_list = scene_manager.get_scene_list()

    segments: list[SceneSegment] = []
    for start_time, end_time in scene_list:
        start_seconds = start_time.get_seconds()
        end_seconds = end_time.get_seconds()
        duration = max(0.0, end_seconds - start_seconds)
        if duration <= 0:
            continue
        segments.append(
            SceneSegment(
                start=round(start_seconds, 3),
                end=round(end_seconds, 3),
                duration=round(duration, 3),
            )
        )

    return segments


def detect_visual_cut_segments(
    file_path: Path,
    templates_dir: Path,
    sample_interval_seconds: float,
    template_similarity_threshold: float,
    min_template_match_duration_seconds: float,
    static_screen_enabled: bool,
    static_motion_threshold: float,
    static_edge_density_threshold: float,
    static_text_like_threshold: float,
    min_static_duration_seconds: float,
) -> list[DetectedSegment]:
    template_paths: list[Path] = []
    if templates_dir.exists():
        template_paths = [
            path for path in templates_dir.iterdir() if path.suffix.lower() in {".png", ".jpg", ".jpeg"}
        ]

    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError("OpenCV is required for loading-screen template matching.") from exc

    def parse_region_hint(stem: str) -> tuple[str | None, str]:
        match = re.match(
            r"^(tl|tr|bl|br|tc|bc|cl|cr|top|bottom|left|right|center)(?:__|_)(.+)$",
            stem,
            re.IGNORECASE,
        )
        if not match:
            return None, stem
        return match.group(1).lower(), match.group(2)

    capture = cv2.VideoCapture(str(file_path))
    if not capture.isOpened():
        return []

    ok, first_frame = capture.read()
    if not ok or first_frame is None:
        capture.release()
        return []

    source_height, source_width = first_frame.shape[:2]
    base_width = 640
    scale_factor = min(1.0, base_width / max(1, source_width))
    scaled_width = max(1, int(source_width * scale_factor))
    scaled_height = max(1, int(source_height * scale_factor))

    def preprocess_frame(frame):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        resized = cv2.resize(gray, (scaled_width, scaled_height))
        edges = cv2.Canny(resized, 50, 150)
        return resized, edges

    def resolve_region(
        frame_gray,
        frame_edges,
        region_hint: str | None,
    ):
        height, width = frame_gray.shape[:2]
        x0, y0, x1, y1 = 0, 0, width, height
        if region_hint in {"br", "bottom", "right"}:
            x0 = width // 2 if region_hint in {"br", "right"} else 0
            y0 = height // 2 if region_hint in {"br", "bottom"} else 0
        elif region_hint in {"bl"}:
            x1 = width // 2
            y0 = height // 2
        elif region_hint in {"tr"}:
            x0 = width // 2
            y1 = height // 2
        elif region_hint in {"tl"}:
            x1 = width // 2
            y1 = height // 2
        elif region_hint == "top":
            y1 = height // 2
        elif region_hint == "left":
            x1 = width // 2
        elif region_hint == "tc":
            x0 = width // 4
            x1 = width - (width // 4)
            y1 = height // 2
        elif region_hint == "bc":
            x0 = width // 4
            x1 = width - (width // 4)
            y0 = height // 2
        elif region_hint == "cl":
            x1 = width - (width // 4)
            y0 = height // 4
            y1 = height - (height // 4)
        elif region_hint == "cr":
            x0 = width // 4
            y0 = height // 4
            y1 = height - (height // 4)
        elif region_hint == "center":
            x0 = width // 4
            x1 = width - (width // 4)
            y0 = height // 4
            y1 = height - (height // 4)

        return frame_gray[y0:y1, x0:x1], frame_edges[y0:y1, x0:x1]

    templates: list[tuple[str, object, object, object | None, object | None, float, str | None]] = []
    for template_path in template_paths:
        raw_image = cv2.imread(str(template_path), cv2.IMREAD_UNCHANGED)
        if raw_image is None:
            continue

        region_hint, cleaned_label = parse_region_hint(template_path.stem)

        if len(raw_image.shape) == 3 and raw_image.shape[2] == 4:
            bgr = raw_image[:, :, :3]
            alpha = raw_image[:, :, 3]
            image = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
            mask_source = alpha
        elif len(raw_image.shape) == 3:
            image = cv2.cvtColor(raw_image, cv2.COLOR_BGR2GRAY)
            mask_source = None
        else:
            image = raw_image
            mask_source = None

        template_height, template_width = image.shape[:2]
        scaled_size = (
            max(1, int(template_width * scale_factor)),
            max(1, int(template_height * scale_factor)),
        )
        template_scaled = cv2.resize(
            image,
            scaled_size,
        )
        template_edges = cv2.Canny(template_scaled, 50, 150)
        template_mask = None
        template_edge_mask = None
        if mask_source is not None:
            template_mask = cv2.resize(mask_source, scaled_size)
            template_mask = cv2.threshold(template_mask, 1, 255, cv2.THRESH_BINARY)[1]
            template_edge_mask = template_mask

        coverage = (template_scaled.shape[0] * template_scaled.shape[1]) / max(
            1,
            scaled_width * scaled_height,
        )
        templates.append(
            (
                cleaned_label,
                template_scaled,
                template_edges,
                template_mask,
                template_edge_mask,
                coverage,
                region_hint,
            ),
        )

    matched_ranges: list[tuple[float, float, str]] = []
    current_start: float | None = None
    current_label = "template_match"
    last_time = 0.0
    sample_time = 0.0

    while True:
        capture.set(cv2.CAP_PROP_POS_MSEC, sample_time * 1000.0)
        ok, frame = capture.read()
        if not ok or frame is None:
            break

        frame_small, frame_edges = preprocess_frame(frame)

        best_label = "template_match"
        similarity = 0.0
        for template_label, template_small, template_edge, template_mask, template_edge_mask, coverage, region_hint in templates:
            search_gray, search_edges = resolve_region(frame_small, frame_edges, region_hint)
            if (
                template_small.shape[0] > search_gray.shape[0]
                or template_small.shape[1] > search_gray.shape[1]
            ):
                continue

            if coverage >= 0.6:
                resized_template = cv2.resize(template_small, (search_gray.shape[1], search_gray.shape[0]))
                resized_template_edges = cv2.resize(template_edge, (search_edges.shape[1], search_edges.shape[0]))
                if template_mask is not None:
                    resized_mask = cv2.resize(template_mask, (search_gray.shape[1], search_gray.shape[0]))
                    gray_score = float(
                        cv2.matchTemplate(search_gray, resized_template, cv2.TM_CCORR_NORMED, mask=resized_mask)[0][0]
                    )
                    edge_score = float(
                        cv2.matchTemplate(search_edges, resized_template_edges, cv2.TM_CCORR_NORMED, mask=resized_mask)[0][0]
                    )
                else:
                    gray_score = float(
                        cv2.matchTemplate(search_gray, resized_template, cv2.TM_CCOEFF_NORMED)[0][0]
                    )
                    edge_score = float(
                        cv2.matchTemplate(search_edges, resized_template_edges, cv2.TM_CCOEFF_NORMED)[0][0]
                    )
            else:
                if template_mask is not None:
                    gray_score = float(
                        cv2.matchTemplate(search_gray, template_small, cv2.TM_CCORR_NORMED, mask=template_mask).max()
                    )
                    edge_score = float(
                        cv2.matchTemplate(search_edges, template_edge, cv2.TM_CCORR_NORMED, mask=template_edge_mask).max()
                    )
                else:
                    gray_score = float(
                        cv2.matchTemplate(search_gray, template_small, cv2.TM_CCOEFF_NORMED).max()
                    )
                    edge_score = float(
                        cv2.matchTemplate(search_edges, template_edge, cv2.TM_CCOEFF_NORMED).max()
                    )
            template_score = max(gray_score, edge_score)
            if template_score > similarity:
                similarity = template_score
                best_label = template_label

        is_match = similarity >= template_similarity_threshold
        if is_match and current_start is None:
            current_start = sample_time
            current_label = best_label
        elif is_match and current_start is not None:
            current_label = f"{current_label}|{best_label}" if best_label not in current_label.split("|") else current_label
        elif not is_match and current_start is not None:
            matched_ranges.append((current_start, sample_time, current_label))
            current_start = None

        last_time = sample_time
        sample_time += sample_interval_seconds

    if current_start is not None:
        matched_ranges.append((current_start, last_time + sample_interval_seconds, current_label))

    capture.release()

    merged_matches: list[tuple[float, float, str]] = []
    for start, end, label in matched_ranges:
        if not merged_matches:
            merged_matches.append((start, end, label))
            continue

        last_start, last_end, last_label = merged_matches[-1]
        if start <= last_end + max(sample_interval_seconds * 3.0, 1.5):
            merged_label_parts = sorted(set(last_label.split("|")) | set(label.split("|")))
            merged_matches[-1] = (last_start, max(last_end, end), "|".join(merged_label_parts))
        else:
            merged_matches.append((start, end, label))

    segments: list[DetectedSegment] = []
    for start, end, label in merged_matches:
        duration = round(end - start, 3)
        if duration < min_template_match_duration_seconds:
            continue
        segments.append(
            DetectedSegment(
                start=round(start, 3),
                end=round(end, 3),
                duration=duration,
                label=label,
            )
        )

    if static_screen_enabled:
        capture = cv2.VideoCapture(str(file_path))
        if capture.isOpened():
            static_matches: list[tuple[float, float, str]] = []
            previous_small = None
            current_start = None
            last_time = 0.0
            sample_time = 0.0

            while True:
                capture.set(cv2.CAP_PROP_POS_MSEC, sample_time * 1000.0)
                ok, frame = capture.read()
                if not ok or frame is None:
                    break

                frame_small, frame_edges = preprocess_frame(frame)
                edge_density = float((frame_edges > 0).mean())

                horizontal_projection = (frame_edges > 0).mean(axis=1)
                text_like_rows = float((horizontal_projection > 0.10).mean())

                if previous_small is None:
                    motion_value = 0.0
                    changed_pixel_ratio = 0.0
                else:
                    diff = cv2.absdiff(frame_small, previous_small)
                    motion_value = float(diff.mean())
                    changed_pixel_ratio = float((diff > 12).mean())

                is_static_menu = (
                    motion_value <= static_motion_threshold
                    and changed_pixel_ratio <= 0.18
                    and edge_density >= static_edge_density_threshold
                    and text_like_rows >= static_text_like_threshold
                )

                if is_static_menu and current_start is None:
                    current_start = sample_time
                elif not is_static_menu and current_start is not None:
                    static_matches.append((current_start, sample_time, "static_text_screen"))
                    current_start = None

                previous_small = frame_small
                last_time = sample_time
                sample_time += sample_interval_seconds

            if current_start is not None:
                static_matches.append(
                    (current_start, last_time + sample_interval_seconds, "static_text_screen")
                )

            capture.release()

            for start, end, label in static_matches:
                duration = round(end - start, 3)
                if duration < min_static_duration_seconds:
                    continue
                segments.append(
                    DetectedSegment(
                        start=round(start, 3),
                        end=round(end, 3),
                        duration=duration,
                        label=label,
                    )
                )

    segments.sort(key=lambda item: item.start)
    merged_segments: list[DetectedSegment] = []
    for segment in segments:
        if not merged_segments:
            merged_segments.append(segment)
            continue

        last = merged_segments[-1]
        if segment.start <= last.end + sample_interval_seconds and segment.label == last.label:
            merged_segments[-1] = DetectedSegment(
                start=last.start,
                end=max(last.end, segment.end),
                duration=round(max(last.end, segment.end) - last.start, 3),
                label=last.label,
            )
        else:
            merged_segments.append(segment)

    return merged_segments


def subtract_ranges(
    base_range: tuple[float, float],
    blocked_ranges: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    start, end = base_range
    if end <= start:
        return []

    current_ranges = [(start, end)]
    for blocked_start, blocked_end in sorted(blocked_ranges):
        if blocked_end <= blocked_start:
            continue

        next_ranges: list[tuple[float, float]] = []
        for current_start, current_end in current_ranges:
            if blocked_end <= current_start or blocked_start >= current_end:
                next_ranges.append((current_start, current_end))
                continue

            if blocked_start > current_start:
                next_ranges.append((current_start, blocked_start))
            if blocked_end < current_end:
                next_ranges.append((blocked_end, current_end))
        current_ranges = next_ranges

    return current_ranges


def merge_ranges(ranges: list[tuple[float, float]], gap_seconds: float) -> list[tuple[float, float]]:
    normalized = sorted((start, end) for start, end in ranges if end > start)
    if not normalized:
        return []

    merged: list[tuple[float, float]] = [normalized[0]]
    for start, end in normalized[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end + gap_seconds:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def align_range_to_scene_boundaries(
    start: float,
    end: float,
    scenes: list[SceneSegment],
) -> tuple[float, float]:
    if not scenes:
        return start, end

    aligned_start = start
    aligned_end = end

    for scene in scenes:
        if scene.start <= start <= scene.end:
            aligned_start = max(start, scene.start)
            break
        if scene.start >= start:
            aligned_start = scene.start
            break

    for scene in reversed(scenes):
        if scene.start <= end <= scene.end:
            aligned_end = min(end, scene.end)
            break
        if scene.end <= end:
            aligned_end = scene.end
            break

    if aligned_end <= aligned_start:
        return start, end
    return aligned_start, aligned_end


def build_keep_segments_for_clip(
    clip: ClipInfo,
    overlap_trim_seconds: float,
    minimum_keep_segment_seconds: float,
    merge_gap_seconds: float,
) -> list[KeepSegment]:
    if clip.duration_seconds is None or clip.duration_seconds <= 0:
        return []

    effective_clip_end = max(0.0, clip.duration_seconds - max(0.0, overlap_trim_seconds))
    if effective_clip_end <= 0:
        return []

    blocked_ranges = [(segment.start, segment.end) for segment in clip.black_segments]
    blocked_ranges.extend((segment.start, segment.end) for segment in clip.cut_segments)

    visible_ranges = subtract_ranges((0.0, effective_clip_end), blocked_ranges)
    merged_visible_ranges = merge_ranges(visible_ranges, gap_seconds=merge_gap_seconds)

    keep_segments: list[KeepSegment] = []
    for visible_start, visible_end in merged_visible_ranges:
        aligned_start, aligned_end = align_range_to_scene_boundaries(
            visible_start,
            visible_end,
            clip.scene_segments,
        )
        duration = round(aligned_end - aligned_start, 3)
        if duration < minimum_keep_segment_seconds:
            continue

        reason = "contiguous gameplay range after blocked segments removed"
        if overlap_trim_seconds > 0:
            reason += " and overlap tail trimmed"

        keep_segments.append(
            KeepSegment(
                start=round(aligned_start, 3),
                end=round(aligned_end, 3),
                duration=duration,
                reason=reason,
            )
        )

    return keep_segments


def apply_overlap_and_keep_segments(
    clips: list[ClipInfo],
    minimum_overlap_seconds: float,
    minimum_keep_segment_seconds: float,
    merge_gap_seconds: float,
) -> tuple[list[ClipInfo], list[OverlapInfo]]:
    sorted_clips = sort_clips(clips)
    overlaps = find_likely_overlaps(sorted_clips, minimum_overlap_seconds)

    overlap_trim_by_clip: dict[str, float] = {}
    for overlap in overlaps:
        overlap_trim_by_clip[overlap.clip_a] = max(
            overlap_trim_by_clip.get(overlap.clip_a, 0.0),
            overlap.overlap_seconds,
        )

    for clip in sorted_clips:
        clip.keep_segments = build_keep_segments_for_clip(
            clip=clip,
            overlap_trim_seconds=overlap_trim_by_clip.get(clip.name, 0.0),
            minimum_keep_segment_seconds=minimum_keep_segment_seconds,
            merge_gap_seconds=merge_gap_seconds,
        )

    return sorted_clips, overlaps


def should_reuse_cached_clip(
    cached_clip: ClipInfo | None,
    current_signature: str,
    reprocess_mode: Literal["auto", "all"],
) -> bool:
    if cached_clip is None:
        return False
    if reprocess_mode == "all":
        return False
    return cached_clip.file_signature == current_signature


def analyze_clips(
    app_config: AppConfig,
    input_dir: Path,
    output_dir: Path,
    review_dir: Path,
    log_path: Path,
    cache_path: Path,
    reprocess_mode: Literal["auto", "all"],
    per_clip_callback: Callable[[list[ClipInfo], list[OverlapInfo], list[str], ClipInfo], None] | None = None,
) -> Report:
    warnings: list[str] = []
    files = find_video_files(input_dir, app_config.analysis.supported_extensions)
    logging.info("Found %d supported video file(s).", len(files))

    if not files:
        warnings.append("No supported video files were found in the input directory.")

    cached_clips = load_clip_cache(cache_path) if app_config.analysis.reuse_analysis_by_default else {}
    clips: list[ClipInfo] = []
    reused_count = 0

    templates_dir = resolve_from_app_root(app_config.analysis.visual_cut_detection.templates_dir).resolve()
    legacy_templates_dir = resolve_from_app_root("presets/loading_templates").resolve()
    if not templates_dir.exists() and legacy_templates_dir.exists():
        templates_dir = legacy_templates_dir

    for file_path in files:
        current_signature = f"{file_path.stat().st_size}:{int(file_path.stat().st_mtime)}"
        cached_clip = cached_clips.get(str(file_path.resolve()))
        if should_reuse_cached_clip(cached_clip, current_signature, reprocess_mode):
            logging.info("Reusing cached analysis for %s", file_path.name)
            clips.append(cached_clip)
            reused_count += 1
            if per_clip_callback is not None:
                partial_clips, partial_overlaps = apply_overlap_and_keep_segments(
                    list(clips),
                    minimum_overlap_seconds=app_config.analysis.overlap_warning_min_seconds,
                    minimum_keep_segment_seconds=app_config.analysis.minimum_keep_segment_seconds,
                    merge_gap_seconds=app_config.analysis.merge_gap_seconds,
                )
                per_clip_callback(partial_clips, partial_overlaps, list(warnings), cached_clip)
            continue

        logging.info("Extracting metadata for %s", file_path.name)
        try:
            clip = extract_metadata(app_config.ffprobe_path, file_path)
        except Exception as exc:
            logging.exception("Metadata extraction failed for %s", file_path.name)
            warnings.append(f"Metadata extraction failed for '{file_path.name}': {exc}")
            continue

        if app_config.analysis.blackdetect.enabled:
            logging.info("Running blackdetect for %s", file_path.name)
            try:
                clip.black_segments = detect_black_segments(
                    ffmpeg_path=app_config.ffmpeg_path,
                    file_path=file_path,
                    min_duration=app_config.analysis.blackdetect.min_duration,
                    pixel_threshold=app_config.analysis.blackdetect.pixel_threshold,
                    picture_threshold=app_config.analysis.blackdetect.picture_threshold,
                )
            except Exception as exc:
                logging.exception("Blackdetect failed for %s", file_path.name)
                clip.warnings.append(f"Blackdetect failed: {exc}")

        if app_config.analysis.visual_cut_detection.enabled:
            logging.info("Running visual cut detection for %s", file_path.name)
            try:
                clip.cut_segments = detect_visual_cut_segments(
                    file_path=file_path,
                    templates_dir=templates_dir,
                    sample_interval_seconds=app_config.analysis.visual_cut_detection.sample_interval_seconds,
                    template_similarity_threshold=app_config.analysis.visual_cut_detection.template_similarity_threshold,
                    min_template_match_duration_seconds=app_config.analysis.visual_cut_detection.min_template_match_duration_seconds,
                    static_screen_enabled=app_config.analysis.visual_cut_detection.static_screen_enabled,
                    static_motion_threshold=app_config.analysis.visual_cut_detection.static_motion_threshold,
                    static_edge_density_threshold=app_config.analysis.visual_cut_detection.static_edge_density_threshold,
                    static_text_like_threshold=app_config.analysis.visual_cut_detection.static_text_like_threshold,
                    min_static_duration_seconds=app_config.analysis.visual_cut_detection.min_static_duration_seconds,
                )
            except Exception as exc:
                logging.exception("Visual cut detection failed for %s", file_path.name)
                clip.warnings.append(f"Visual cut detection failed: {exc}")

        if app_config.analysis.scene_detection.enabled:
            logging.info("Running scene detection for %s", file_path.name)
            try:
                clip.scene_segments = detect_scene_segments(
                    file_path=file_path,
                    threshold=app_config.analysis.scene_detection.threshold,
                    min_scene_length_seconds=app_config.analysis.scene_detection.min_scene_length_seconds,
                )
            except Exception as exc:
                logging.exception("Scene detection failed for %s", file_path.name)
                clip.warnings.append(f"Scene detection failed: {exc}")

        clips.append(clip)
        if per_clip_callback is not None:
            partial_clips, partial_overlaps = apply_overlap_and_keep_segments(
                list(clips),
                minimum_overlap_seconds=app_config.analysis.overlap_warning_min_seconds,
                minimum_keep_segment_seconds=app_config.analysis.minimum_keep_segment_seconds,
                merge_gap_seconds=app_config.analysis.merge_gap_seconds,
            )
            current_clip = next(item for item in partial_clips if item.path == clip.path)
            per_clip_callback(partial_clips, partial_overlaps, list(warnings), current_clip)

    if reused_count:
        logging.info("Reused cached analysis for %d unchanged clip(s).", reused_count)

    sorted_clips, overlaps = apply_overlap_and_keep_segments(
        clips,
        minimum_overlap_seconds=app_config.analysis.overlap_warning_min_seconds,
        minimum_keep_segment_seconds=app_config.analysis.minimum_keep_segment_seconds,
        merge_gap_seconds=app_config.analysis.merge_gap_seconds,
    )
    logging.info("Detected %d likely overlap(s).", len(overlaps))

    save_clip_cache(cache_path, sorted_clips)

    return Report(
        generated_at_iso=datetime.now().astimezone().isoformat(),
        input_dir=str(input_dir),
        output_dir=str(output_dir),
        review_dir=str(review_dir),
        log_path=str(log_path),
        ffmpeg_path=app_config.ffmpeg_path,
        ffprobe_path=app_config.ffprobe_path,
        clips=sorted_clips,
        overlaps=overlaps,
        exported_fight_clips=[],
        combined_video=None,
        warnings=warnings,
    )
