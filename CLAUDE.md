# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
uv sync

# Run CLI
uv run rs

# Run lint, type check and tests (what CI runs)
just check

# Run tests with coverage (extra args go to pytest)
just test

# Lint and check formatting (ruff)
just lint

# Format code and apply lint fixes (ruff)
just fmt

# Type check (ty)
just typecheck

# Run a single test
just test tests/test_cli.py::test_list
```

CI (`.github/workflows/ci.yml`) runs `just check` on PRs and pushes to `main`. Tests marked `hardware` are excluded by default.

## Architecture

**`rs`** is a Typer-based CLI for Intel RealSense cameras. The entry point is `realsense_cli/cli.py`, which defines the root app with a callback for global options (`--serial`, `--verbose`) and registers sub-apps from `commands/`.

### Driver abstraction

All hardware interaction goes through a driver interface. `driver/__init__.py:get_driver()` returns either:
- `driver/realsense.py` — wraps `pyrealsense2` (production, default)
- `driver/mock.py` — simulates a D435 camera (testing, set `RSCLI_DRIVER=mock`)

Tests always use the mock driver via the fixture in `tests/conftest.py`.

### Commands

| Command | Module | Purpose |
|---|---|---|
| `rs list` | `cli.py` | List connected devices |
| `rs config list/get/set` | `commands/config.py` | Read/write sensor controls |
| `rs stream list/play` | `commands/stream.py` | List profiles or start live stream |
| `rs bag info` | `commands/bag.py` | Inspect ROS bag files |
| `rs reset` | `cli.py` | Hardware reset |

### Key types (`types.py`)

- `DeviceInfo` — device metadata
- `Sensor` enum — `STEREO_MODULE`, `RGB_CAMERA`, `MOTION_SENSOR`
- `Stream` enum — `DEPTH`, `INFRARED`, `COLOR`, `GYRO`, `ACCEL`
- `Profile` — `(stream, width, height, fps, format)`; CLI syntax: `depth-640x480-30-z16`
- `Frame` / `FrameSet` — single frame and `Dict[Stream, Frame]`

### Output

`printer.py` handles Rich table formatting for device/profile/control listings. `stream_view.py` renders the live stream display using Rich Live.

`rs_bag_parser.py` uses `rosbags` (the rosbag1 `Reader`) to parse ROS1 bag files without a ROS installation.

## Code style

Formatting and linting with ruff (`just fmt` / `just lint`), line length 96. Python 3.11+.

## Agent skills

### Issue tracker

Issues are tracked in GitHub Issues on `yegarti/realsense-cli` (via `gh`). See `docs/agents/issue-tracker.md`.

### Triage labels

Default vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `GLOSSARY.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.
