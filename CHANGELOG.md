# Changelog

All notable changes to the Adaptive Cover Pro Simulator are documented here.

This project uses [CalVer](https://calver.org/) in the format `YYYY.MM.PATCH`.
The `PATCH` number resets to `1` at the start of each month. Every release is
also tagged in git as `vYYYY.MM.PATCH`.

## [2026.10.1] — 2026-10-27

Initial public release.

### Added

- **Headless replay of the real engine.** The simulator imports the Adaptive
  Cover Pro engine, cover-type policies, pipeline handlers/registry and
  diagnostics builder directly, so the computed position, decision trace and
  diagnostics JSON match Home Assistant byte-for-byte — no reimplementation.
- **Local web UI** (FastAPI + static frontend) with:
  - A sun-path diagram and a time slider to move the sun through any day.
  - Location controls (latitude, longitude, elevation, timezone) with
    persistence between sessions.
  - A configuration editor generated from the integration's own `FieldSpec`
    schema, including section titles, icons, labels, descriptions and selector
    options pulled from `translations/en.json`.
  - Separate **Entities** and **Environment** panels, with `entity_id` hints on
    entity fields.
  - A **Result** panel showing the computed position, active pipeline branch and
    the full diagnostics payload.
- **Diagnostics import/export.** Accepts both the full Home Assistant
  diagnostics envelope and a bare `data` payload; "Copy config" emits a
  re-importable diagnostics JSON that is also persisted across refreshes.
- **Supported cover types (v1):** blind, awning and tilt.
- **Session persistence** via a single `localStorage` key, covering location,
  cover type, options, environment, date and time.
- Cross-platform launchers (`run.ps1` on Windows, `run.sh` on macOS/Linux) that
  create a local virtualenv and install dependencies on first run.
- Documentation covering setup, dependencies, usage and limitations.
