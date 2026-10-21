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
A concrete way to open a stream: its resolution, frame rate and format, written
`depth-640x480-30-z16`.
_Avoid_: Mode, stream config

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

## Runs

**Bounded run**:
A streaming command limited by a frame count or a duration, which ends on its own and reports a
summary.
_Avoid_: Snapshot

**Capture**:
A bounded run that saves its framesets to files on disk after a warm-up, so they can be opened
afterwards.
_Avoid_: Snapshot, grab, record (a recording is a `.bag` file)

**Hardware reset**:
Power-cycling a device so it re-enumerates (`rs reset`).
_Avoid_: Reset (alone, when control restore is meant)

**Control restore**:
Setting controls back to their defaults (`rs config restore`), without touching the device's
connection.
_Avoid_: Reset, restore-defaults
