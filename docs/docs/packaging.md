# Packaging Notes

This project is being prepared for a future low-friction Windows user release.

## Intended End-User Shape

The preferred packaging target is a portable Windows folder:

```text
GameplayHighlightPipeline/
  GameplayHighlightPipeline.exe
  ffmpeg.exe
  ffprobe.exe
  config/
  presets/
  input/
  intermediate/
  output/
  review/
  logs/
```

Goal:

- no Python install required
- no separate FFmpeg install required
- user can unzip and run

## What Is Already Prepared

- runtime paths now resolve relative to the application root
- config and presets are treated as app-local resources
- local `ffmpeg.exe` and `ffprobe.exe` in the app folder are auto-discovered
- a PyInstaller spec file exists at `packaging/gameplay_pipeline.spec`
- a PowerShell build helper exists at `scripts/build_exe.ps1`

## What Is Still Needed For A Real User Release

- run PyInstaller and verify the frozen app behavior
- bundle `ffmpeg.exe` and `ffprobe.exe` into the portable output
- test on a machine without Python installed
- possibly add a minimal GUI launcher for non-technical users
- verify OpenCV/PySceneDetect behavior in the frozen build

## Build Direction

Current recommendation:

- use `PyInstaller --onedir`
- keep FFmpeg bundled as sibling executables
- keep config/presets as normal files alongside the executable

That is more maintainable than a single-file executable for this project.
