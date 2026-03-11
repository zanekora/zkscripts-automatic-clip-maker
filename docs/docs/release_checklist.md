# Release Checklist

## Before Making The Repo Public

- Remove any personal gameplay clips from `input/`.
- Remove generated artifacts from `output/`, `review/`, and `logs/`.
- Confirm `.gitignore` is present and correct.
- Confirm no runtime media or generated artifacts are tracked in git.
- Confirm the README reflects the actual current behavior.
- Confirm `requirements.txt` and `pyproject.toml` match runtime dependencies.
- Confirm no private absolute paths remain in docs except as examples.
- Confirm the MIT license text is present in `LICENSE`.

## Before Tagging A Release

- Run the tool on a known sample set.
- Verify `clip_report.json`, `clip_summary.csv`, and `review_report.md`.
- Verify at least one per-fight export run.
- Verify at least one combined export run.
- Verify `--clip-at-a-time` behavior if you plan to document or demo it.
- Verify cache reuse and `--reprocess-mode` behavior.
- Review logs for misleading or repeated failures.
- Update `CHANGELOG.md`.
- Bump the version in `pyproject.toml`.

## Suggested First Public Release Positioning

Recommended wording:

- alpha
- Windows-first
- local-first
- heuristic, review-assisted workflow

Avoid claiming:

- full automation
- reliable action understanding
- complete menu/loading-screen detection
- perfect overlap removal in all cases

## Git Hygiene

Runtime folders should stay out of the repository:

- `input/`
- `intermediate/`
- `output/`
- `review/`
- `logs/`

Keep only structure placeholders such as `.gitkeep`.
