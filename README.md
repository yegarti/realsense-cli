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
- **Inspect** ROS bag files without a full ROS installation
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

**Run tests:**
```sh
uv run pytest                  # mock tests only (no camera required)
uv run pytest -m hardware      # hardware integration tests (camera required)
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
rs reset
```

---

## Options

| Option | Description |
|---|---|
| `-s`, `--serial` | Select device by serial number |
| `-v` | Verbose output (INFO); `-vv` for DEBUG |
| `-h`, `--help` | Show help for any command |
