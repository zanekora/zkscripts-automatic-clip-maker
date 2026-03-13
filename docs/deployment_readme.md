# Gameplay Pipeline V1.2 Deployment Guide

This guide covers the next practical steps to get the workflow running on a Windows machine and use it repeatedly as a local-first gameplay ingest and review tool.

## Purpose

The current workflow is a non-destructive analysis and export pipeline. It does not trim, rewrite, or delete the original clips. It scans raw gameplay files, extracts metadata, flags likely overlaps, detects black/dead-space candidates, detects scene boundaries, optionally matches reference cut templates, applies static/text-heavy menu heuristics, and generates candidate keep segments for manual editing follow-up or optional exports.

This tool was built primarily for the author's own use. Others are welcome to use or adapt it, but there is no formal support commitment.

If you publish modified versions or reuse substantial parts publicly, source credit is appreciated, although the license allows broad reuse.

The defaults are currently tuned on the aggressive side for gameplay footage where loading, queue, and results screens should be removed quickly.

It can now also optionally create new exported media files:

- one clip per detected fight segment
- one combined highlight reel assembled from those fight clips

## Current State

Implemented now:

- folder-based ingest
- `ffprobe` metadata extraction
- timestamp-based overlap estimation
- `ffmpeg blackdetect` parsing
- PySceneDetect scene boundary detection
- reference cut-template matching
- static/text-heavy menu-screen detection
- cached analysis reuse for unchanged clips
- candidate keep-segment generation
- optional per-fight clip export
- optional combined highlight export
- support for multiple detected fight segments within a single source clip
- selectable segmentation modes: hybrid, cut_only, fight_only
- fight_only mode now preserves the active-fight template ranges directly instead of expanding back to the whole scene
- active-fight detection threshold and keep-window controls for fight_only workflows
- hybrid mode now lets active-fight ranges protect gameplay from overlapping cut spans
- active-fight detection now uses consecutive-hit confirmation and optional dynamic-frame gating
- JSON, CSV, Markdown, and log outputs
- Windows PowerShell helper scripts

Not implemented yet:

- menu/loading-screen detection beyond dark-frame detection
- automatic trimming
- Resolve timeline import/export generation
- smart overlap confirmation using frames or audio

## Recommended Next Steps

### 1. Validate the local environment

Confirm these are available:

- Python 3.11+
- `ffmpeg`
- `ffprobe`

Run:

```powershell
python --version
ffmpeg -version
ffprobe -version
```

If `ffmpeg` or `ffprobe` are missing, install a local FFmpeg build and either:

- add the FFmpeg `bin` folder to `PATH`, or
- pass explicit executable paths to the CLI

### 2. Create and activate the virtual environment

From the project root:

```powershell
cd "C:\path\to\gameplay-highlight-pipeline"
.\scripts\setup_env.ps1
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks script execution for your user account:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

### 3. Put test footage into `input\`

Copy a few representative gameplay clips into:

```text
input\
```

Use real samples that reflect your normal recording pattern:

- same session split across multiple files
- clips with probable overlap
- clips containing loading or dead-space moments

If you have representative screenshots of screens that should be cut, sort them into:

```text
presets\fullscreen_templates\
presets\partial_templates\
presets\terminal_templates\
presets\active_fight_templates\
```

Recommended use:

- `fullscreen_templates`
  whole screens such as loading, matchmaking, queue, menu, or scoreboard states
- `partial_templates`
  cropped UI fragments or icons that indicate a non-fight state
- `terminal_templates`
  strong end-of-match signals such as result cards, victory/defeat banners, continue prompts, or post-match summary panels
- `active_fight_templates`
  positive in-match signals such as round timers or fight HUD elements that should help preserve gameplay while they are visible

For small in-fight UI snippets such as timers, use region-prefixed or masked images where possible. The active-fight matcher now benefits from the same region-aware and masked matching concepts as the cut detector.

If you have templates that specifically mean "the match is over" or "we are now on the result screen", put those in:

```text
presets\terminal_templates\
```

Those templates are treated as stronger late end-state indicators than general cut templates.
Late terminal tail cuts are intentionally conservative and prefer either multiple distinct terminal-template confirmations or one larger, stronger terminal template.
In practice, larger result-card templates are more reliable than very small snippets on their own.

You can mix:

- full-screen screenshots
- smaller UI-element screenshots that indicate a non-fight state
- full-screen menu, loading, queue, or scoreboard screens

For dynamic screens where only part of the UI is stable, use:

- a cropped template of the stable UI element
- or a transparent PNG that masks out changing text or character animation

You can also hint the expected screen region in the filename:

- `br__...` or `br_...` bottom-right
- `tr__...` or `tr_...` top-right
- `bl__...` or `bl_...` bottom-left
- `tl__...` or `tl_...` top-left
- `tc__...` or `tc_...` top-center
- `bc__...` or `bc_...` bottom-center
- `cl__...` or `cl_...` center-left
- `cr__...` or `cr_...` center-right
- `center__...` or `center_...` center

Example valid names:

- `br_17.png`
- `br__victory_panel.png`
- `tr_queue_badge.png`
- `tc_loading_banner.png`
- `bc_results_prompt.png`

If template matching still misses too much, the first useful adjustments are usually:

- lower `--template-similarity-threshold`
- lower the sample interval in config so frames are checked more often
- add a few more screenshots of the exact non-fight states that survived

By default, generic template matches are kept conservative and are expected to work together with static/text-heavy or anchored-region signals, rather than cutting purely on visual similarity alone.
Smaller templates can still help late-clip end-state detection when they match strongly enough near the end of a clip.
Region-hinted templates are preferred. Unscoped templates are intentionally conservative because they are more likely to create false positives during live gameplay.

### 4. Run the first analysis

Basic run:

```powershell
python -m src.main --input input --output output --review review --logs logs
```

Export per-fight clips:

```powershell
python -m src.main --input input --output output --review review --logs logs --export-fights
```

Export per-fight clips plus one combined highlight reel:

```powershell
python -m src.main --input input --output output --review review --logs logs --export-combined
```

Example of a more aggressive visual-cut run:

```powershell
python -m src.main `
  --input input `
  --output output `
  --review review `
  --logs logs `
  --export-combined `
  --template-similarity-threshold 0.82 `
  --static-motion-threshold 2.5 `
  --static-edge-threshold 0.08 `
  --static-text-threshold 0.02 `
  --min-static-duration 2.5
```

What those mean:

- `--template-similarity-threshold 0.82`
  makes reference-image matching more aggressive
- `--static-motion-threshold 2.5`
  treats low-motion screens as static more easily
- `--static-edge-threshold 0.08`
  makes UI/text-structured screens easier to cut
- `--static-text-threshold 0.02`
  makes text-heavy screens easier to cut
- `--min-static-duration 2.5`
  cuts static/text-heavy spans once they persist for at least 2.5 seconds

The visual-cut system can also detect sudden flash transitions leading into result or menu screens. If your game uses a sharp flash before the end screen appears, this can help the tool cut from the transition itself rather than from the first stable UI frame.

Flash detection is intended to behave like a true transition detector, not just a "big effect happened" detector. It now also checks how much of the frame became bright, which helps reject many flashy combat skills.

When the follow-up UI signal is strong enough, the default behavior can also hold that cut through the rest of the post-match tail instead of letting the winner animation slip back into the export.

The visual-cut system can also use late-clip anchored region heuristics, which are especially useful when a bottom-right or bottom-center result panel appears during an animated win/lose sequence.

Those anchored-region heuristics are intentionally gated by repeated template confirmation so that unrelated region hints in other templates do not over-block the clip.
If the end screen is being cut too early, make terminal detection more conservative by:

- raising `--terminal-region-start-fraction`
- raising `--terminal-region-min-template-hits`

If a late anchored result UI is confirmed strongly enough, the detector can also block from that late confirmation point through the end of the clip.
To reduce premature trimming, terminal tail cuts are aligned conservatively to a late scene boundary near the end of the clip.

Force a full refresh instead of reusing cache:

```powershell
python -m src.main --input input --output output --review review --logs logs --reprocess-mode all
```

Write partial reports and provisional outputs after each clip:

```powershell
python -m src.main --input input --output output --review review --logs logs --clip-at-a-time --export-combined
```

Or with the helper:

```powershell
.\scripts\run_analysis.ps1
```

If FFmpeg is not on `PATH`:

```powershell
python -m src.main `
  --input input `
  --output output `
  --review review `
  --logs logs `
  --ffmpeg "C:\ffmpeg\bin\ffmpeg.exe" `
  --ffprobe "C:\ffmpeg\bin\ffprobe.exe"
```

### 5. Review the generated artifacts

Check:

- `output\clip_report.json`
- `output\clip_summary.csv`
- `review\review_report.md`
- `logs\gameplay_pipeline.log`
- `output\fights\` when fight export is enabled
- `output\combined_highlights.mp4` when combined export is enabled
- `output\_in_progress\` when `--clip-at-a-time` is enabled with exports

Use the Markdown report for a fast human pass. Use the JSON and CSV outputs if you want to feed later steps or build companion tooling.
The pipeline also keeps a reusable analysis cache in `intermediate\analysis_cache.json` by default.
When `--clip-at-a-time` is enabled, partial reports are overwritten during the run so you can inspect progress before the batch finishes.
The run log should also explicitly tell you whether a clip produced a provisional export or had no provisional keep segments.

### 6. Validate the heuristics against real footage

Before adding more automation, verify:

- clip ordering looks correct
- estimated overlaps match actual duplicated footage
- black/dead-space detections are useful enough to keep
- visual cut matches are correctly identifying non-fight screens
- static/text-heavy menu screens are being cut when they should be
- warnings are understandable and actionable

This matters because the overlap logic is still timestamp-based, not content-aware.

### 7. Decide the next feature phase

Best next implementation order:

1. Improve overlap confidence using frame or audio comparison.
2. Improve cut-template coverage and static/text-heavy menu detection with better tuning or additional heuristics.
3. Export review sidecars that are easier to consume in Resolve.
4. Add tests before the pipeline starts making editing decisions.

## Potential Features

Possible future features that are not implemented yet:

1. Lower-filesize export modes for easier sharing and upload.
2. Named quality/sensitivity presets.
3. Resolve-side timeline or marker export.
4. OCR-assisted text detection.
5. Portable packaged user build with a lightweight GUI.

## Deployment Model

This project is best deployed as a local workstation tool, not a service.

Recommended deployment pattern:

- keep the project in a dedicated local folder
- keep FFmpeg installed locally
- run analysis manually or from a scheduled/local script
- keep `input`, `output`, `review`, and `logs` as working directories on the same machine

That matches the project goal of low friction and local-first operation.

## Suggested Local Workflow

1. Record gameplay as usual.
2. Copy or move raw clips into `input\`.
3. Run the analysis command.
4. Open `review\review_report.md`.
5. Use the overlap, cut-template, static-screen, scene, black/dead-space, and keep-segment findings to guide the manual edit in DaVinci Resolve.
6. Keep the original source clips untouched.

If the exports are good enough, you can use the combined video directly as a first-pass highlight reel and the individual fight clips as modular building blocks.

## Folder Handling

Recommended operating convention:

- `input\`: raw clips dropped in for analysis
- `intermediate\`: future scratch outputs, caches, or segment sidecars
- `intermediate\analysis_cache.json`: reusable per-clip analysis cache
- `review\`: Markdown and human-facing outputs
- `output\`: JSON and CSV machine-readable outputs
- `output\fights\`: per-fight exported clips when enabled
- `logs\`: run logs
- `presets\`: future workflow presets

## Deployment Checklist

- Python installed
- FFmpeg installed
- venv created
- helper scripts working
- sample clips analyzed successfully
- reports generated successfully
- overlap results manually checked
- blackdetect usefulness manually checked
- scene boundaries checked on a few real sessions
- keep segments checked for obvious false positives
- cache reuse verified by rerunning against unchanged clips
- exported fight clips checked for pacing and cut accuracy
- combined highlight reel checked for transition quality

## Practical Hardening Before Wider Use

Before treating this as a stable repeatable production workflow, add:

- automated tests for config loading and report generation
- a known-good sample clip set for regression checks
- better executable validation at startup
- clearer confidence scoring for overlap warnings
- optional export naming conventions for multiple runs

## How To Deploy On Another Windows Machine

1. Copy the entire `gameplay-highlight-pipeline` folder.
2. Install Python.
3. Install FFmpeg.
4. Run `.\scripts\setup_env.ps1`.
5. Put footage into `input\`.
6. Run `.\scripts\run_analysis.ps1`.

No database, cloud service, or external API deployment is required for v1.

## What To Avoid Right Now

- do not auto-delete source footage
- do not auto-trim overlaps yet
- do not claim blackdetect or scene detection fully solves loading/menu removal
- do not build Resolve timeline automation until the keep-segment outputs are validated on real sessions

## Recommended Immediate Follow-Up

If you want the next phase built cleanly, the best next task is:

`Add a sample verification set and then improve content-aware overlap validation or static-screen/menu detection.`
