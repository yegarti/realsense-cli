# realsense-cli

`rs`, a command line for Intel RealSense depth cameras, built for humans at a terminal and usable
by agents through its JSON output.

## Camera

**Device**:
One connected RealSense camera, identified by its serial number.
_Avoid_: Camera (in code and docs), unit

**Sensor**:
A part of a device that produces streams and owns controls, e.g. the Stereo Module or RGB Camera.
Referred to by its full name or an alias (`depth`, `color`, `motion`).

**Stream**:
One kind of data a sensor produces, e.g. depth, infrared, color, gyro.

**Profile**:
A concrete way to open a stream: its resolution, frame rate and stream format, written
`depth-640x480-30-z16`.
_Avoid_: Mode, stream config

**Stream format**:
How a device packs a stream's frames, e.g. Z16 depth or RGB8 color; part of a profile.
_Avoid_: Format (alone), pixel format

**Camera info**:
The fixed details a device reports about itself, e.g. its name, serial number, firmware
version and product line (`rs info`).
_Avoid_: Device info (that is `rs list`'s short summary)

**Calibration**:
A device's intrinsics (each video profile's principal point, focal length and lens distortion)
and extrinsics (the rotation and translation from one stream's coordinate frame to another's).

**Control**:
A setting on a sensor with a range, step and default, e.g. exposure or laser power.
_Avoid_: Option (the SDK's word), setting, parameter

**Visual preset**:
A named built-in tuning of the depth sensor, e.g. High Accuracy, set as the `visual_preset`
control.
_Avoid_: Preset (alone)

**Advanced mode**:
A device state that unlocks preset files and advanced controls. It persists across power
cycles, and turning it on or off resets the device.

**Advanced control**:
One depth tuning value in an advanced-mode group, e.g. the RSM group's diff threshold. It has a
minimum and maximum (sometimes neither) but no step or default, and it can only be read or set
in advanced mode. It is not a control.
_Avoid_: Advanced parameter, advanced option

**Preset file**:
An advanced-mode JSON file holding the values of many advanced controls and depth controls at
once, loaded into or saved from a device.
_Avoid_: Preset (alone), config file

**Preset key**:
One entry in a preset file, named as the SDK writes it, e.g. `controls-laserpower`. Some set a
control, others an advanced control.
_Avoid_: Parameter

## Runs

**Bounded run**:
A streaming command limited by a frame count or a duration, which ends on its own and reports a
summary.
_Avoid_: Snapshot

**Capture**:
A bounded run that saves its framesets to files on disk after a warm-up, so they can be opened
afterwards.
_Avoid_: Snapshot, grab, record (a recording is a `.db3` file)

**Recording**:
A file holding a run's frames together with the device's details (camera info, profiles,
calibration and control values), in the rosbag2 `.db3` format (`rs bag`).
_Avoid_: Bag file (alone), `.bag` file, capture

**File format**:
How a capture writes each frame to disk: PNG to look at, NPY to load as an array, or raw
bytes exactly as the device sent them.
_Avoid_: Format (alone), output format

**Depth query**:
A short run that reports the depth at one pixel or over a region, combined from a few frames
after a warm-up (`rs depth`).
_Avoid_: Depth measurement, depth probe

**Region**:
A rectangle of pixels a depth query reports on, given by its top-left corner, width and
height. ROI is its short form on the command line.
_Avoid_: ROI (in prose), area, window

**Fill rate**:
The share of a region's pixels that have depth.
_Avoid_: Density, coverage, valid ratio

**Hardware reset**:
Power-cycling a device so it re-enumerates (`rs reset`).
_Avoid_: Reset (alone, when control restore is meant)

**Control restore**:
Setting controls back to their defaults (`rs config restore`), without touching the device's
connection.
_Avoid_: Reset, restore-defaults
