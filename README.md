# realsense-cli

> A modern command-line interface for [Intel RealSense](https://github.com/IntelRealSense/librealsense) cameras, built on [pyrealsense2](https://pypi.org/project/pyrealsense2/).

[![PyPI version](https://img.shields.io/pypi/v/realsense-cli)](https://pypi.org/project/realsense-cli/)
[![Python](https://img.shields.io/pypi/pyversions/realsense-cli)](https://pypi.org/project/realsense-cli/)
[![License](https://img.shields.io/pypi/l/realsense-cli)](LICENSE)

---

## Features

- **List** connected devices and their supported streaming profiles
- **Show** a device's details and calibration (intrinsics, extrinsics)
- **Configure** sensor controls (exposure, gain, laser power, etc.)
- **Stream** selected profiles and monitor live FPS per stream
- **Capture** framesets to PNG or NumPy `.npy` files with a JSON sidecar, to look at or load afterwards
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

### `rs info` — device details and calibration

**Every camera info field the device reports, and its sensors:**
```
> rs info

                                            Device

  Name                  RealSense D455
  Serial Number         801312071342
  Firmware Version      5.17.3.10
  Physical Port         /sys/devices/pci0000:00/0000:00:14.0/usb2/2-1/2-1:1.0/video4linux/video0
  Debug Op Code         15
  Advanced Mode         YES
  Product Id            0B5C
  Camera Locked         NO
  Connection Type       USB
  Usb Type Descriptor   3.2
  Product Line          D400
  Asic Serial Number    031323060591
  Firmware Update Id    031323060591
  Imu Type              BMI055
  Sensors               Stereo Module (depth)
                        RGB Camera (color)
                        Motion Module (motion)
```

A field the device reports as `unknown` (e.g. the IMU type of a D415, which has no IMU) is left
out.

**Add calibration for some profiles, or for all of them** (like `rs-enumerate-devices -c`):
```sh
rs info depth color                 # every depth and color video profile
rs info depth-1280x720 color-0x0-30 # same partial syntax as `rs stream play`
rs info --all-profiles              # every video profile
```
```
> rs info --all-profiles
...
                                             Intrinsics

  Stream       Resolution         ppx          ppy          fx          fy   Formats
 ──────────────────────────────────────────────────────────────────────────────────────────────────
  Depth        1280x720      630.2564     361.3397    647.8624    647.8624   Z16
               848x480      417.54486    240.88754   429.20886   429.20886   Z16
               ...

  Infrared 1   1280x800           n/a          n/a         n/a         n/a   Y16
               1280x800      630.2564     401.3397    647.8624    647.8624   Y8
               ...

  Color        1280x800      643.5558    404.56467    636.9544    636.7007   RGB8, BGRA8, RGBA8, BGR8, YUYV
               ...

                                             Distortion

  Stream       Model                   Coefficients
 ──────────────────────────────────────────────────────────────────────────────────────────────────
  Depth        brown_conrady           0, 0, 0, 0, 0
  Infrared 1   brown_conrady           0, 0, 0, 0, 0
  Color        inverse_brown_conrady   -0.05178671, 0.059920404, -0.0010254717, 0.00043725056, -0.018729214
  ...

                                   Extrinsics

  From    To      Rotation                                     Translation (m)
 ──────────────────────────────────────────────────────────────────────────────
  Depth   Color       0.9999991 -0.0011860202   0.0006337429     -0.059180804
                   0.0011865316      0.999999 -0.00080718077   -0.00009067777
                  -0.0006327849   0.000807932     0.99999946   -0.00015896332
  ...
```

Unset parts of a profile match anything, so `depth` covers every depth profile. Profiles that
differ only in format or frame rate share their intrinsics and are shown once; the distortion
model and coefficients, which rarely change with the resolution, are shown once per stream.
Profiles the SDK has no intrinsics for (the infrared Y16 ones) show `n/a`. Extrinsics are listed
for each ordered pair of the matched streams. A profile that matches no video profile fails with
exit code `6`. `rs list` stays the short summary.

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
Some read-only controls, such as `asic_temperature` and `projector_temperature` on a D400 camera,
can only be read while the camera is streaming. `--all` shows them as `unavailable` and reads the
rest; naming one explicitly fails with exit code `10`.

**Restore controls to their defaults:**
```sh
rs config restore                         # every control on every sensor
rs config restore depth                   # one sensor
rs config restore depth exposure gain     # only these controls
rs config restore --keep-going            # don't stop at a control that fails to write
```
```
                    Restored controls
  Sensor          Control       Old Value   New Value
 ─────────────────────────────────────────────────────
  Stereo Module   exposure      1000.0      8500.0
```

Only controls whose value changed are listed. Read-only controls are skipped. Unlike `rs reset`,
the device stays connected.

Some controls move others, so `visual_preset` is written first, and the auto modes
(`enable_auto_exposure`, `enable_auto_white_balance`) and gates (`auto_exposure_limit_toggle`,
`auto_gain_limit_toggle`, `hdr_enabled`) last. Restore leaves alone:

- exposure, gain and white balance while their auto mode is on and stays on: the camera drives them
- the auto exposure/gain limits and the HDR sequence while their gate ends off: they don't apply then
- `error_polling_enabled`: the SDK turns it back on in every new process

A control that fails to write stops the restore with exit code `7`; controls already written stay
restored. With `--keep-going` the other controls are still restored, the failed ones are listed,
and the exit code is `7`.

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

**Bounded run** — a smoke check that frames arrive. `--frames N` stops once every stream received
N frames, `--duration S` after S seconds; given both, whichever comes first. The run then prints
the frames received per stream:
```sh
rs stream play depth color --frames 100
rs --json stream play --duration 5
```
```
 Frames received
  Stream   Frames
 ────────────────
  Depth       100
  Color       100
```

The streams checked are the ones the device started, so without profiles every default stream
counts. A stream that received no frames fails the run with exit code `9`, as does a stream that
sends nothing for 3 seconds before it has its N frames (or, with `--duration`, before the time
is up). Frames are counted by frame number: when the pipeline hands out a slower stream's last
frame again in a later frameset, it counts once.

---

### `rs capture` — save framesets to files

A capture streams, discards the frames of the first second so auto-exposure settles, then saves
a frameset to files that a person, a script or an agent can open afterwards:
```sh
rs capture                                 # default depth and color profiles
rs capture depth infrared color --frames 5 # 5 framesets of three streams
rs capture color-1280x720-30 -o shots      # into ./shots
rs capture --warmup 3                      # let auto-exposure settle for 3 seconds
rs capture --format npy --format png       # NumPy arrays as well as PNGs
```
```
/home/me/rs-capture-20261021-143005/depth-0.png
/home/me/rs-capture-20261021-143005/depth-0-colorized.png
/home/me/rs-capture-20261021-143005/color-0.png
/home/me/rs-capture-20261021-143005/capture.json
```

Profiles take the `rs stream play` syntax. A profile that leaves the format unset is captured in
Z16 for depth, Y8 for infrared and RGB8 for color; Y16, BGR8, RGBA8 and BGRA8 can be asked for,
and YUYV with `--format npy`. Each stream gets a file per frameset, named after its alias and the
frameset's number, padded so the files sort in order (`depth-00.png` to `depth-11.png` for `--frames 12`):

| Stream | Files |
|---|---|
| Depth | `depth-N.png`, a 16-bit grayscale PNG of the raw depth values (multiply by the depth scale for meters), and `depth-N-colorized.png`, colorized by the SDK for viewing |
| Infrared, color | `infrared-N.png`, `infrared2-N.png`, `color-N.png`, 8-bit grayscale or RGB(A) |

`--format` picks the **file formats** the frames are saved in, `png` by default; repeat it for
several (`--format npy --format png`). It is not the **stream format** (Z16, RGB8 ...), which the
profile sets. Each file format's files share the PNG file names, with their own extension:

| File format | Files |
|---|---|
| `png` | as above; BGR(A) is stored as RGB(A). `depth-N-colorized.png` is written only with `png` |
| `npy` | `depth-N.npy`, `color-N.npy` ...: a NumPy array of the values as the camera sent them, for `numpy.load` |

| Stream format | `.npy` dtype and shape |
|---|---|
| Z16, Y16 | `uint16 (H, W)`; depth is the raw values, as in `depth-N.png` (multiply by the depth scale for meters; 0 is no depth) |
| Y8 | `uint8 (H, W)` |
| RGB8, BGR8 | `uint8 (H, W, 3)`; BGR8 stays in BGR order |
| RGBA8, BGRA8 | `uint8 (H, W, 4)`; BGRA8 stays in BGRA order |
| YUYV | `uint8 (H, W, 2)` as sent: `Y0 U`, `Y1 V` for each pair of pixels. PNG can't hold it |

A profile must suit every file format asked for; otherwise the capture fails with exit code `6`,
naming the file format that can't hold it.

`capture.json` describes the capture, with file names relative to its directory:
```json
{
  "device": {"name": "Intel RealSense D435", "serial": "012345678"},
  "depth_scale": 0.001,
  "profiles": [{"stream": "Depth", "width": 640, "height": 480, "fps": 30, "format": "Z16", "index": 0}],
  "framesets": [
    {"frames": [{"stream": "Depth", "frame_number": 6, "timestamp": 200.0,
                 "metadata": {"actual_fps": 30000}, "files": ["depth-0.png", "depth-0-colorized.png"]}]}
  ]
}
```

`depth_scale` is `null` on a device without a depth sensor. Each frame's `files` lists every
file written for it, in every file format. The output directory (`-o`) must be
new or empty unless `--force` is given, which overwrites files of the same name and leaves the
others. The default, `./rs-capture-<timestamp>`, is always new: a capture in the same second gets
`-2`, `-3`, ... appended. A stream that sends no frames for 3 seconds before the
last frameset is complete fails the capture with exit code `9`, and nothing is written.

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
| `rs info` | `{"device": {"<camera_info>": "<value>"}, "sensors": [...]}`: every camera info field the device supports and doesn't report as `unknown`, keyed by its `rs.camera_info` name (`name`, `serial_number`, `firmware_version`, `connection_type`, `product_id`, ...) |
| `rs info PROFILES...` / `--all-profiles` | also `"intrinsics": [{"stream", "index", "width", "height", "formats": [...], "fps": [...], "ppx", "ppy", "fx", "fy", "model", "coeffs": [...]}]`, with `ppx` to `coeffs` `null` for profiles the SDK has no intrinsics for, and `"extrinsics": [{"from", "to", "rotation": [9 values, column-major], "translation": [x, y, z] in meters}]` |
| `rs config list SENSOR` | `{"sensor", "controls": [{"name", "description", "min_value", "max_value", "step", "default_value", "vtype": "int" \| "float", "read_only"}]}` |
| `rs config get` | `{"sensor", "values": {"<control>": <value>}, "unavailable": [...]}`; `unavailable` lists the controls `--all` skipped because the camera can't read them right now (empty otherwise) |
| `rs config set` | `{"sensor", "values": {"<control>": <value>}}`: the values read back from the device |
| `rs config restore` | `{"restored": [{"sensor", "control", "old", "new"}], "failed": [{"sensor", "control", "error"}]}`; only the controls whose value changed. `failed` is only filled with `--keep-going`, which then prints the result on stdout and exits `7` |
| `rs stream list` | `{"profiles": [{"sensor", "stream", "width", "height", "fps", "format", "index"}]}` |
| `rs stream play --frames N` / `--duration S` | `{"streams": [{"stream", "frames"}]}` |
| `rs capture` | `{"directory", "files": [...]}`: absolute paths of the files written, `capture.json` last |
| `rs bag info BAG` | `{"path", "duration", "topics": [{"name", "messages", "type"}]}` |
| `rs reset` | `{"reset": "<serial>"}`; with `--wait`, also `"reconnected": true` |

`rs stream play` needs `--frames` or `--duration` under `--json`; without them it runs until
interrupted and fails with exit code `2`. Under `--json` the live view is off, so stdout holds
only the summary.

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
| `6` | Invalid or unsupported stream profile (for `rs info`, one that matches no video profile; for `rs capture`, a stream or stream format it can't save in a file format asked for) |
| `7` | Invalid control value, a control that failed to write during `rs config restore`, or an `rs capture` output directory that isn't empty |
| `8` | Confirmation needed: several devices connected, add `--serial` or `--yes` |
| `9` | A stream in a bounded `rs stream play` or `rs capture` received no frames, or stopped sending them for 3 seconds |
| `10` | A control the sensor lists but can't read right now (e.g. a temperature while not streaming) |
| `130` | Interrupted (Ctrl+C) |
