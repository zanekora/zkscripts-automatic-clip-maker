from __future__ import annotations

import logging
import math
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


def has_meaningful_alpha_mask(alpha_mask) -> bool:
    try:
        import numpy as np
    except ImportError:
        return False

    binary_mask = alpha_mask > 0
    coverage = float(binary_mask.mean())
    return 0.01 <= coverage <= 0.99


def derive_auto_foreground_mask(bgr_image):
    try:
        import cv2
        import numpy as np
    except ImportError:
        return None

    if bgr_image is None or len(bgr_image.shape) != 3 or bgr_image.shape[2] < 3:
        return None

    height, width = bgr_image.shape[:2]
    if height < 12 or width < 12:
        return None

    border = max(2, min(height, width) // 12)
    inset_x = max(border + 1, width // 5)
    inset_y = max(border + 1, height // 6)
    if inset_x >= width - inset_x or inset_y >= height - inset_y:
        return None

    grabcut_mask = np.full((height, width), cv2.GC_PR_BGD, dtype=np.uint8)
    grabcut_mask[:border, :] = cv2.GC_BGD
    grabcut_mask[height - border :, :] = cv2.GC_BGD
    grabcut_mask[:, :border] = cv2.GC_BGD
    grabcut_mask[:, width - border :] = cv2.GC_BGD
    grabcut_mask[inset_y : height - inset_y, inset_x : width - inset_x] = cv2.GC_PR_FGD

    background_model = np.zeros((1, 65), np.float64)
    foreground_model = np.zeros((1, 65), np.float64)
    try:
        cv2.grabCut(
            bgr_image,
            grabcut_mask,
            None,
            background_model,
            foreground_model,
            5,
            cv2.GC_INIT_WITH_MASK,
        )
    except cv2.error:
        return None

    foreground_mask = np.where(
        (grabcut_mask == cv2.GC_FGD) | (grabcut_mask == cv2.GC_PR_FGD),
        255,
        0,
    ).astype("uint8")
    foreground_mask = cv2.morphologyEx(
        foreground_mask,
        cv2.MORPH_OPEN,
        np.ones((2, 2), np.uint8),
    )
    foreground_mask = cv2.dilate(foreground_mask, np.ones((2, 2), np.uint8), iterations=1)

    coverage = float((foreground_mask > 0).mean())
    if coverage < 0.01 or coverage > 0.70:
        return None

    return foreground_mask


def detect_active_fight_segments(
    file_path: Path,
    templates_dir: Path,
    sample_interval_seconds: float,
    similarity_threshold: float,
    min_match_duration_seconds: float,
    leading_keep_seconds: float,
    trailing_keep_seconds: float,
    min_consecutive_hits: int,
    release_after_misses: int,
    require_dynamic_frame: bool,
    max_static_changed_pixel_ratio: float,
) -> tuple[list[DetectedSegment], list[str]]:
    template_dirs = [templates_dir]
    legacy_templates_dir = resolve_from_app_root("presets/active_fight_templates").resolve()
    if legacy_templates_dir != templates_dir:
        template_dirs.append(legacy_templates_dir)

    template_paths: list[Path] = []
    seen_template_paths: set[Path] = set()
    for template_dir in template_dirs:
        if not template_dir.exists():
            continue
        for path in template_dir.iterdir():
            if path.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
                continue
            resolved = path.resolve()
            if resolved in seen_template_paths:
                continue
            seen_template_paths.add(resolved)
            template_paths.append(path)
    if not template_paths:
        return [], []

    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError("OpenCV is required for active fight template matching.") from exc

    def parse_region_hint(stem: str) -> tuple[str | None, str]:
        match = re.match(
            r"^(tl|tr|bl|br|tc|bc|cl|cr|top|bottom|left|right|center)(?:__|_)(.+)$",
            stem,
            re.IGNORECASE,
        )
        if not match:
            return None, stem
        return match.group(1).lower(), match.group(2)

    def resolve_region(frame_gray, frame_edges, region_hint: str | None, template_shape: tuple[int, int] | None):
        height, width = frame_gray.shape[:2]
        x0, y0, x1, y1 = 0, 0, width, height
        if region_hint in {"br", "bottom", "right"}:
            x0 = width // 2 if region_hint in {"br", "right"} else 0
            y0 = height // 2 if region_hint in {"br", "bottom"} else 0
        elif region_hint == "bc":
            x0 = width // 4
            x1 = width - (width // 4)
            y0 = height // 2
        elif region_hint == "tc":
            x0 = width // 4
            x1 = width - (width // 4)
            y1 = height // 2
        elif region_hint == "tr":
            x0 = width // 2
            y1 = height // 2
        elif region_hint == "tl":
            x1 = width // 2
            y1 = height // 2
        elif region_hint == "bl":
            x1 = width // 2
            y0 = height // 2
        elif region_hint == "left":
            x1 = width // 2
        elif region_hint == "top":
            y1 = height // 2
        elif region_hint == "center":
            x0 = width // 4
            x1 = width - (width // 4)
            y0 = height // 4
            y1 = height - (height // 4)

        # Positive in-fight UI is usually anchored HUD, so a region prefix should
        # search a tighter semantic window than a whole half-screen.
        if template_shape is not None and region_hint is not None:
            template_height, template_width = template_shape

            def centered_band(total: int, desired: int) -> tuple[int, int]:
                clamped = max(1, min(total, desired))
                start = max(0, (total - clamped) // 2)
                return start, min(total, start + clamped)

            region_width = max(1, x1 - x0)
            region_height = max(1, y1 - y0)

            if region_hint == "tc":
                inner_x0, inner_x1 = centered_band(region_width, max(template_width * 3, region_width // 3))
                band_height = min(region_height, max(template_height * 4, region_height // 6))
                x0 += inner_x0
                x1 = x0 + max(1, inner_x1 - inner_x0)
                y1 = y0 + max(1, band_height)
            elif region_hint == "bc":
                inner_x0, inner_x1 = centered_band(region_width, max(template_width * 3, region_width // 3))
                band_height = min(region_height, max(template_height * 4, region_height // 6))
                x0 += inner_x0
                x1 = x0 + max(1, inner_x1 - inner_x0)
                y0 = max(y0, y1 - max(1, band_height))
            elif region_hint in {"tr", "tl"}:
                band_width = min(region_width, max(template_width * 3, region_width // 2))
                band_height = min(region_height, max(template_height * 4, region_height // 5))
                if region_hint == "tr":
                    x0 = max(x0, x1 - band_width)
                else:
                    x1 = min(x1, x0 + band_width)
                y1 = min(y1, y0 + band_height)
            elif region_hint in {"br", "bl"}:
                band_width = min(region_width, max(template_width * 3, region_width // 2))
                band_height = min(region_height, max(template_height * 4, region_height // 5))
                if region_hint == "br":
                    x0 = max(x0, x1 - band_width)
                else:
                    x1 = min(x1, x0 + band_width)
                y0 = max(y0, y1 - band_height)
            elif region_hint in {"top", "bottom"}:
                band_height = min(region_height, max(template_height * 4, region_height // 5))
                if region_hint == "top":
                    y1 = min(y1, y0 + band_height)
                else:
                    y0 = max(y0, y1 - band_height)
            elif region_hint in {"left", "right"}:
                band_width = min(region_width, max(template_width * 3, region_width // 3))
                if region_hint == "left":
                    x1 = min(x1, x0 + band_width)
                else:
                    x0 = max(x0, x1 - band_width)
            elif region_hint in {"cl", "cr"}:
                band_width = min(region_width, max(template_width * 3, region_width // 3))
                inner_y0, inner_y1 = centered_band(region_height, max(template_height * 4, region_height // 2))
                y0 += inner_y0
                y1 = y0 + max(1, inner_y1 - inner_y0)
                if region_hint == "cl":
                    x1 = min(x1, x0 + band_width)
                else:
                    x0 = max(x0, x1 - band_width)
            elif region_hint == "center":
                inner_x0, inner_x1 = centered_band(region_width, max(template_width * 3, region_width // 2))
                inner_y0, inner_y1 = centered_band(region_height, max(template_height * 4, region_height // 3))
                x0 += inner_x0
                x1 = x0 + max(1, inner_x1 - inner_x0)
                y0 += inner_y0
                y1 = y0 + max(1, inner_y1 - inner_y0)

        return frame_gray[y0:y1, x0:x1], frame_edges[y0:y1, x0:x1], x0, y0

    capture = cv2.VideoCapture(str(file_path))
    if not capture.isOpened():
        return [], []

    ok, first_frame = capture.read()
    if not ok or first_frame is None:
        capture.release()
        return [], []

    source_height, source_width = first_frame.shape[:2]
    fps = max(1.0, float(capture.get(cv2.CAP_PROP_FPS)))
    total_frames = max(1.0, float(capture.get(cv2.CAP_PROP_FRAME_COUNT)))
    clip_duration_seconds = total_frames / fps
    sample_frame_stride = max(1, int(round(fps * sample_interval_seconds)))
    base_width = 640
    scale_factor = min(1.0, base_width / max(1, source_width))
    scaled_width = max(1, int(source_width * scale_factor))
    scaled_height = max(1, int(source_height * scale_factor))

    templates: list[
        tuple[
            str,
            object,
            object,
            object | None,
            float,
            str | None,
            str,
            object | None,
            tuple[int, int] | None,
            float,
            float,
        ]
    ] = []
    for template_path in template_paths:
        raw_image = cv2.imread(str(template_path), cv2.IMREAD_UNCHANGED)
        if raw_image is None:
            continue
        region_hint, label = parse_region_hint(template_path.stem)
        mask_note = "unmasked"
        if len(raw_image.shape) == 3 and raw_image.shape[2] == 4:
            bgr = raw_image[:, :, :3]
            alpha = raw_image[:, :, 3]
            image = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
            if has_meaningful_alpha_mask(alpha):
                mask_source = alpha
                mask_note = "alpha_mask"
            else:
                mask_source = derive_auto_foreground_mask(bgr)
                if mask_source is not None:
                    mask_note = "auto_mask"
        elif len(raw_image.shape) == 3:
            image = cv2.cvtColor(raw_image, cv2.COLOR_BGR2GRAY)
            mask_source = derive_auto_foreground_mask(raw_image)
            if mask_source is not None:
                mask_note = "auto_mask"
        else:
            image = raw_image
            mask_source = None
        template_height, template_width = image.shape[:2]
        scaled_size = (
            max(1, int(template_width * scale_factor)),
            max(1, int(template_height * scale_factor)),
        )
        template_scaled = cv2.resize(image, scaled_size)
        template_edges = cv2.Canny(template_scaled, 50, 150)
        template_mask = None
        if mask_source is not None:
            template_mask = cv2.resize(mask_source, scaled_size)
            template_mask = cv2.threshold(template_mask, 1, 255, cv2.THRESH_BINARY)[1]

        tracker_template = None
        tracker_offset = None
        tracker_min_score = 0.0
        tracker_min_std = 0.0
        if template_mask is not None:
            component_count, labels, stats, _ = cv2.connectedComponentsWithStats(template_mask, 8)
            if component_count > 1:
                largest_component = max(
                    range(1, component_count),
                    key=lambda index: int(stats[index, cv2.CC_STAT_AREA]),
                )
                component_x, component_y, component_width, component_height, component_area = stats[largest_component]
                if component_area > 0:
                    padding = 2
                    crop_x0 = max(0, int(component_x) - padding)
                    crop_y0 = max(0, int(component_y) - padding)
                    crop_x1 = min(template_scaled.shape[1], int(component_x + component_width) + padding)
                    crop_y1 = min(template_scaled.shape[0], int(component_y + component_height) + padding)
                    tracker_crop = template_scaled[crop_y0:crop_y1, crop_x0:crop_x1]
                    if tracker_crop.size > 0 and tracker_crop.shape[0] >= 4 and tracker_crop.shape[1] >= 4:
                        tracker_template = tracker_crop
                        tracker_offset = (crop_x0, crop_y0)
                        tracker_min_score = 0.20
                        tracker_min_std = max(3.0, float(tracker_crop.std()) * 0.12)
        coverage = (template_scaled.shape[0] * template_scaled.shape[1]) / max(1, scaled_width * scaled_height)
        templates.append(
            (
                label,
                template_scaled,
                template_edges,
                template_mask,
                coverage,
                region_hint,
                mask_note,
                tracker_template,
                tracker_offset,
                tracker_min_score,
                tracker_min_std,
            )
        )

    if not templates:
        capture.release()
        return [], []

    auto_mask_count = sum(1 for _, _, _, _, _, _, mask_note, _, _, _, _ in templates if mask_note == "auto_mask")
    debug_notes = [f"Loaded {len(templates)} active fight template(s)."]
    if auto_mask_count:
        debug_notes.append(f"Auto-derived foreground mask for {auto_mask_count} active fight template(s).")
    matched_ranges: list[tuple[float, float, str, tuple[int, int] | None]] = []
    current_start: float | None = None
    current_label = "active_fight"
    current_best_score = 0.0
    current_tracker_template = None
    current_tracker_anchor: tuple[int, int] | None = None
    current_tracker_min_score = 0.0
    current_tracker_min_std = 0.0
    consecutive_hits = 0
    consecutive_misses = 0
    pending_start_time: float | None = None
    pending_label = "active_fight"
    pending_tracker_template = None
    pending_tracker_anchor: tuple[int, int] | None = None
    pending_tracker_min_score = 0.0
    pending_tracker_min_std = 0.0
    last_released_anchor: tuple[int, int] | None = None
    last_released_end = -1.0
    reacquire_cooldown_seconds = max(
        trailing_keep_seconds,
        sample_interval_seconds * max(1, min_consecutive_hits + release_after_misses),
    )
    frame_index = 0
    last_time = 0.0
    previous_frame_small = None

    capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
    while True:
        ok, frame = capture.read()
        if not ok or frame is None:
            break
        if frame_index % sample_frame_stride != 0:
            frame_index += 1
            continue

        sample_time = frame_index / fps
        frame_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        frame_small = cv2.resize(frame_gray, (scaled_width, scaled_height))
        frame_edges = cv2.Canny(frame_small, 50, 150)
        changed_pixel_ratio = 1.0
        if previous_frame_small is not None:
            diff = cv2.absdiff(frame_small, previous_frame_small)
            changed_pixel_ratio = float((diff > 12).mean())
        previous_frame_small = frame_small

        best_score = 0.0
        best_label = "active_fight"
        best_match_location: tuple[int, int] | None = None
        best_tracker_template = None
        best_tracker_anchor: tuple[int, int] | None = None
        best_tracker_min_score = 0.0
        best_tracker_min_std = 0.0
        for (
            label,
            template_small,
            template_edges,
            template_mask,
            coverage,
            region_hint,
            _,
            tracker_template,
            tracker_offset,
            tracker_min_score,
            tracker_min_std,
        ) in templates:
            search_gray, search_edges, search_x0, search_y0 = resolve_region(
                frame_small,
                frame_edges,
                region_hint,
                template_small.shape[:2],
            )
            if template_small.shape[0] > search_gray.shape[0] or template_small.shape[1] > search_gray.shape[1]:
                continue

            match_location = (search_x0, search_y0)
            if coverage >= 0.4:
                resized_template = cv2.resize(template_small, (search_gray.shape[1], search_gray.shape[0]))
                resized_edges = cv2.resize(template_edges, (search_edges.shape[1], search_edges.shape[0]))
                if template_mask is not None:
                    resized_mask = cv2.resize(template_mask, (search_gray.shape[1], search_gray.shape[0]))
                    gray_score = float(cv2.matchTemplate(search_gray, resized_template, cv2.TM_CCORR_NORMED, mask=resized_mask)[0][0])
                    edge_score = float(cv2.matchTemplate(search_edges, resized_edges, cv2.TM_CCORR_NORMED, mask=resized_mask)[0][0])
                else:
                    gray_score = float(cv2.matchTemplate(search_gray, resized_template, cv2.TM_CCOEFF_NORMED)[0][0])
                    edge_score = float(cv2.matchTemplate(search_edges, resized_edges, cv2.TM_CCOEFF_NORMED)[0][0])
            else:
                if template_mask is not None:
                    gray_result = cv2.matchTemplate(search_gray, template_small, cv2.TM_CCORR_NORMED, mask=template_mask)
                    edge_result = cv2.matchTemplate(search_edges, template_edges, cv2.TM_CCORR_NORMED, mask=template_mask)
                else:
                    gray_result = cv2.matchTemplate(search_gray, template_small, cv2.TM_CCOEFF_NORMED)
                    edge_result = cv2.matchTemplate(search_edges, template_edges, cv2.TM_CCOEFF_NORMED)
                _, gray_score, _, gray_loc = cv2.minMaxLoc(gray_result)
                _, edge_score, _, edge_loc = cv2.minMaxLoc(edge_result)
                winning_loc = gray_loc if gray_score >= edge_score else edge_loc
                match_location = (search_x0 + winning_loc[0], search_y0 + winning_loc[1])
            score = max(gray_score, edge_score)

            if not math.isfinite(gray_score):
                gray_score = 0.0
            if not math.isfinite(edge_score):
                edge_score = 0.0
            score = max(gray_score, edge_score)
            if not math.isfinite(score):
                score = 0.0

            if score > best_score:
                best_score = score
                best_label = label
                best_match_location = match_location
                best_tracker_template = tracker_template
                if tracker_template is not None and tracker_offset is not None and best_match_location is not None:
                    best_tracker_anchor = (
                        best_match_location[0] + tracker_offset[0],
                        best_match_location[1] + tracker_offset[1],
                    )
                else:
                    best_tracker_anchor = best_match_location
                best_tracker_min_score = tracker_min_score
                best_tracker_min_std = tracker_min_std

        dynamic_ok = (not require_dynamic_frame) or (changed_pixel_ratio >= max_static_changed_pixel_ratio)
        raw_hit = best_score >= similarity_threshold and dynamic_ok
        hit = False

        def validate_tracker(
            frame_gray,
            tracker_template,
            anchor_location: tuple[int, int] | None,
            search_tolerance: int,
            minimum_score: float,
            minimum_std: float,
        ) -> tuple[bool, tuple[int, int] | None]:
            if tracker_template is None or anchor_location is None:
                return False, None

            anchor_x, anchor_y = anchor_location
            tolerance = max(0, search_tolerance)
            x0 = max(0, anchor_x - tolerance)
            y0 = max(0, anchor_y - tolerance)
            x1 = min(frame_gray.shape[1], anchor_x + tracker_template.shape[1] + tolerance)
            y1 = min(frame_gray.shape[0], anchor_y + tracker_template.shape[0] + tolerance)
            local_region = frame_gray[y0:y1, x0:x1]
            if (
                local_region.shape[0] < tracker_template.shape[0]
                or local_region.shape[1] < tracker_template.shape[1]
            ):
                return False, None

            local_result = cv2.matchTemplate(local_region, tracker_template, cv2.TM_CCOEFF_NORMED)
            _, local_score, _, local_location = cv2.minMaxLoc(local_result)
            candidate_x = x0 + local_location[0]
            candidate_y = y0 + local_location[1]
            candidate_patch = frame_gray[
                candidate_y : candidate_y + tracker_template.shape[0],
                candidate_x : candidate_x + tracker_template.shape[1],
            ]
            candidate_std = float(candidate_patch.std())
            return (
                local_score >= minimum_score and candidate_std >= minimum_std,
                (candidate_x, candidate_y),
            )

        if current_start is not None and current_tracker_template is not None and current_tracker_anchor is not None:
            tracker_hit, updated_anchor = validate_tracker(
                frame_small,
                current_tracker_template,
                current_tracker_anchor,
                search_tolerance=max(10, current_tracker_template.shape[1] // 2),
                minimum_score=current_tracker_min_score,
                minimum_std=current_tracker_min_std,
            )
            if tracker_hit:
                hit = True
                current_tracker_anchor = updated_anchor
        elif raw_hit:
            tracker_hit, updated_anchor = validate_tracker(
                frame_small,
                best_tracker_template,
                best_tracker_anchor,
                search_tolerance=4,
                minimum_score=best_tracker_min_score,
                minimum_std=best_tracker_min_std,
            )
            if best_tracker_template is None:
                tracker_hit = best_match_location is not None
                updated_anchor = best_match_location
            hit = tracker_hit
            if hit:
                best_tracker_anchor = updated_anchor

        if hit:
            if current_start is None and sample_time < (last_released_end + reacquire_cooldown_seconds):
                consecutive_hits = 0
                consecutive_misses = 0
                pending_start_time = None
                pending_tracker_template = None
                pending_tracker_anchor = None
                pending_tracker_min_score = 0.0
                pending_tracker_min_std = 0.0
                last_time = sample_time
                frame_index += 1
                continue
            if (
                current_start is None
                and last_released_anchor is not None
                and best_tracker_anchor is not None
                and sample_time >= (clip_duration_seconds * 0.80)
            ):
                max_anchor_delta_x = max(24, template_scaled.shape[1])
                max_anchor_delta_y = max(16, template_scaled.shape[0] * 2)
                if (
                    abs(best_tracker_anchor[0] - last_released_anchor[0]) > max_anchor_delta_x
                    or abs(best_tracker_anchor[1] - last_released_anchor[1]) > max_anchor_delta_y
                ):
                    consecutive_hits = 0
                    consecutive_misses = 0
                    pending_start_time = None
                    pending_tracker_template = None
                    pending_tracker_anchor = None
                    pending_tracker_min_score = 0.0
                    pending_tracker_min_std = 0.0
                    last_time = sample_time
                    frame_index += 1
                    continue
            consecutive_hits += 1
            consecutive_misses = 0
            if pending_start_time is None:
                pending_start_time = sample_time
                pending_label = best_label
                pending_tracker_template = best_tracker_template
                pending_tracker_anchor = best_tracker_anchor
                pending_tracker_min_score = best_tracker_min_score
                pending_tracker_min_std = best_tracker_min_std
            if current_start is None and consecutive_hits >= min_consecutive_hits:
                current_start = max(0.0, pending_start_time - leading_keep_seconds)
                current_label = pending_label
                current_best_score = best_score
                current_tracker_template = pending_tracker_template
                current_tracker_anchor = pending_tracker_anchor
                current_tracker_min_score = pending_tracker_min_score
                current_tracker_min_std = pending_tracker_min_std
                debug_notes.append(
                    f"active_match_start t={current_start:.2f}s template={pending_label} score={best_score:.3f} dynamic={changed_pixel_ratio:.3f}"
                )
        elif current_start is not None:
            consecutive_misses += 1
            consecutive_hits = 0
            if consecutive_misses >= release_after_misses:
                release_end = sample_time + trailing_keep_seconds
                matched_ranges.append((current_start, release_end, current_label, current_tracker_anchor))
                last_released_end = max(last_released_end, release_end)
                last_released_anchor = current_tracker_anchor
                debug_notes.append(
                    f"active_match_end t={release_end:.2f}s template={current_label} peak_score={current_best_score:.3f}"
                )
                current_start = None
                current_tracker_template = None
                current_tracker_anchor = None
                current_tracker_min_score = 0.0
                current_tracker_min_std = 0.0
                current_best_score = 0.0
                consecutive_misses = 0
                pending_start_time = None
                pending_tracker_template = None
                pending_tracker_anchor = None
                pending_tracker_min_score = 0.0
                pending_tracker_min_std = 0.0
        else:
            consecutive_hits = 0
            consecutive_misses = 0
            pending_start_time = None
            pending_tracker_template = None
            pending_tracker_anchor = None
            pending_tracker_min_score = 0.0
            pending_tracker_min_std = 0.0

        if hit and current_start is not None:
            current_label = best_label
            current_best_score = max(current_best_score, best_score)

        last_time = sample_time
        frame_index += 1

    if current_start is not None:
        release_end = last_time + trailing_keep_seconds
        matched_ranges.append((current_start, release_end, current_label, current_tracker_anchor))
        last_released_end = max(last_released_end, release_end)
        last_released_anchor = current_tracker_anchor
        debug_notes.append(
            f"active_match_end t={release_end:.2f}s template={current_label} peak_score={current_best_score:.3f}"
        )

    capture.release()

    merged_anchor_ranges: list[tuple[float, float, str, tuple[int, int] | None]] = []
    sorted_ranges = sorted(matched_ranges, key=lambda item: (item[0], item[1]))
    anchor_merge_gap_seconds = max(8.0, trailing_keep_seconds)
    anchor_merge_delta_x = max(20, template_scaled.shape[1] // 4)
    anchor_merge_delta_y = max(10, template_scaled.shape[0])
    anchor_merge_start_time = clip_duration_seconds * 0.25
    for start, end, label, anchor in sorted_ranges:
        if not merged_anchor_ranges:
            merged_anchor_ranges.append((start, end, label, anchor))
            continue
        last_start, last_end, last_label, last_anchor = merged_anchor_ranges[-1]
        gap_seconds = start - last_end
        anchor_close = (
            anchor is not None
            and last_anchor is not None
            and abs(anchor[0] - last_anchor[0]) <= anchor_merge_delta_x
            and abs(anchor[1] - last_anchor[1]) <= anchor_merge_delta_y
        )
        allow_anchor_bridge = last_end >= anchor_merge_start_time
        if gap_seconds <= trailing_keep_seconds or (
            allow_anchor_bridge and gap_seconds <= anchor_merge_gap_seconds and anchor_close
        ):
            merged_anchor_ranges[-1] = (last_start, max(last_end, end), last_label, anchor or last_anchor)
        else:
            merged_anchor_ranges.append((start, end, label, anchor))

    segments: list[DetectedSegment] = []
    for start, end, _, _ in merged_anchor_ranges:
        duration = round(end - start, 3)
        if duration < min_match_duration_seconds:
            continue
        segments.append(
            DetectedSegment(
                start=round(start, 3),
                end=round(end, 3),
                duration=duration,
                label="active_fight_template",
            )
        )

    return segments, debug_notes


def detect_visual_cut_segments(
    file_path: Path,
    templates_dirs: list[Path],
    sample_interval_seconds: float,
    template_similarity_threshold: float,
    min_template_match_duration_seconds: float,
    template_only_cut_requires_static: bool,
    unscoped_template_enabled: bool,
    small_template_late_match_enabled: bool,
    small_template_max_coverage: float,
    small_template_extra_similarity: float,
    sticky_region_match_enabled: bool,
    sticky_region_min_consecutive_hits: int,
    sticky_region_release_seconds: float,
    flash_transition_enabled: bool,
    flash_brightness_delta_threshold: float,
    flash_changed_pixel_ratio_threshold: float,
    flash_bright_pixel_ratio_threshold: float,
    flash_follow_window_seconds: float,
    flash_terminal_tail_enabled: bool,
    terminal_region_detector_enabled: bool,
    terminal_region_start_fraction: float,
    terminal_region_min_template_hits: int,
    terminal_template_min_unique_matches: int,
    terminal_large_template_min_coverage: float,
    terminal_region_edge_density_threshold: float,
    terminal_region_text_like_threshold: float,
    terminal_region_min_duration_seconds: float,
    static_screen_enabled: bool,
    static_motion_threshold: float,
    static_edge_density_threshold: float,
    static_text_like_threshold: float,
    min_static_duration_seconds: float,
) -> tuple[list[DetectedSegment], list[str]]:
    template_priority = {
        "terminal_templates": 3,
        "partial_templates": 2,
        "fullscreen_templates": 1,
    }
    selected_template_paths: dict[str, Path] = {}
    selected_priorities: dict[str, int] = {}
    for templates_dir in templates_dirs:
        if not templates_dir.exists():
            continue
        for path in templates_dir.iterdir():
            if path.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
                continue
            stem = path.stem.lower()
            priority = template_priority.get(path.parent.name.lower(), 0)
            if stem not in selected_template_paths or priority > selected_priorities[stem]:
                selected_template_paths[stem] = path
                selected_priorities[stem] = priority
    template_paths: list[Path] = list(selected_template_paths.values())

    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError("OpenCV is required for loading-screen template matching.") from exc

    def parse_template_metadata(stem: str) -> tuple[str | None, str, bool]:
        match = re.match(
            r"^(tl|tr|bl|br|tc|bc|cl|cr|top|bottom|left|right|center)(?:__|_)(.+)$",
            stem,
            re.IGNORECASE,
        )
        region_hint: str | None = None
        cleaned_label = stem
        if match:
            region_hint = match.group(1).lower()
            cleaned_label = match.group(2)

        normalized_label = cleaned_label.lower()
        terminal_keywords = (
            "terminal",
            "result",
            "victory",
            "triumph",
            "win",
            "lose",
            "loss",
            "defeat",
            "continue",
            "share",
        )
        is_terminal_candidate = any(keyword in normalized_label for keyword in terminal_keywords)

        return region_hint, cleaned_label, is_terminal_candidate

    capture = cv2.VideoCapture(str(file_path))
    if not capture.isOpened():
        return [], []

    ok, first_frame = capture.read()
    if not ok or first_frame is None:
        capture.release()
        return [], []

    source_height, source_width = first_frame.shape[:2]
    total_frames = max(1.0, float(capture.get(cv2.CAP_PROP_FRAME_COUNT)))
    source_fps = max(1.0, float(capture.get(cv2.CAP_PROP_FPS)))
    clip_duration_seconds = total_frames / source_fps
    sample_frame_stride = max(1, int(round(source_fps * sample_interval_seconds)))
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

    templates: list[tuple[str, str, str, bool, object, object, object | None, object | None, float, str | None, str]] = []
    for template_path in template_paths:
        raw_image = cv2.imread(str(template_path), cv2.IMREAD_UNCHANGED)
        if raw_image is None:
            continue

        region_hint, cleaned_label, is_terminal_candidate = parse_template_metadata(template_path.stem)
        template_group = template_path.parent.name.lower()
        if template_group == "terminal_templates":
            is_terminal_candidate = True

        mask_note = "unmasked"
        if len(raw_image.shape) == 3 and raw_image.shape[2] == 4:
            bgr = raw_image[:, :, :3]
            alpha = raw_image[:, :, 3]
            image = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
            if has_meaningful_alpha_mask(alpha):
                mask_source = alpha
                mask_note = "alpha_mask"
            else:
                mask_source = derive_auto_foreground_mask(bgr)
                if mask_source is not None:
                    mask_note = "auto_mask"
        elif len(raw_image.shape) == 3:
            image = cv2.cvtColor(raw_image, cv2.COLOR_BGR2GRAY)
            mask_source = derive_auto_foreground_mask(raw_image)
            if mask_source is not None:
                mask_note = "auto_mask"
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
                template_path.stem,
                cleaned_label,
                template_group,
                is_terminal_candidate,
                template_scaled,
                template_edges,
                template_mask,
                template_edge_mask,
                coverage,
                region_hint,
                mask_note,
            ),
        )

    debug_notes: list[str] = []
    debug_notes.append(f"Loaded {len(templates)} cut template(s).")
    auto_mask_count = sum(1 for *_, mask_note in templates if mask_note == "auto_mask")
    if auto_mask_count:
        debug_notes.append(f"Auto-derived foreground mask for {auto_mask_count} cut template(s).")

    def is_terminal_label(label: str) -> bool:
        return label.startswith("terminal_") or "terminal_" in label

    matched_ranges: list[tuple[float, float, str]] = []
    current_start: float | None = None
    current_label = "template_match"
    sticky_start: float | None = None
    sticky_label = "template_match"
    sticky_hits = 0
    sticky_last_match_time = 0.0
    pending_flash_time: float | None = None
    terminal_cut_start: float | None = None
    region_hit_counts: dict[str, int] = {}
    region_first_match_time: dict[str, float] = {}
    terminal_template_hit_counts: dict[str, int] = {}
    terminal_template_first_hit: dict[str, float] = {}
    terminal_template_coverage: dict[str, float] = {}
    last_time = 0.0
    sample_time = 0.0
    previous_frame_small = None

    capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
    frame_index = 0
    while True:
        ok, frame = capture.read()
        if not ok or frame is None:
            break
        if frame_index % sample_frame_stride != 0:
            frame_index += 1
            continue

        sample_time = frame_index / source_fps

        frame_small, frame_edges = preprocess_frame(frame)

        brightness_delta = 0.0
        changed_pixel_ratio = 0.0
        bright_pixel_ratio = float((frame_small > 205).mean())
        if previous_frame_small is not None:
            diff = cv2.absdiff(frame_small, previous_frame_small)
            brightness_delta = float(diff.mean())
            changed_pixel_ratio = float((diff > 20).mean())
            if (
                flash_transition_enabled
                and brightness_delta >= flash_brightness_delta_threshold
                and changed_pixel_ratio >= flash_changed_pixel_ratio_threshold
                and bright_pixel_ratio >= flash_bright_pixel_ratio_threshold
            ):
                pending_flash_time = sample_time
        previous_frame_small = frame_small

        edge_density_for_frame = float((frame_edges > 0).mean())
        horizontal_projection_for_frame = (frame_edges > 0).mean(axis=1)
        text_like_rows_for_frame = float((horizontal_projection_for_frame > 0.10).mean())
        static_like_frame = (
            brightness_delta <= static_motion_threshold
            and changed_pixel_ratio <= 0.18
            and edge_density_for_frame >= static_edge_density_threshold
            and text_like_rows_for_frame >= static_text_like_threshold
        )

        best_template_stem = "template_match"
        best_label = "template_match"
        best_region_hint: str | None = None
        best_coverage = 1.0
        similarity = 0.0
        region_scores_this_frame: dict[str, float] = {}
        template_scores_this_frame: list[tuple[str, str | None, str, bool, float, float]] = []
        for template_stem, template_label, template_group, is_terminal_candidate, template_small, template_edge, template_mask, template_edge_mask, coverage, region_hint, _ in templates:
            if region_hint is None and not unscoped_template_enabled and template_group != "terminal_templates":
                continue
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
            if region_hint is not None:
                region_scores_this_frame[region_hint] = max(
                    region_scores_this_frame.get(region_hint, 0.0),
                    template_score,
                )
            template_scores_this_frame.append(
                (template_stem, region_hint, template_group, is_terminal_candidate, template_score, coverage)
            )
            if template_score > similarity:
                similarity = template_score
                best_template_stem = template_stem
                best_label = template_label
                best_region_hint = region_hint
                best_coverage = coverage

        is_match = similarity >= template_similarity_threshold
        late_clip_active = sample_time >= (clip_duration_seconds * terminal_region_start_fraction)
        best_is_terminal_group = any(
            stem == best_template_stem and group == "terminal_templates"
            for stem, _, group, _, _, _ in template_scores_this_frame
        )
        small_template_late_match = (
            small_template_late_match_enabled
            and late_clip_active
            and not best_is_terminal_group
            and best_coverage <= small_template_max_coverage
            and similarity >= (template_similarity_threshold + small_template_extra_similarity)
        )
        template_can_cut = (
            ((not best_is_terminal_group) and (not template_only_cut_requires_static or static_like_frame))
            or small_template_late_match
        )
        is_match = is_match and template_can_cut
        sticky_candidate = best_region_hint in {"br", "bc", "cr", "right", "bottom"}
        if late_clip_active:
            for template_stem, region_hint, template_group, is_terminal_candidate, template_score, coverage in template_scores_this_frame:
                if template_group != "terminal_templates" or not is_terminal_candidate or region_hint is None:
                    continue
                required_score = template_similarity_threshold
                if coverage <= small_template_max_coverage:
                    required_score = template_similarity_threshold + small_template_extra_similarity
                if template_score >= required_score:
                    terminal_template_hit_counts[template_stem] = terminal_template_hit_counts.get(template_stem, 0) + 1
                    terminal_template_first_hit.setdefault(template_stem, sample_time)
                    terminal_template_coverage[template_stem] = max(
                        terminal_template_coverage.get(template_stem, 0.0),
                        coverage,
                    )
                    # Let repeated late terminal snippets bootstrap the region detector,
                    # even when the larger card contains changing text like player names.
                    region_hit_counts[region_hint] = region_hit_counts.get(region_hint, 0) + 1
                    region_first_match_time.setdefault(region_hint, sample_time)
        if is_match and current_start is None:
            current_start = sample_time
            if pending_flash_time is not None and (sample_time - pending_flash_time) <= flash_follow_window_seconds:
                current_start = pending_flash_time
            current_label = best_label
        elif is_match and current_start is not None:
            current_label = f"{current_label}|{best_label}" if best_label not in current_label.split("|") else current_label
        elif not is_match and current_start is not None:
            matched_ranges.append((current_start, sample_time, current_label))
            current_start = None

        if sticky_region_match_enabled and sticky_candidate and is_match:
            sticky_hits += 1
            sticky_last_match_time = sample_time
            sticky_label = (
                f"{sticky_label}|{best_label}"
                if sticky_start is not None and best_label not in sticky_label.split("|")
                else best_label
            )
            if sticky_start is None and sticky_hits >= sticky_region_min_consecutive_hits:
                sticky_start = max(0.0, sample_time - (sample_interval_seconds * (sticky_region_min_consecutive_hits - 1)))
                if pending_flash_time is not None and (sample_time - pending_flash_time) <= flash_follow_window_seconds:
                    sticky_start = min(sticky_start, pending_flash_time)
                    if flash_terminal_tail_enabled:
                        terminal_cut_start = sticky_start if terminal_cut_start is None else min(terminal_cut_start, sticky_start)
        elif sticky_region_match_enabled and sticky_start is not None:
            if sample_time - sticky_last_match_time > sticky_region_release_seconds:
                matched_ranges.append((sticky_start, sample_time, sticky_label))
                sticky_start = None
                sticky_label = "template_match"
                sticky_hits = 0
        elif sticky_region_match_enabled and not is_match:
            sticky_hits = 0

        if pending_flash_time is not None and (sample_time - pending_flash_time) > flash_follow_window_seconds:
            pending_flash_time = None

        if late_clip_active:
            top_templates = ", ".join(
                f"{stem}:{score:.3f}"
                for stem, _, _, _, score, _ in sorted(
                    template_scores_this_frame,
                    key=lambda item: item[4],
                    reverse=True,
                )[:3]
            )
            top_regions = ", ".join(
                f"{region}:{score:.3f}" for region, score in sorted(region_scores_this_frame.items(), key=lambda item: item[1], reverse=True)[:3]
            )
            debug_notes.append(
                f"late_frame t={sample_time:.2f}s best_template={best_template_stem} score={similarity:.3f} region={best_region_hint} top_templates=[{top_templates}] top_regions=[{top_regions}]"
            )

        last_time = sample_time
        frame_index += 1

    if current_start is not None:
        matched_ranges.append((current_start, last_time + sample_interval_seconds, current_label))
    if sticky_region_match_enabled and sticky_start is not None:
        matched_ranges.append((sticky_start, last_time + sample_interval_seconds, sticky_label))
    if flash_terminal_tail_enabled and terminal_cut_start is not None:
        matched_ranges.append((terminal_cut_start, last_time + sample_interval_seconds, "flash_terminal_tail"))

    confirmed_terminal_templates = {
        stem
        for stem, hit_count in terminal_template_hit_counts.items()
        if hit_count >= terminal_region_min_template_hits
    }
    strong_terminal_templates = {
        stem
        for stem in confirmed_terminal_templates
        if terminal_template_coverage.get(stem, 0.0) >= terminal_large_template_min_coverage
    }
    if confirmed_terminal_templates and (
        len(confirmed_terminal_templates) >= terminal_template_min_unique_matches
        or len(strong_terminal_templates) >= 1
    ):
        earliest_terminal_template_start = min(
            terminal_template_first_hit[stem]
            for stem in confirmed_terminal_templates
            if stem in terminal_template_first_hit
        )
        matched_ranges.append(
            (
                earliest_terminal_template_start,
                last_time + sample_interval_seconds,
                "terminal_template_tail",
            )
        )

    capture.release()

    merged_matches: list[tuple[float, float, str]] = []
    for start, end, label in matched_ranges:
        if not merged_matches:
            merged_matches.append((start, end, label))
            continue

        last_start, last_end, last_label = merged_matches[-1]
        should_merge = start <= last_end + max(sample_interval_seconds * 3.0, 1.5)

        # Keep terminal tail detections isolated so they do not inherit an earlier
        # start time from unrelated generic template matches.
        if should_merge and (
            is_terminal_label(label) != is_terminal_label(last_label)
            or (is_terminal_label(label) and label != last_label)
        ):
            should_merge = False

        if should_merge:
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
            frame_index = 0
            pending_flash_time = None

            while True:
                ok, frame = capture.read()
                if not ok or frame is None:
                    break
                if frame_index % sample_frame_stride != 0:
                    frame_index += 1
                    continue

                sample_time = frame_index / source_fps

                frame_small, frame_edges = preprocess_frame(frame)
                edge_density = float((frame_edges > 0).mean())

                horizontal_projection = (frame_edges > 0).mean(axis=1)
                text_like_rows = float((horizontal_projection > 0.10).mean())

                if previous_small is None:
                    motion_value = 0.0
                    changed_pixel_ratio = 0.0
                    brightness_delta = 0.0
                else:
                    diff = cv2.absdiff(frame_small, previous_small)
                    motion_value = float(diff.mean())
                    brightness_delta = motion_value
                    changed_pixel_ratio = float((diff > 12).mean())
                    bright_pixel_ratio = float((frame_small > 205).mean())
                    if (
                        flash_transition_enabled
                        and brightness_delta >= flash_brightness_delta_threshold
                        and changed_pixel_ratio >= flash_changed_pixel_ratio_threshold
                        and bright_pixel_ratio >= flash_bright_pixel_ratio_threshold
                    ):
                        pending_flash_time = sample_time

                is_static_menu = (
                    motion_value <= static_motion_threshold
                    and changed_pixel_ratio <= 0.18
                    and edge_density >= static_edge_density_threshold
                    and text_like_rows >= static_text_like_threshold
                )

                if is_static_menu and current_start is None:
                    current_start = sample_time
                    if pending_flash_time is not None and (sample_time - pending_flash_time) <= flash_follow_window_seconds:
                        current_start = pending_flash_time
                elif not is_static_menu and current_start is not None:
                    static_matches.append((current_start, sample_time, "static_text_screen"))
                    current_start = None

                if pending_flash_time is not None and (sample_time - pending_flash_time) > flash_follow_window_seconds:
                    pending_flash_time = None

                previous_small = frame_small
                last_time = sample_time
                frame_index += 1

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

    confirmed_terminal_regions = {
        region
        for region, hit_count in region_hit_counts.items()
        if hit_count >= terminal_region_min_template_hits
    }

    if terminal_region_detector_enabled and confirmed_terminal_regions:
        capture = cv2.VideoCapture(str(file_path))
        if capture.isOpened():
            region_matches: list[tuple[float, float, str]] = []
            region_start_times: dict[str, float | None] = {
                region: None for region in confirmed_terminal_regions
            }
            start_frame_index = max(0, int((clip_duration_seconds * terminal_region_start_fraction) * source_fps))
            capture.set(cv2.CAP_PROP_POS_FRAMES, start_frame_index)
            frame_index = start_frame_index
            last_time = frame_index / source_fps

            while True:
                ok, frame = capture.read()
                if not ok or frame is None:
                    break
                if frame_index % sample_frame_stride != 0:
                    frame_index += 1
                    continue

                sample_time = frame_index / source_fps

                frame_small, frame_edges = preprocess_frame(frame)
                for region in confirmed_terminal_regions:
                    search_gray, search_edges = resolve_region(frame_small, frame_edges, region)
                    edge_density = float((search_edges > 0).mean())
                    horizontal_projection = (search_edges > 0).mean(axis=1)
                    text_like_rows = float((horizontal_projection > 0.10).mean())

                    is_terminal_region = (
                        edge_density >= terminal_region_edge_density_threshold
                        and text_like_rows >= terminal_region_text_like_threshold
                    )

                    if is_terminal_region and region_start_times[region] is None:
                        region_start_times[region] = sample_time
                    elif not is_terminal_region and region_start_times[region] is not None:
                        region_matches.append((region_start_times[region], sample_time, f"terminal_region_{region}"))
                        region_start_times[region] = None

                last_time = sample_time
                frame_index += 1

            for region, start_time in region_start_times.items():
                if start_time is not None:
                    region_matches.append((start_time, last_time + sample_interval_seconds, f"terminal_region_{region}"))

            capture.release()

            for start, end, label in region_matches:
                duration = round(end - start, 3)
                if duration < terminal_region_min_duration_seconds:
                    continue
                segments.append(
                    DetectedSegment(
                        start=round(start, 3),
                        end=round(end, 3),
                        duration=duration,
                        label=label,
                    )
                )

        earliest_terminal_start = min(
            region_first_match_time[region]
            for region in confirmed_terminal_regions
            if region in region_first_match_time
        )
        segments.append(
            DetectedSegment(
                start=round(earliest_terminal_start, 3),
                end=round(clip_duration_seconds, 3),
                duration=round(clip_duration_seconds - earliest_terminal_start, 3),
                label="terminal_region_tail",
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

    if confirmed_terminal_regions:
        debug_notes.append(
            "Confirmed terminal regions: " + ", ".join(sorted(confirmed_terminal_regions))
        )
    else:
        debug_notes.append("Confirmed terminal regions: none")
    if confirmed_terminal_templates:
        debug_notes.append(
            "Confirmed terminal templates: " + ", ".join(sorted(confirmed_terminal_templates))
        )
    else:
        debug_notes.append("Confirmed terminal templates: none")

    return merged_segments, debug_notes


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
    segmentation_mode: str,
    active_fight_weight: float,
    cut_weight: float,
    terminal_cut_weight: float,
) -> list[KeepSegment]:
    if clip.duration_seconds is None or clip.duration_seconds <= 0:
        return []

    effective_clip_end = max(0.0, clip.duration_seconds - max(0.0, overlap_trim_seconds))
    if effective_clip_end <= 0:
        return []

    if segmentation_mode == "fight_only":
        keep_segments: list[KeepSegment] = []
        merged_active_ranges = merge_ranges(
            [
                (max(0.0, segment.start), min(effective_clip_end, segment.end))
                for segment in clip.active_fight_segments
            ],
            gap_seconds=merge_gap_seconds,
        )
        for keep_start, keep_end in merged_active_ranges:
            duration = round(keep_end - keep_start, 3)
            if duration < minimum_keep_segment_seconds:
                continue
            keep_segments.append(
                KeepSegment(
                    start=round(keep_start, 3),
                    end=round(keep_end, 3),
                    duration=duration,
                    reason="active fight template visibility",
                )
            )
        return keep_segments

    blocked_ranges = [(segment.start, segment.end) for segment in clip.black_segments]
    if segmentation_mode == "cut_only":
        active_fight_ranges: list[tuple[float, float]] = []
    else:
        active_fight_ranges = merge_ranges(
            [(segment.start, segment.end) for segment in clip.active_fight_segments],
            gap_seconds=merge_gap_seconds,
        )

    for segment in clip.cut_segments:
        blocked_start = segment.start
        blocked_end = segment.end
        segment_cut_weight = terminal_cut_weight if (
            segment.label.startswith("terminal_")
            or "terminal_" in segment.label
            or segment.label in {"flash_terminal_tail", "terminal_template_tail", "terminal_region_tail"}
        ) else cut_weight
        if clip.scene_segments and blocked_end >= max(0.0, effective_clip_end - 0.5):
            tail_scene = clip.scene_segments[-1]
            forced_tail_start = max(blocked_start, tail_scene.start)
            tail_has_active_protection = False
            if segmentation_mode == "hybrid" and active_fight_ranges:
                tail_has_active_protection = any(
                    active_end > forced_tail_start and active_start < blocked_end
                    for active_start, active_end in active_fight_ranges
                )
            if not tail_has_active_protection and blocked_end > forced_tail_start:
                blocked_ranges.append((forced_tail_start, blocked_end))
                continue
        if segment.label == "static_text_screen":
            trimmed_blocked_ranges = [(blocked_start, blocked_end)]
        elif segmentation_mode == "hybrid" and active_fight_ranges and active_fight_weight >= segment_cut_weight:
            trimmed_blocked_ranges = subtract_ranges((blocked_start, blocked_end), active_fight_ranges)
        else:
            trimmed_blocked_ranges = [(blocked_start, blocked_end)]

        for trimmed_start, trimmed_end in trimmed_blocked_ranges:
            adjusted_start = trimmed_start
            adjusted_end = trimmed_end
            if segment.label.startswith("terminal_") and clip.scene_segments:
                final_scene = clip.scene_segments[-1]
                if adjusted_end >= max(0.0, effective_clip_end - 0.5):
                    adjusted_start = max(adjusted_start, final_scene.start)
            if adjusted_end > adjusted_start:
                blocked_ranges.append((adjusted_start, adjusted_end))

    visible_ranges = subtract_ranges((0.0, effective_clip_end), blocked_ranges)
    merged_visible_ranges = list(visible_ranges)
    if segmentation_mode == "hybrid" and active_fight_ranges and len(merged_visible_ranges) > 1:
        late_bridge_gap_seconds = max(6.0, merge_gap_seconds * 2.0)
        late_bridge_start = effective_clip_end * 0.75
        bridged_visible_ranges: list[tuple[float, float]] = [merged_visible_ranges[0]]
        for next_start, next_end in merged_visible_ranges[1:]:
            last_start, last_end = bridged_visible_ranges[-1]
            gap_seconds = next_start - last_end
            next_has_active_fight = any(
                active_end > next_start and active_start < next_end
                for active_start, active_end in active_fight_ranges
            )
            if last_end >= late_bridge_start and gap_seconds <= late_bridge_gap_seconds and next_has_active_fight:
                bridged_visible_ranges[-1] = (last_start, next_end)
            else:
                bridged_visible_ranges.append((next_start, next_end))
        merged_visible_ranges = bridged_visible_ranges
    if segmentation_mode == "hybrid" and clip.scene_segments:
        final_scene = clip.scene_segments[-1]
        final_scene_start = final_scene.start
        has_terminal_tail_cut = any(segment.end >= max(0.0, effective_clip_end - 0.5) for segment in clip.cut_segments)
        if has_terminal_tail_cut:
            capped_visible_ranges: list[tuple[float, float]] = []
            final_scene_tail_allowance = min(3.0, max(0.0, final_scene.duration * 0.5))
            final_scene_cap_end = min(effective_clip_end, final_scene_start + final_scene_tail_allowance)
            for visible_start, visible_end in merged_visible_ranges:
                adjusted_end = visible_end
                if visible_start < final_scene_start < visible_end:
                    adjusted_end = min(visible_end, final_scene_cap_end)
                if adjusted_end > visible_start:
                    capped_visible_ranges.append((visible_start, adjusted_end))
            merged_visible_ranges = capped_visible_ranges

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
    segmentation_mode: str,
    active_fight_weight: float,
    cut_weight: float,
    terminal_cut_weight: float,
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
            segmentation_mode=segmentation_mode,
            active_fight_weight=active_fight_weight,
            cut_weight=cut_weight,
            terminal_cut_weight=terminal_cut_weight,
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

    fullscreen_templates_dir = resolve_from_app_root(
        app_config.analysis.visual_cut_detection.fullscreen_templates_dir
    ).resolve()
    partial_templates_dir = resolve_from_app_root(
        app_config.analysis.visual_cut_detection.partial_templates_dir
    ).resolve()
    terminal_templates_dir = resolve_from_app_root(
        app_config.analysis.visual_cut_detection.terminal_templates_dir
    ).resolve()
    active_fight_templates_dir = resolve_from_app_root(
        app_config.analysis.active_fight_detection.templates_dir
    ).resolve()
    template_dirs: list[Path] = [
        fullscreen_templates_dir,
        partial_templates_dir,
        terminal_templates_dir,
    ]

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
                    segmentation_mode=app_config.analysis.segmentation_mode,
                    active_fight_weight=app_config.analysis.active_fight_detection.protection_weight,
                    cut_weight=app_config.analysis.visual_cut_detection.cut_weight,
                    terminal_cut_weight=app_config.analysis.visual_cut_detection.terminal_cut_weight,
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

        if app_config.analysis.active_fight_detection.enabled:
            logging.info("Running active fight detection for %s", file_path.name)
            try:
                clip.active_fight_segments, active_debug_notes = detect_active_fight_segments(
                    file_path=file_path,
                    templates_dir=active_fight_templates_dir,
                    sample_interval_seconds=app_config.analysis.active_fight_detection.sample_interval_seconds,
                    similarity_threshold=app_config.analysis.active_fight_detection.similarity_threshold,
                    min_match_duration_seconds=app_config.analysis.active_fight_detection.min_match_duration_seconds,
                    leading_keep_seconds=app_config.analysis.active_fight_detection.leading_keep_seconds,
                    trailing_keep_seconds=app_config.analysis.active_fight_detection.trailing_keep_seconds,
                    min_consecutive_hits=app_config.analysis.active_fight_detection.min_consecutive_hits,
                    release_after_misses=app_config.analysis.active_fight_detection.release_after_misses,
                    require_dynamic_frame=app_config.analysis.active_fight_detection.require_dynamic_frame,
                    max_static_changed_pixel_ratio=app_config.analysis.active_fight_detection.max_static_changed_pixel_ratio,
                )
                clip.debug_notes.extend(active_debug_notes)
            except Exception as exc:
                logging.exception("Active fight detection failed for %s", file_path.name)
                clip.warnings.append(f"Active fight detection failed: {exc}")

        if app_config.analysis.visual_cut_detection.enabled:
            logging.info("Running visual cut detection for %s", file_path.name)
            try:
                clip.cut_segments, visual_debug_notes = detect_visual_cut_segments(
                    file_path=file_path,
                    templates_dirs=template_dirs,
                    sample_interval_seconds=app_config.analysis.visual_cut_detection.sample_interval_seconds,
                    template_similarity_threshold=app_config.analysis.visual_cut_detection.template_similarity_threshold,
                    min_template_match_duration_seconds=app_config.analysis.visual_cut_detection.min_template_match_duration_seconds,
                    template_only_cut_requires_static=app_config.analysis.visual_cut_detection.template_only_cut_requires_static,
                    unscoped_template_enabled=app_config.analysis.visual_cut_detection.unscoped_template_enabled,
                    small_template_late_match_enabled=app_config.analysis.visual_cut_detection.small_template_late_match_enabled,
                    small_template_max_coverage=app_config.analysis.visual_cut_detection.small_template_max_coverage,
                    small_template_extra_similarity=app_config.analysis.visual_cut_detection.small_template_extra_similarity,
                    sticky_region_match_enabled=app_config.analysis.visual_cut_detection.sticky_region_match_enabled,
                    sticky_region_min_consecutive_hits=app_config.analysis.visual_cut_detection.sticky_region_min_consecutive_hits,
                    sticky_region_release_seconds=app_config.analysis.visual_cut_detection.sticky_region_release_seconds,
                    flash_transition_enabled=app_config.analysis.visual_cut_detection.flash_transition_enabled,
                    flash_brightness_delta_threshold=app_config.analysis.visual_cut_detection.flash_brightness_delta_threshold,
                    flash_changed_pixel_ratio_threshold=app_config.analysis.visual_cut_detection.flash_changed_pixel_ratio_threshold,
                    flash_bright_pixel_ratio_threshold=app_config.analysis.visual_cut_detection.flash_bright_pixel_ratio_threshold,
                    flash_follow_window_seconds=app_config.analysis.visual_cut_detection.flash_follow_window_seconds,
                    flash_terminal_tail_enabled=app_config.analysis.visual_cut_detection.flash_terminal_tail_enabled,
                    terminal_region_detector_enabled=app_config.analysis.visual_cut_detection.terminal_region_detector_enabled,
                    terminal_region_start_fraction=app_config.analysis.visual_cut_detection.terminal_region_start_fraction,
                    terminal_region_min_template_hits=app_config.analysis.visual_cut_detection.terminal_region_min_template_hits,
                    terminal_template_min_unique_matches=app_config.analysis.visual_cut_detection.terminal_template_min_unique_matches,
                    terminal_large_template_min_coverage=app_config.analysis.visual_cut_detection.terminal_large_template_min_coverage,
                    terminal_region_edge_density_threshold=app_config.analysis.visual_cut_detection.terminal_region_edge_density_threshold,
                    terminal_region_text_like_threshold=app_config.analysis.visual_cut_detection.terminal_region_text_like_threshold,
                    terminal_region_min_duration_seconds=app_config.analysis.visual_cut_detection.terminal_region_min_duration_seconds,
                    static_screen_enabled=app_config.analysis.visual_cut_detection.static_screen_enabled,
                    static_motion_threshold=app_config.analysis.visual_cut_detection.static_motion_threshold,
                    static_edge_density_threshold=app_config.analysis.visual_cut_detection.static_edge_density_threshold,
                    static_text_like_threshold=app_config.analysis.visual_cut_detection.static_text_like_threshold,
                    min_static_duration_seconds=app_config.analysis.visual_cut_detection.min_static_duration_seconds,
                )
                clip.debug_notes.extend(visual_debug_notes)
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
                segmentation_mode=app_config.analysis.segmentation_mode,
                active_fight_weight=app_config.analysis.active_fight_detection.protection_weight,
                cut_weight=app_config.analysis.visual_cut_detection.cut_weight,
                terminal_cut_weight=app_config.analysis.visual_cut_detection.terminal_cut_weight,
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
        segmentation_mode=app_config.analysis.segmentation_mode,
        active_fight_weight=app_config.analysis.active_fight_detection.protection_weight,
        cut_weight=app_config.analysis.visual_cut_detection.cut_weight,
        terminal_cut_weight=app_config.analysis.visual_cut_detection.terminal_cut_weight,
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
