# Gameplay Highlight Pipeline

Windows-first, local-first tooling for turning raw gameplay recordings into review-ready fight segments and optional highlight exports.

## Status

This project is currently **alpha**. It is intended for real local use, but the detection and export logic is still heuristic and should be validated on your footage before relying on it for production workflows.

## What It Does

- Scans an input folder recursively for supported video files
- Extracts clip metadata with `ffprobe`
- Sorts clips by estimated recording start time
- Flags likely overlap windows using estimated start/end timestamps
- Runs `ffmpeg` `blackdetect` to find likely black or dead-space segments
- Runs PySceneDetect content analysis to split clips into scene ranges
- Optionally matches reference cut templates from `presets/cut_templates/`
- Optionally blocks static, text-heavy menu-style screens
- Reuses cached analysis for unchanged clips by default
- Generates longer candidate keep segments by removing blocked ranges and merging nearby gameplay spans
- Optionally exports each candidate keep segment as its own fight clip
- Optionally exports one combined highlight video from the fight clips
- Writes JSON, CSV, and Markdown review outputs
- Logs to console and file
- Keeps processing non-destructive

## What It Does Not Do Yet

- reliably classify all menus, matchmaking screens, or loading screens
- validate overlap with frame or audio similarity
- generate DaVinci Resolve timelines, XML, or EDL
- produce vertical deliverables
- replace human review for pacing or final editorial judgment

## Design Goals

- Config-driven thresholds and paths
- Modular source layout for future smarter overlap logic and review exports
- Windows PowerShell helper scripts for environment setup and common execution

## Recommended Next Steps

1. Improve overlap confidence with frame or audio fingerprints.
2. Add static-screen and menu/loading heuristics beyond blackdetect.
3. Export Resolve-friendly sidecar data after keep-segment quality is validated.
4. Add tests around config loading, scene/overlap heuristics, and report generation.

## Potential Features

Potential future additions, kept separate from the implemented feature set:

1. Lower-filesize export options for fight clips and combined videos, including presets for smaller upload-friendly output.
2. Named sensitivity presets such as conservative, balanced, and aggressive.
3. Resolve XML/EDL or timeline sidecar export.
4. Optional OCR-assisted UI/text detection.
5. Audio or frame-similarity overlap confirmation.
6. Lightweight GUI launcher for non-technical users.

Deployment and rollout guidance is documented in [docs/deployment_readme.md](docs/deployment_readme.md).
Public-release checks are documented in [docs/release_checklist.md](docs/release_checklist.md).
Packaging notes are documented in [docs/packaging.md](docs/packaging.md).

## Project Structure

```text
project-root/
  README.md
  requirements.txt
  config/
  scripts/
  src/
  input/
  intermediate/
  review/
  output/
  logs/
  presets/
  docs/
```

## Requirements

- Windows
- Python 3.11+ recommended
- `ffmpeg` and `ffprobe` available on `PATH`, or pass explicit paths on the command line
- Python dependencies from `requirements.txt`: `scenedetect`, `opencv-python`

## Quick Start

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m src.main --input input --output output --review review --logs logs
```

## Windows Setup

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Or use:

```powershell
.\scripts\setup_env.ps1
```

## Confirm FFmpeg Tools

```powershell
ffmpeg -version
ffprobe -version
```

If those commands fail, install FFmpeg locally and either add it to `PATH` or pass `--ffmpeg` and `--ffprobe`.

## Configuration

Defaults live in [config/defaults.json](config/defaults.json). You can override them with `--config` and then override individual values again with CLI flags.

Key current tuning knobs:

- `analysis.blackdetect.*`
- `analysis.scene_detection.threshold`
- `analysis.scene_detection.min_scene_length_seconds`
- `analysis.minimum_keep_segment_seconds`
- `analysis.merge_gap_seconds`
- `analysis.visual_cut_detection.*`
- `export.export_fight_clips`
- `export.export_combined_video`
- `export.transition_mode`
- `export.transition_duration_seconds`

## Tuning Guide

These visual-cut settings control how aggressively the tool removes non-fight footage such as loading screens, menus, queue screens, scoreboards, and other static UI-heavy screens.

### `--template-similarity-threshold`

What it does:

- Controls how closely a video frame must match one of your reference images in `presets/cut_templates/` before that span is marked for removal.

How to think about it:

- Higher value = stricter matching
- Lower value = more aggressive matching

Typical behavior:

- around `0.90`: only very close matches
- around `0.85`: good general-purpose default
- around `0.72` to `0.80`: more aggressive, useful if partial UI templates are being missed

Use this when:

- the tool is missing obvious loading/menu screens that look similar to your templates

Risk if too low:

- it may start cutting gameplay moments that coincidentally resemble your templates

### `--static-motion-threshold`

What it does:

- Controls how little the image must change between sampled frames before the tool considers the screen "static."

How to think about it:

- Lower value = stricter static detection
- Higher value = more screens treated as static

Use this when:

- menu or scoreboard screens are surviving because they are mostly still
- or gameplay is being falsely cut because the threshold is too high

Rule of thumb:

- lower it if real gameplay is being cut
- raise it if static non-fight screens are not being removed

### `--static-edge-threshold`

What it does:

- Measures how visually "UI/text dense" the frame is using edges and line structure.

How to think about it:

- Higher value = requires more visible UI/text structure before cutting
- Lower value = more willing to treat structured screens as menus/non-fight

Use this when:

- text-heavy menus are slipping through
- or detailed gameplay HUD moments are being mistaken for menu screens

### `--static-text-threshold`

What it does:

- Estimates how text-like the screen is by looking for dense horizontal rows of edge activity.

How to think about it:

- Higher value = requires more obvious text-like structure
- Lower value = more aggressive at cutting text-heavy screens

Use this when:

- queue, results, scoreboard, or menu screens with lots of text are surviving

Risk if too low:

- some gameplay overlays or HUD-heavy moments could be incorrectly treated as non-fight

### `--min-static-duration`

What it does:

- The minimum number of seconds a static/text-heavy screen must persist before it is cut.

How to think about it:

- Lower value = cuts short static/menu moments faster
- Higher value = only cuts longer non-fight spans

Use this when:

- short menu flashes should be removed
- or brief in-game pauses are being cut too aggressively

Typical behavior:

- around `2.0` to `3.0` seconds is a good working range

### Flash Transition Detection

The tool can also watch for sudden, large scene flashes or abrupt full-screen transitions that often happen right before a win/lose, results, or post-match screen.

Relevant knobs:

- `--flash-brightness-threshold`
- `--flash-change-threshold`
- `--flash-follow-window`

How it works:

- if the screen changes very sharply
- and a result/menu-style state appears shortly after
- the blocked segment can start from the flash instead of only when the UI becomes obvious

This is useful for:

- win/lose transitions
- result-card reveals
- sudden end-of-match flashes

Default behavior also supports a flash-to-tail handoff:

- if a strong flash is followed by a convincing anchored end-state signal
- the blocked segment can continue from that flash through the rest of the post-match tail

### Late-Clip Terminal Region Detection

The tool can also look for text/UI-heavy anchored regions late in a clip, especially when you have region-hinted templates such as `br_...` or `bc_...`.

This helps when:

- the result UI appears in a stable region
- but the rest of the screen is still animated
- and exact per-frame template matching is too fragile

## Practical Tuning Advice

Start with defaults first.

If too much non-fight footage remains:

- lower `--template-similarity-threshold`
- lower `analysis.visual_cut_detection.sample_interval_seconds` to sample frames more often
- raise `--static-motion-threshold`
- lower `--static-edge-threshold`
- lower `--static-text-threshold`
- lower `--min-static-duration`

If it cuts too much real gameplay:

- raise `--template-similarity-threshold`
- lower `--static-motion-threshold`
- raise `--static-edge-threshold`
- raise `--static-text-threshold`
- raise `--min-static-duration`

Recommended workflow:

1. Run with defaults.
2. Review `review/review_report.md`.
3. Add or improve reference images in `presets/cut_templates/`.
4. Change one or two thresholds at a time.
5. Re-run with cache reuse on unless you need a full refresh.

## Cut Templates

If you want the tool to learn what should be cut, place representative screenshots in:

```text
presets/cut_templates/
```

Backward compatibility:

- `presets/cut_templates/` is the preferred folder
- `presets/loading_templates/` is still scanned for older template sets

Supported image types:

- `.png`
- `.jpg`
- `.jpeg`

The tool will sample frames from each clip and mark spans that closely match those templates as blocked/non-fight time.
It will also cut static, text-heavy menu-like spans using configurable heuristics.

Full-screen screenshots and smaller UI-element screenshots are both supported. Partial templates are matched as on-screen indicators, not only as full-frame replacements.
Transparent PNG templates are also supported, so you can mask out changing areas like player names while keeping stable UI elements.
You can optionally scope a template to a likely screen region by naming it with a prefix such as:

- `br__results_card.png` for bottom-right
- `br_results_card.png` for bottom-right
- `tr__queue_badge.png` for top-right
- `tr_queue_badge.png` for top-right
- `bl__menu_prompt.png` for bottom-left
- `center__loading_banner.png` for center

Supported region prefixes:

- `tl`
- `tr`
- `bl`
- `br`
- `tc`
- `bc`
- `cl`
- `cr`
- `top`
- `bottom`
- `left`
- `right`
- `center`

Accepted filename formats:

- `<prefix>__<name>.png`
- `<prefix>_<name>.png`

Examples:

- `br_17.png`
- `br__victory_panel.png`
- `tr_queue_status.png`
- `tc_loading_banner.png`
- `bc_results_prompt.png`
- `cl_sidebar_notice.png`
- `cr_status_panel.png`

The prefix tells the matcher to focus on that region of the frame instead of searching the full screen.

Defaults are intentionally tuned to be fairly aggressive for gameplay footage with repeated loading, queue, and results screens. If too much non-fight footage survives, the first setting to adjust is usually `--template-similarity-threshold`.

## Usage

Standard command:

```powershell
python -m src.main --input input --output output --review review
```

Export one clip per fight:

```powershell
python -m src.main --input input --output output --review review --logs logs --export-fights
```

Export fight clips plus one combined highlight reel:

```powershell
python -m src.main --input input --output output --review review --logs logs --export-combined
```

Force a full reprocess instead of reusing cached analysis:

```powershell
python -m src.main --input input --output output --review review --logs logs --reprocess-mode all
```

Write partial reports after each clip completes analysis:

```powershell
python -m src.main --input input --output output --review review --logs logs --clip-at-a-time
```

With exports enabled, `--clip-at-a-time` also writes provisional per-clip exports under:

```text
output/_in_progress/
```

Those are early review artifacts. The final end-of-run outputs are still written to the normal output locations and should converge to the same result as standard batch mode.

Use a custom cut-template folder:

```powershell
python -m src.main --input input --output output --review review --logs logs --cut-templates presets\cut_templates
```

Disable heavier analysis passes if needed:

```powershell
python -m src.main --input input --output output --review review --skip-blackdetect --skip-scenedetect
```

Windows helper script:

```powershell
.\scripts\run_analysis.ps1
```

With explicit FFmpeg paths:

```powershell
python -m src.main `
  --input input `
  --output output `
  --review review `
  --ffmpeg "C:\ffmpeg\bin\ffmpeg.exe" `
  --ffprobe "C:\ffmpeg\bin\ffprobe.exe"
```

Compatibility wrapper:

```powershell
python .\gameplay_pipeline_v1.py --input input --output output --review review
```

## Repository Hygiene

- Local media in `input/` is ignored by `.gitignore`.
- Generated files in `output/`, `review/`, `logs/`, and `intermediate/` are ignored by `.gitignore`.
- The virtual environment is ignored by `.gitignore`.
- Before publishing the repo, review [docs/release_checklist.md](docs/release_checklist.md).

This repository is intended to store code and documentation, not raw gameplay media or generated runtime artifacts.

## Packaging

Project metadata for a public repository lives in [pyproject.toml](pyproject.toml).

The project is also being prepared for future portable Windows packaging:

- runtime paths resolve relative to the application root
- local `ffmpeg.exe` / `ffprobe.exe` beside the app are auto-detected
- PyInstaller scaffolding exists in [packaging/gameplay_pipeline.spec](packaging/gameplay_pipeline.spec)
- a build helper exists in [scripts/build_exe.ps1](scripts/build_exe.ps1)

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE).

## Support

This project is provided open source, as-is, with no guarantee of support, maintenance, updates, or responsiveness.

You may use, modify, and distribute it under the terms of the license, but you should assume:

- no formal support
- no service-level commitment
- no guarantee of future fixes or feature work
- no warranty beyond the MIT license terms

## Outputs

- `output\clip_report.json`
- `output\clip_summary.csv`
- `review\review_report.md`
- `logs\gameplay_pipeline.log`

The reports now include:

- likely overlap windows
- black/dead-space candidates
- scene segments
- visual cut matches
- candidate keep segments
- exported fight clip inventory
- combined video output metadata

Media exports, when enabled, are written to:

- `output\fights\`
- `output\combined_highlights.mp4`

## Notes On Non-Destructive Behavior

- Original clips are never modified or deleted.
- The pipeline only analyzes source files and writes sidecar reports and logs.
- Candidate keep segments are suggestions for review and export, not direct edits to the source files.
- Unchanged files are reused from cache by default; use `--reprocess-mode all` to force fresh analysis.
- Static, text-heavy screen cutting is heuristic and should be tuned against your actual game UI.

## Troubleshooting

### `ffprobe` or `ffmpeg` not found

```powershell
python -m src.main --input input --output output --review review --ffmpeg "C:\path\to\ffmpeg.exe" --ffprobe "C:\path\to\ffprobe.exe"
```

### No clips found

Confirm files are in `input\` and use a supported extension.

### Metadata warnings

Some gameplay files omit embedded creation timestamps. In that case v1 falls back to modified time and duration estimates, which lowers overlap confidence.
