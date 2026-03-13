# V1 Status

## Implemented

- Recursive clip inventory
- `ffprobe` metadata extraction
- Timestamp-based overlap estimation
- `ffmpeg blackdetect` parsing
- PySceneDetect scene boundary detection
- Cut-template matching from reference screenshots
- Partial-template matching for smaller UI elements
- Static/text-heavy menu-screen detection
- Flash-transition detection that can hand off into result/menu cuts
- Late-clip anchored region detection for result-card style UI
- Dedicated terminal template folder for stronger late end-state confirmation
- Separate fullscreen and partial template folders for clearer end-user setup
- Active fight template folder for positive in-match keep signals
- Reusable per-file analysis cache
- Candidate keep-segment generation from blocked-range removal, overlap-tail trimming, and optional scene-boundary alignment
- Terminal tail ranges are preserved separately from generic cut spans so late end-state cuts keep their correct start time
- Terminal tail ranges are conservatively snapped to a late scene boundary near clip end
- Visual-cut analysis now uses sequential sampled frame scanning instead of repeated random seeks
- Optional clip-at-a-time partial reporting and provisional exports
- Optional per-fight clip export
- Optional combined highlight export
- Portable packaging scaffolding for a future PyInstaller-based Windows release
- JSON, CSV, and Markdown reporting
- Config-driven CLI defaults
- Windows setup and execution helpers

## Scaffolded

- Modular analysis package layout
- Config override flow for later feature additions
- Separate modules for FFmpeg interaction, reporting, and analysis heuristics

## Not Yet Implemented

- Menu/loading-screen heuristics beyond black detection
- Automatic trimming
- Resolve integration
- Vertical reframing metadata
- Tests
