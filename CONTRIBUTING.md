# Contributing

## Scope

This project is currently focused on a practical Windows-first workflow for:

- gameplay clip analysis
- overlap detection
- dead-space detection
- scene-based candidate segment generation
- optional export of per-fight clips and a combined highlight reel

Changes should keep the workflow:

- local-first
- non-destructive to source media
- easy to operate from PowerShell
- modular and easy to inspect

## Development Setup

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Guidelines

- Prefer clear heuristics over opaque complexity.
- Do not claim features are implemented if they are only scaffolded.
- Keep new export behavior opt-in.
- Avoid changing or deleting original clips.
- Keep Windows examples and paths valid for PowerShell users.

## Validation

Before opening a PR, run:

```powershell
python -m py_compile .\gameplay_pipeline_v1.py .\src\main.py (Get-ChildItem .\src\gameplay_pipeline\*.py | Select-Object -ExpandProperty FullName)
python -m src.main --help
```

If you test against real media, do not commit files from:

- `input/`
- `output/`
- `review/`
- `logs/`
