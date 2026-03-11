# Changelog

## 0.1.0 - 2026-03-11

- Created initial Windows-friendly project structure.
- Added metadata extraction with `ffprobe`.
- Added overlap detection based on estimated clip timing.
- Added black/dead-space detection with `ffmpeg blackdetect`.
- Added scene detection with PySceneDetect.
- Added cut-template matching from reference screenshots.
- Improved template matching to support smaller UI-element templates in addition to full-screen screenshots.
- Made default cut-template matching more aggressive and sample frames more frequently.
- Added static/text-heavy menu-screen detection heuristics with config and CLI tuning.
- Fixed a template-matching bug that could cause only the last template to meaningfully influence scoring.
- Fixed static/text-heavy detection so it can still run even when no template images are present.
- Added support for both `br__name.png` and `br_name.png` style region-prefixed template filenames.
- Added support for `tc`, `bc`, `cl`, and `cr` region-prefixed template filenames.
- Added portable packaging scaffolding, runtime app-root path resolution, and local FFmpeg autodiscovery for future end-user releases.
- Added flash-transition detection so abrupt win/lose transitions can start a cut before the result UI fully settles.
- Added flash-to-terminal-tail behavior so a result-card signal after a flash can block the rest of the post-match animation.
- Added late-clip anchored region detection for result-card style UI that appears during animated post-match sequences.
- Added reusable per-file analysis caching and `--reprocess-mode`.
- Changed keep-segment generation to build longer contiguous gameplay spans instead of tiny scene fragments.
- Added `--clip-at-a-time` for partial reports and provisional early exports.
- Added optional per-fight clip export.
- Added optional combined highlight export.
- Added config, helper scripts, and project documentation.
