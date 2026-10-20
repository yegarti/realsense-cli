# realsense-cli

> A modern command-line interface for [Intel RealSense](https://github.com/IntelRealSense/librealsense) cameras, built on [pyrealsense2](https://pypi.org/project/pyrealsense2/).

[![PyPI version](https://img.shields.io/pypi/v/realsense-cli)](https://pypi.org/project/realsense-cli/)
[![Python](https://img.shields.io/pypi/pyversions/realsense-cli)](https://pypi.org/project/realsense-cli/)
[![License](https://img.shields.io/pypi/l/realsense-cli)](LICENSE)

---

## Features

- **List** connected devices and their supported streaming profiles
- **Configure** sensor controls (exposure, gain, laser power, etc.)
- **Stream** selected profiles and monitor live FPS per stream
- **Inspect** ROS1 bag files without a full ROS installation
- Multi-device support via `--serial`

---

## Installation

**uv** (recommended):
```sh
uv tool install realsense-cli   # install permanently
uvx realsense-cli               # run without installing
```

**pipx:**
```sh
pipx install realsense-cli
```

**pip:**
```sh
pip install realsense-cli
```

---

## Development

**Clone and set up:**
```sh
git clone https://github.com/yegarti/realsense-cli.git
cd realsense-cli
uv sync
```

**Run the CLI from source:**
```sh
uv run rs --help
```

**Checks** (requires [`just`](https://github.com/casey/just)):
```sh
just check                     # lint, type check and tests, as CI runs them
just test                      # tests with coverage (no camera required)
just test -m hardware          # hardware integration tests (camera required)
just fmt                       # format and apply lint fixes with ruff
```

---

## Quick Start

```sh
rs --help          # top-level help
rs list            # show connected devices
rs stream play     # start all streams with default settings
```

Use `-s / --serial` to target a specific device when multiple are connected:
```sh
rs -s 801312071342 stream play depth
```

---

## Commands

### `rs list` — connected devices

```
> rs list

                                     Devices
          Name              Serial       Firmware    USB Connection      Sensors
 ───────────────────────────────────────────────────────────────────────────────
  Intel RealSense D435   801312071342   5.13.0.51        2.1          Stereo Module
                                                                       RGB Camera
  Intel RealSense D415   732612060537   5.15.0.2         3.2          Stereo Module
                                                                       RGB Camera
```

---

### `rs config` — sensor controls

**List all writable controls for a sensor:**
```sh
rs config list depth
rs config list color
```

**Read control values:**
```sh
rs config get depth exposure laser_power
```
```
  Name          Value
 ──────────────────────
  exposure      8500.0
  laser_power   150.0
```

**Write control values:**
```sh
rs config set depth exposure=15000 laser_power=120
```

**Read all controls at once:**
```sh
rs config get depth --all
```

---

### `rs stream` — streaming

**List supported profiles for a sensor (or all sensors):**
```sh
rs stream list
rs stream list depth
```
```
                     Streams
  Stream       Resolution   FPS          Format
 ───────────────────────────────────────────────
  Depth        640x480      6/15/30      Z16
  Infrared 1   640x480      6/15/30      Y8
  Infrared 2   640x480      6/15/30      Y8
  Color        640x480      6/15/30      RGB8
  ...
```

**Start streaming — profile syntax:** `STREAM[-WxH[-FPS[-FORMAT]]]`

```sh
rs stream play                             # all streams, default settings
rs stream play depth                       # depth only
rs stream play depth color                 # depth + color
rs stream play depth-640x480-30-z16        # fully specified profile
rs stream play depth-640x480-30 color-0x0-15
```

**Live view** (Ctrl-C to stop):
```
  ╭─────── Depth (0) 640x480 15fps z16 ───────╮
  │ Frame #69       FPS: 15.01                │
  ╰───────────────────────────────────────────╯
  ╭───── Infrared 1 (1) 640x480 15fps y8 ─────╮
  │ Frame #66       FPS: 15.01                │
  ╰───────────────────────────────────────────╯
  ╭────── Color (0) 640x480 15fps rgb8 ───────╮
  │ Frame #68       FPS: 15.01                │
  ╰───────────────────────────────────────────╯
```

Hide metadata with `--no-md`. Switch to the low-level sensor API with `--sensor`.

---

### `rs bag` — ROS bag inspection

```sh
rs bag info recording.bag
```

Displays bag duration and per-topic message counts without requiring a full ROS installation.

---

### `rs reset` — hardware reset

```sh
rs reset                    # reset the device
rs reset --wait             # ...and wait until it is connected again (--timeout, default 30s)
rs -s 123456789 reset       # pick a device when several are connected
rs reset --yes              # several connected: reset the first one without asking
```

With one device connected, or `--serial` given, `rs reset` resets right away. When several devices
are connected and no `--serial` was given, it asks before resetting the first one, unless `--yes`
is given. Without a terminal to ask on, or under `--json`, it fails with exit code `8` instead of
asking. With `--wait`, a device that doesn't come back within `--timeout` (only valid with `--wait`)
fails with exit code `3`.

---

## Options

| Option | Description |
|---|---|
| `-s`, `--serial` | Select device by serial number |
| `--json` | Print results as JSON (see [JSON output](#json-output)) |
| `-v` | Verbose output (INFO); `-vv` for DEBUG |
| `-h`, `--help` | Show help for any command |

## JSON output

`rs --json <command>` prints one JSON object on stdout instead of a table, for scripts and
agents. Each command's result sits under a named key, so fields can be added without breaking
parsers.

| Command | Output |
|---|---|
| `rs list` | `{"devices": [{"name", "serial", "fw", "connection", "sensors": [...]}]}` |
| `rs config list SENSOR` | `{"sensor", "controls": [{"name", "description", "min_value", "max_value", "step", "default_value", "vtype": "int" \| "float", "read_only"}]}` |
| `rs config get` / `set` | `{"sensor", "values": {"<control>": <value>}}`; `set` returns the values read back from the device |
| `rs stream list` | `{"profiles": [{"sensor", "stream", "width", "height", "fps", "format", "index"}]}` |
| `rs bag info BAG` | `{"path", "duration", "topics": [{"name", "messages", "type"}]}` |
| `rs reset` | `{"reset": "<serial>"}`; with `--wait`, also `"reconnected": true` |

`rs stream play` runs until interrupted and rejects `--json` with exit code `2`.

With `--json`, an error is a JSON object on the last line of stderr (warnings such as the
multiple-devices notice may come before it), stdout stays empty, and the exit code is the same as
without it (see below). Usage errors have `"type": "UsageError"`. Errors in the global options
themselves (e.g. an unknown option before the command) are reported by click as plain text, and
`-v` keeps showing the traceback for unexpected errors.

```json
{"error": {"type": "UnknownSensor", "message": "Unknown sensor 'bogus'. Valid sensors: ...", "exit_code": 4}}
```

## Exit codes

Errors print a one-line message to stderr. Unexpected errors show a traceback only with `-v`.

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | Other or unexpected error |
| `2` | Invalid command-line usage |
| `3` | No device connected, none matches `--serial`, or a reset device didn't reconnect |
| `4` | Unknown sensor |
| `5` | Unknown control |
| `6` | Invalid or unsupported stream profile |
| `7` | Invalid control value |
| `8` | Confirmation needed: several devices connected, add `--serial` or `--yes` |
| `130` | Interrupted (Ctrl+C) |
