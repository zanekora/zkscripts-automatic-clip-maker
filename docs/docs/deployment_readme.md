# Gameplay Pipeline V1.2 Deployment Guide

This guide covers the next practical steps to get the workflow running on a Windows machine and use it repeatedly as a local-first gameplay ingest and review tool.

## Purpose

The current workflow is a non-destructive analysis and export pipeline. It does not trim, rewrite, or delete the original clips. It scans raw gameplay files, extracts metadata, flags likely overlaps, detects black/dead-space candidates, detects scene boundaries, optionally matches reference cut templates, applies static/text-heavy menu heuristics, and generates candidate keep segments for manual editing follow-up or optional exports.

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

If you have representative screenshots of screens that should be cut, place them in:

```text
presets\cut_templates\
```

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

When the follow-up UI signal is strong enough, the default behavior can also hold that cut through the rest of the post-match tail instead of letting the winner animation slip back into the export.

The visual-cut system can also use late-clip anchored region heuristics, which are especially useful when a bottom-right or bottom-center result panel appears during an animated win/lose sequence.

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
