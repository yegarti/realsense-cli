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

All hardware interaction goes through the driver interface in `driver/base.py`. `driver/__init__.py:create_driver()` builds the `Realsense` driver (`driver/realsense.py`), which wraps `pyrealsense2`.

The root callback puts a `Session` (`session.py`) in `ctx.obj`; it creates the driver on first use. Commands that need a camera take `ctx: typer.Context` and call `require_device(ctx)`, which raises `DeviceNotFound` when none is connected; `rs list` uses `get_driver(ctx)`. Commands that need no camera (`bag`, `--help`) never create an `rs.context`, and `pyrealsense2` is imported only inside `create_driver()`, never at CLI import time.

`driver/software.py` simulates a D435 on `rs.software_device`, injected into the real driver with `Realsense(devices=[...])`. pyrealsense2 can't add a software device to an `rs.context`, so the pipeline can't see it, and `play()` on injected devices always streams through the sensor API. A software device only produces frames that are pushed to it.

`typings/pyrealsense2/__init__.pyi` is a partial stub for the pyrealsense2 API this project uses (the package ships no type information). Add any newly used pyrealsense2 call to it, or `ty` fails.

- `RSCLI_DRIVER=mock` runs the CLI against the simulated D435, with a background thread pushing frames (`start_frame_pump()`).
- Tests get the same camera from the `driver` fixture in `tests/conftest.py` and push frames themselves with `camera.push_frames()`. No hardware is needed, and a connected camera is ignored. `inject_driver` serves any driver to CLI commands by replacing `session.create_driver`.

### Commands

| Command | Module | Purpose |
|---|---|---|
| `rs list` | `cli.py` | List connected devices |
| `rs info` | `commands/info.py` | Device details (every camera info field); with profiles or `--all-profiles`, intrinsics and extrinsics |
| `rs config list/get/set/restore` | `commands/config.py`, `restore.py` | Read/write sensor controls, restore defaults |
| `rs stream list/play` | `commands/stream.py` | List profiles, or stream with a live view; `--frames`/`--duration` make it a bounded run that reports frames per stream |
| `rs capture` | `commands/capture.py`, `png.py`, `npy.py` | Bounded run that saves framesets as PNGs and/or `.npy` arrays (`--format`) plus a `capture.json` sidecar |
| `rs bag info` | `commands/bag.py` | Inspect ROS bag files |
| `rs reset` | `cli.py` | Hardware reset |

### Key types (`types.py`)

- `DeviceInfo` — device metadata
- `Sensor` `StrEnum` — known sensors: `STEREO_MODULE`, `RGB_CAMERA`, `MOTION_MODULE`
- `Stream` `StrEnum` — known streams: `DEPTH`, `INFRARED`, `INFRARED2`, `COLOR`, `GYRO`, `ACCEL`
- Fields holding a sensor or stream name from a device are typed `str`, not the enum: a new camera's unknown names pass through unchanged. Enum members compare equal to their plain string.
- `Option` — a control's range, step and default as `float`, with `vtype` `int` or `float`
- `Profile` — `(stream, resolution, fps, format, index)`; CLI syntax: `depth-640x480-30-z16`
- `Calibration` — `StreamIntrinsics` (an `Intrinsics` shared by a stream's profiles at one resolution) and `Extrinsics` between streams
- `Frame` / `FrameSet` — single frame and `dict[str, Frame]` keyed by stream name; `wait_for_frameset(images=True)` also fills a video frame's `Image` (and a depth frame's SDK-colorized one)

### Output

All output goes through the shared consoles in `console.py`: `console` for command output (stdout), `err_console` for diagnostics (stderr). Bare `print` is a lint error (ruff `T20`).

Commands build their result as a plain dict and pass it to `printer.emit(ctx, payload, table=...)`, which prints it as JSON under the global `--json` flag (shapes documented in the README) and otherwise calls the table renderer. `printer.py` handles Rich table formatting for device/profile/control listings. `stream_view.py` renders the live stream display using Rich Live.

`rs_bag_parser.py` uses `rosbags` (the rosbag1 `Reader`) to parse ROS1 bag files without a ROS installation.

### Errors

Raise an `RsCliError` subclass from `errors.py` (`DeviceNotFound`, `UnknownSensor`, `UnknownControl`, `InvalidProfile`, `InvalidValue`, `ConfirmationRequired`, `NoFrames`) for anything the user can fix; messages list the valid values. `RsCliGroup` in `cli.py` turns them into a one-line stderr message (a JSON `{"error": ...}` object under `--json`, click usage errors included) and the class's `exit_code` (documented in the README). Other exceptions print one line too, with the traceback only under `--verbose`.

## Code style

Formatting and linting with ruff (`just fmt` / `just lint`), line length 96. Python 3.11+.

## Agent skills

### Issue tracker

Issues are tracked in GitHub Issues on `yegarti/realsense-cli` (via `gh`). See `docs/agents/issue-tracker.md`.

### Triage labels

Default vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `GLOSSARY.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.
