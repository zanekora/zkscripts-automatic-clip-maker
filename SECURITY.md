# Security Policy

## Supported Scope

This project is a local-first desktop workflow and is not intended to expose a network service.

Security-sensitive areas still include:

- shelling out to `ffmpeg` and `ffprobe`
- handling untrusted media files
- future Resolve scripting hooks
- any future import/export or plugin integrations

## Reporting

If you discover a security issue, please avoid posting a public exploit immediately.

Preferred initial report contents:

- affected file or module
- reproduction steps
- expected vs actual behavior
- whether the issue requires malicious media input or local user access

This file describes a preferred disclosure path only. It does not create any obligation to provide support, response timelines, fixes, or ongoing maintenance.

## Current Risk Notes

- The tool processes local files and invokes external executables.
- Media parsing is delegated primarily to FFmpeg and OpenCV-backed tooling.
- The project currently assumes trusted local execution on Windows.
