# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
uv sync

# Run CLI
uv run rs

# Run tests
uv run pytest

# Format code
uv run black realsense_cli/

# Type check
uv run mypy realsense_cli/

# Run a single test
uv run pytest tests/test_cli.py::test_list_devices -s
```

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

`rs_bag_parser.py` uses `rosbags` to parse ROS2 bag files without a ROS installation.

## Code style

Line length: 96 (Black). Python 3.11+.
