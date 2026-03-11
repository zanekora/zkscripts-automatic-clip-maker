# Project: Automated Gameplay Highlight Pipeline
Last updated: 2026-03-11

## 1. Project Goal

Build a local-first workflow and toolset that helps turn long raw gameplay recordings into polished highlight videos with minimal friction.

The system should help with all of the following:

- ingest multiple raw gameplay clips
- detect and handle overlap between clips
- remove or avoid loading screens, matchmaking, menus, and other non-action segments
- isolate match/fight/action segments as intelligently as possible
- make the editing process fast and repeatable
- support a final horizontal export and a final vertical export from the same source edit
- reduce manual work without making the result feel sloppy or over-automated

This project is intended to support an efficient creator workflow for action-heavy gameplay content.

---

## 2. Core Use Case

The user records gameplay locally at:

- **1920x1080**
- **30 FPS**

The recordings may include:

- multiple files for the same session
- overlapping content between one clip and the next
- menus
- matchmaking
- loading screens
- downtime between fights
- repeated or duplicated footage due to clip overlap

The desired output is:

1. a **horizontal master video** for YouTube / archive / longer-form viewing
2. a **vertical version** for TikTok / Shorts / Reels

The output should:

- contain only action or near-action moments
- avoid showing loading screens or matchmaking
- avoid duplicate footage caused by overlapping clips
- use clean transitions between fights
- be fast to produce repeatedly over time

---

## 3. High-Level Product Philosophy

This project should prioritize:

- **low friction**
- **repeatability**
- **local processing when possible**
- **clarity over cleverness**
- **strong defaults**
- **minimal manual steps**
- **easy iteration**
- **no destructive behavior without confirmation or backup**

The goal is not to fully replace creative judgment. The goal is to eliminate repetitive grunt work and speed up the path from raw footage to publishable clips.

This should feel like an assistant pipeline for a gameplay creator, not a rigid one-shot batch processor.

---

## 4. Primary Deliverables

Codex should help create the following:

### 4.1 Project documentation
Create clear documentation for:

- setup
- dependencies
- folder structure
- usage
- expected inputs
- expected outputs
- troubleshooting
- future expansion

### 4.2 Local preprocessing tool
A local script or small app that can:

- scan a folder of raw clips
- sort clips in a useful order
- inspect metadata where helpful
- identify likely overlapping files or overlapping time ranges
- detect obvious dead-space segments such as:
  - loading screens
  - menus
  - black screens
  - matchmaking screens
  - static/non-combat segments where feasible
- prepare clips or segment data for an editing workflow

### 4.3 Review-friendly outputs
The preprocessing step should ideally generate review-friendly artifacts such as:

- trimmed candidate clips
- timestamps or cut lists
- JSON metadata
- CSV or markdown reports
- EDL/XML-compatible data if practical
- any useful sidecar data for Resolve or manual review

### 4.4 Dual output workflow
The system should support:

- one **master horizontal timeline/output**
- one **derived vertical timeline/output**

The intention is to edit once and reuse the work for both outputs whenever possible.

---

## 5. Editing Workflow Expectations

The likely editing target is **DaVinci Resolve 20**.

The system does not need to fully replace Resolve. Instead, it should complement it.

Preferred workflow:

1. raw clips are dropped into an input folder
2. automation analyzes and prepares them
3. likely dead space is flagged or trimmed
4. likely overlap is identified
5. action segments are easier to review and assemble
6. a master edit is created or assisted
7. a vertical derivative version is produced with minimal extra work
8. exports are produced for both formats

If Resolve scripting is useful and practical, include it. If not, create a clean workflow that still makes Resolve use much faster.

---

## 6. Functional Requirements

### 6.1 Input handling
The system should support:

- common gameplay video files
- many clips in a folder
- clips that overlap partially
- clips that belong to the same session
- clips that may have inconsistent lengths

### 6.2 Overlap detection
The system should attempt to identify overlapping footage between clips.

Possible strategies may include:

- filename/date ordering
- metadata timestamps
- audio fingerprinting
- frame similarity
- visual fingerprinting
- configurable heuristics

The overlap system should aim to:

- prevent duplicate content in final edits
- help choose the better version of duplicated footage
- preserve continuity without repeated moments

### 6.3 Dead-space detection
The system should attempt to detect and remove or flag:

- loading screens
- black screens
- menus
- queue/matchmaking screens
- static post-match or pre-match screens
- obvious low-value downtime where detection is reasonably reliable

This should be configurable and non-destructive.

### 6.4 Action-first segmentation
The system should favor segments likely to contain gameplay action.

Possible signals may include:

- rapid motion changes
- HUD/state changes
- audio intensity changes
- scene cut detection
- visual similarity changes
- repeated non-action templates to exclude

The project should avoid pretending this is perfect. It should be robust, practical, and easy to manually review.

### 6.5 Transition-friendly output
Prepared clips should lend themselves to clean assembly with:

- short dissolves
- hard cuts where appropriate
- fight-to-fight pacing
- minimal awkward dead air

---

## 7. Vertical Video Requirements

The vertical output should be treated as a first-class target, not an afterthought.

### 7.1 Vertical format
Primary target:

- **1080x1920**
- **30 FPS**

### 7.2 Vertical workflow goals
The vertical workflow should make it easy to:

- derive a vertical version from the horizontal source
- keep the subject/action centered as much as possible
- support gameplay framed for TikTok / Shorts
- optionally include a lower area or template area for:
  - logo
  - game branding
  - title
  - subtitles/captions in the future

### 7.3 Reframing
If practical, support:

- auto-centering or smart reframing
- safe area guidance
- clip-level reframing metadata
- manual override where needed

This should be designed to work well with action footage where the subject may move quickly.

---

## 8. Preferred Technical Stack

Start with tools that are free, local, and well-supported.

Preferred candidates:

- **Python**
- **ffmpeg**
- **PySceneDetect**
- **DaVinci Resolve 20**
- optional lightweight GUI later if useful

Possible future additions:

- OpenCV
- audio fingerprinting libraries
- OCR only if truly necessary
- Resolve scripting integration
- subtitle/caption generation
- gameplay-specific heuristics

Avoid unnecessary infrastructure, cloud lock-in, or heavyweight dependencies unless there is a strong benefit.

---

## 9. Output Structure

Please design the project with a clean and understandable folder structure.

Suggested direction:

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

---

## 10. Current Implementation Status

As of **2026-03-11**, the local Python project under `gameplay-highlight-pipeline` currently implements:

- recursive clip scanning from `input/`
- metadata extraction with `ffprobe`
- heuristic overlap detection using estimated clip timestamps
- black/dead-space detection with `ffmpeg blackdetect`
- cut-template matching from user-provided reference images
- static/text-heavy menu-screen detection
- scene boundary detection with **PySceneDetect**
- reusable per-file analysis caching for unchanged clips
- optional prompt-driven reuse or reprocessing of cached clip analysis
- candidate keep-segment generation based on:
  - blocked-range removal
  - overlap-tail trimming
  - gap merging
  - optional scene-boundary alignment
- report generation to:
  - JSON
  - CSV
  - Markdown
- optional export of:
  - one clip per candidate fight segment
  - one combined highlight video assembled from exported fight clips
- optional clip-at-a-time partial report writing and provisional in-progress exports for faster review
- portable packaging scaffolding for a future bundled Windows user release

The current entry points are:

- `python -m src.main`
- `python .\gameplay_pipeline_v1.py`

---

## 11. Current Constraints And Truths

The following are true right now and should not be misrepresented:

- the workflow is still **non-destructive** to the original source media
- source clips are never modified or deleted
- overlap detection is still heuristic and mainly timestamp-based
- blackdetect only catches dark segments, not all menus or loading screens
- scene detection is useful but not equivalent to true action understanding
- exported fight clips are candidate segments, not guaranteed perfect final selects
- combined highlight export is a first-pass assembly, not a substitute for human finishing
- no Resolve timeline/XML/EDL export is implemented yet
- no vertical export workflow is implemented yet
- no content-aware menu/matchmaking classifier is implemented yet

---

## 12. Working Dependencies

Current practical dependencies for the implemented workflow are:

- Python 3.11+
- `ffmpeg`
- `ffprobe`
- `scenedetect`
- `opencv-python`

If scene detection is enabled, OpenCV must be installed in the active virtual environment.

---

## 13. Preferred Near-Term Roadmap

The next improvements should prioritize reliability over novelty:

1. Improve false-positive rejection for menus, loading screens, and low-value downtime.
2. Improve overlap validation using frame or audio similarity instead of timestamps alone.
3. Improve combined highlight assembly quality and pacing controls.
4. Add Resolve-friendly sidecar export after segment quality is stable.
5. Add sample-based regression tests using known gameplay clips.

---

## 14. User-Friendly Activation Principles

Future work should preserve these usability rules:

- everything optional should be controllable by simple CLI flags
- defaults should remain safe and non-destructive
- config files should expose tunable thresholds without requiring code edits
- export features should remain opt-in
- logs and reports should explain clearly what was detected, exported, skipped, or failed

Preferred examples:

- analysis only
- `python -m src.main --input input --output output --review review --logs logs`

- export one file per fight
- `python -m src.main --input input --output output --review review --logs logs --export-fights`

- export one combined highlight reel
- `python -m src.main --input input --output output --review review --logs logs --export-combined`

---

## 15. Source Of Truth Guidance

When the repo state and older planning text diverge:

- prefer the current code and current project docs
- do not claim unfinished features are implemented
- update this file when major workflow behavior changes
- keep the project pragmatic, local-first, and easy to operate on Windows
