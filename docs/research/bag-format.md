# What a RealSense recording stores about profiles and camera info, and reading it with rosbags

Research for [#37](https://github.com/yegarti/realsense-cli/issues/37), feeding the grilling ticket
[#44](https://github.com/yegarti/realsense-cli/issues/44) ("rs bag info: showing stored profiles
and camera info"). Researched 2026-10-22 against librealsense **v2.59.1** (the pyrealsense2 this
repo pins, `2.59.1.11053`) and rosbags **0.11.8** (the version in `uv.lock`).

Source links point at the `v2.59.1` tag of
[realsenseai/librealsense](https://github.com/realsenseai/librealsense) (the repo
`IntelRealSense/librealsense` redirects there) and the `v0.11.8` tag of
[ternaris/rosbags](https://gitlab.com/ternaris/rosbags).

## Answer in brief

- **A recording holds two kinds of data: a static header (camera info, sensor names, the profiles
  that were streaming, their intrinsics, the controls' values and descriptions, extrinsics) and
  per-frame data (images, IMU samples, per-frame metadata).** The static part is a handful of
  topics with one message each, written at the earliest timestamp of the file.
- **The stored profiles are only the profiles that were streaming during the recording, one per
  stream.** A recording does not hold the device's full profile list.
- **pyrealsense2 2.59.1 no longer writes ROS1 `.bag` files.** It records only ROS2 rosbag2 `.db3`
  (SQLite) files and refuses any other extension. It still *plays back* ROS1 `.bag` files. Both
  formats use the same topic tree, but the message types differ: `.bag` uses typed messages
  (`diagnostic_msgs/KeyValue`, `realsense_msgs/StreamInfo`, `sensor_msgs/CameraInfo`, ...), and
  `.db3` packs most of the static data into `std_msgs/String` `key=value;` strings.
- **rosbags reads both formats without a ROS install.** `rosbags.rosbag1.Reader` reads `.bag`;
  `rosbags.rosbag2.Reader` opens a bare `.db3` file (no `metadata.yaml` needed); `AnyReader`
  handles both. The one non-standard type, `realsense_msgs/StreamInfo` (and `ImuIntrinsic`) in
  `.bag` files, can be registered from the message definition the bag itself carries.
- **`rs bag info` today** prints the path, the duration and a table of topics (name, message count,
  type). It reads only ROS1 `.bag` files: on a `.db3` file it fails with
  `Error: UnicodeDecodeError: 'utf-8' codec can't decode byte ...`.

## What `rs bag info` shows today

`realsense_cli/rs_bag_parser.py` opens the file with `rosbags.rosbag1.Reader` and keeps, per
connection, its topic, message type and message count, plus the bag's duration in seconds.
`realsense_cli/commands/bag.py` emits `{"path", "duration", "topics": [{"name", "messages",
"type"}]}` (sorted by message count, then name), and `printer.list_bag_data` renders a "Data"
table of topics and a small Bag/Duration table. No message is ever deserialized, so none of the
stored profiles, camera info or control values reach the user except as topic names.

Run against the two sample files below:

- `single_depth_color_640x480.bag` (ROS1): works; 70 topics, duration `0.1679347`.
- `d435.db3` (recorded with pyrealsense2 2.59.1): `Error: UnicodeDecodeError: 'utf-8' codec can't
  decode byte 0xb6 in position 27: invalid start byte`. The ROS1 reader is fed an SQLite file.

## Which format the pinned SDK records

librealsense picks the writer in `create_writer_for_file`: when built with `BUILD_ROSBAG2`, it
always creates a `ros2_writer`, whatever the file name
([`ros_factory.cpp` L84-95](https://github.com/realsenseai/librealsense/blob/v2.59.1/src/media/ros_factory.cpp#L84-L95)),
and `ros2_writer` throws `Output file must have .db3 extension` for any other suffix
([`ros2_writer.cpp` L38-41](https://github.com/realsenseai/librealsense/blob/v2.59.1/src/media/ros2/ros2_writer.cpp#L38-L41)).
The reader is chosen by suffix: `.db3` opens with `ros2_reader` (or `ros2_native_reader` for a
stock ROS2 bag without `/file_version`), anything else with the ROS1 `ros_reader`
([`ros_factory.cpp` L37-82](https://github.com/realsenseai/librealsense/blob/v2.59.1/src/media/ros_factory.cpp#L37-L82)).

The current docs say the same: "The SDK records a single device to a single `.db3` file using the
ROS2 rosbag2 storage format (SQLite-based). The output file path must end with the `.db3`
extension", and the ROS1 format is now "legacy"
([`doc/record-and-playback.md` L9-15](https://github.com/realsenseai/librealsense/blob/v2.59.1/doc/record-and-playback.md#L9-L15)).
Old `.bag` files convert with `rs-convert -i in.bag -D out.db3` or
`rs.context().convert_bag_to_db3(in, out)`
([L153-174](https://github.com/realsenseai/librealsense/blob/v2.59.1/doc/record-and-playback.md#L153-L174)).

Verified: the pyrealsense2 wheel in this repo has `rs.context.convert_bag_to_db3` (so it is built
with `BUILD_ROSBAG2`), and `rs.recorder("x.bag", dev)` raises
`RuntimeError: Output file must have .db3 extension`, while `rs.recorder("x.db3", dev)` works.

## Topic tree

Both formats name topics the same way. `<stream>` is `rs2_stream_to_string` plus the stream
index, e.g. `Depth_0`, `Color_0`, `Infrared_1`, `Gyro_0`; `device_0` is always device 0 (one
device per file); `sensor_N` is the sensor's index on the device
([`ros_file_format.h` L173-269, L350-360](https://github.com/realsenseai/librealsense/blob/v2.59.1/src/media/ros/ros_file_format.h#L173-L269);
ROS2 equivalents in
[`ros2_file_format.h` L92-186](https://github.com/realsenseai/librealsense/blob/v2.59.1/src/media/ros2/ros2_file_format.h#L92-L186)).

Static (header) topics, one message each unless noted:

| What | Topic | ROS1 `.bag` type | ROS2 `.db3` type and payload |
|---|---|---|---|
| File format version | `/file_version` | `std_msgs/UInt32` | `std_msgs/msg/UInt32` |
| Camera info | `/device_0/info` | `diagnostic_msgs/KeyValue`, **one message per field** | `std_msgs/msg/String`, one message `Name=...;Serial Number=...;...` |
| Sensor name | `/device_0/sensor_N/info` | `diagnostic_msgs/KeyValue` (`Name`) | `std_msgs/msg/String` `Name=Stereo Module` |
| Profile: format, fps | `/device_0/sensor_N/<stream>/info` | `realsense_msgs/StreamInfo` (`fps`, `encoding`, `is_recommended`) | `std_msgs/msg/String` `encoding=Z16;fps=30` |
| Video profile: resolution, intrinsics | `.../<stream>/info/camera_info` (`.bag`), `.../<stream>/camera_info` (`.db3`) | `sensor_msgs/CameraInfo` (`width`, `height`, `K`, `D`, `distortion_model`) | `std_msgs/msg/String` `width=640;height=480;fx=...;ppx=...;fy=...;ppy=...;model=Brown Conrady;coeffs=0,0,0,0,0` |
| Motion profile: IMU intrinsics | `.../<stream>/imu_intrinsic` | `realsense_msgs/ImuIntrinsic` | `std_msgs/msg/String` `data=...;bias_variances=...;noise_variances=...` |
| Control value | `/device_0/sensor_N/option/<name>/value` | `std_msgs/Float32` | `std_msgs/msg/String` `8500.000000` |
| Control description | `/device_0/sensor_N/option/<name>/description` | `std_msgs/String` | `std_msgs/msg/String` |
| Extrinsics | `.../<stream>/tf/<ref>` (`.bag`), `.../<stream>/tf/ref_<ref>` (`.db3`) | `geometry_msgs/Transform` | `std_msgs/msg/String` `rotation=<9 floats>;translation=<3 floats>`, plus a standard `/tf_static` `tf2_msgs/msg/TFMessage` |
| Recommended post-processing | `/device_0/sensor_N/post_processing` | `std_msgs/String` (file version 4+) | `std_msgs/msg/String` |

Per-frame topics: `.../<stream>/image/data` (`sensor_msgs/Image`; in a compressed `.db3`,
`image/data/compressed` or `image/data/compressedDepth` `sensor_msgs/CompressedImage` PNG),
`.../<stream>/image/metadata` (per-frame metadata: `KeyValue` messages in `.bag`, one
`key=value;` String per frame in `.db3`), `.../<stream>/imu/data` (`sensor_msgs/Imu`), pose
topics, and in `.db3` also `.../<stream>/image/camera_info` (`sensor_msgs/CameraInfo` per frame,
for stock ROS2 tools). Notifications go to `/device_0/sensor_N/notification/<category>`
([legacy doc topic table L163-323](https://github.com/realsenseai/librealsense/blob/v2.59.1/doc/record-and-playback-legacy-ros1.md#L163-L323);
[ROS2 topic table L126-141](https://github.com/realsenseai/librealsense/blob/v2.59.1/doc/record-and-playback.md#L126-L141)).

Details from the source and the sample files:

- **Camera info keys** are `rs2_camera_info_to_string` names (`Name`, `Serial Number`,
  `Firmware Version`, `Product Id`, `Usb Type Descriptor`, ...), one per field the device
  supports ([`ros_writer.cpp` L488-501](https://github.com/realsenseai/librealsense/blob/v2.59.1/src/media/ros/ros_writer.cpp#L488-L501);
  [`ros2_writer.cpp` L807-824](https://github.com/realsenseai/librealsense/blob/v2.59.1/src/media/ros2/ros2_writer.cpp#L807-L824)).
  In `.db3` they are joined with `;` and nothing escapes a `;` or `=` inside a value.
- **Profile encoding** differs between formats. The ROS1 writer maps some formats to ROS image
  encodings (`Z16`→`mono16`, `Y8`→`8UC1`, `Y16`→`16UC1`, `RAW8`→`mono8`, `UYVY`→`yuv422`,
  `RGB8`→`rgb8`, ...) and writes the `rs2_format` name for the rest (e.g. `YUYV`,
  `MOTION_XYZ32F`); the reader maps them back and otherwise parses the upper-cased string as an
  `rs2_format`
  ([`ros_common.h` L36-111](https://github.com/realsenseai/librealsense/blob/v2.59.1/src/media/ros_common.h#L36-L111)).
  The ROS2 writer writes the `rs2_format` name directly (`Z16`, `RGB8`)
  ([`ros2_writer.cpp` L640-688](https://github.com/realsenseai/librealsense/blob/v2.59.1/src/media/ros2/ros2_writer.cpp#L640-L688)).
- **Resolution lives in the camera_info topic**, not in StreamInfo: a video profile is StreamInfo
  (format, fps) plus camera_info (width, height, intrinsics); a motion profile is StreamInfo plus
  imu_intrinsic ([`ros_reader.cpp` L1453-1520](https://github.com/realsenseai/librealsense/blob/v2.59.1/src/media/ros/ros_reader.cpp#L1453-L1520)).
  The `.bag` CameraInfo `distortion_model` holds the librealsense name (`Brown Conrady`), not a
  ROS one. The `.db3` per-frame `sensor_msgs/CameraInfo` says `plumb_bob`, so read the String
  topic for the real model.
- **Only the streams that were streaming are stored.** `record_sensor::wrap_streams` snapshots
  `get_active_streams()` ([`record_sensor.cpp` L411-438](https://github.com/realsenseai/librealsense/blob/v2.59.1/src/media/record/record_sensor.cpp#L411-L438)),
  and there is one StreamInfo topic per stream. A playback device built from the file lists
  exactly those profiles (verified: one profile per recorded stream).
- **Extrinsics are per stream, to a reference frame**, not between pairs of streams. They are
  written when the stream's first frame arrives, so a stream that produced no frames has none
  ([`ros_writer.cpp` L130-143](https://github.com/realsenseai/librealsense/blob/v2.59.1/src/media/ros/ros_writer.cpp#L130-L143);
  [`ros2_writer.cpp` L496-551](https://github.com/realsenseai/librealsense/blob/v2.59.1/src/media/ros2/ros2_writer.cpp#L496-L551)).
  The stored transform maps reference → stream; stream-to-stream extrinsics come from
  composing two of them (the playback device does this: its Depth→Color translation matched the
  difference of the two stored transforms). The `/tf_static` copy in `.db3` is inverted
  (stream → reference) for ROS tools.
- **Control topic names** come from `rs2_option_to_string`. The v2.59.1 writers replace spaces
  with `_` (`Enable_Auto_Exposure`)
  ([`ros_file_format.h` L205-222](https://github.com/realsenseai/librealsense/blob/v2.59.1/src/media/ros/ros_file_format.h#L205-L222)),
  while the 2018 sample bag has spaces (`Enable Auto Exposure`). A control's `value` topic can
  hold more than one message when its value changed during recording; the first message is the
  value at the start.
- **File versions.** `/file_version` is 4 for the current writers
  (`ROS_FILE_WITH_RECOMMENDED_PROCESSING_BLOCKS`), and the reader accepts 2 and up
  ([`ros_common.h` L142-150](https://github.com/realsenseai/librealsense/blob/v2.59.1/src/media/ros_common.h#L142-L150)).
  The legacy doc still says 3, the version before `post_processing` was added
  ([L479-493](https://github.com/realsenseai/librealsense/blob/v2.59.1/doc/record-and-playback-legacy-ros1.md#L479-L493)).
  Version 1 is a much older layout (`/camera/rs_stream_info/...`,
  `realsense_legacy_msgs/*`) that the reader handles separately
  ([`ros_reader.cpp` L1383-1430](https://github.com/realsenseai/librealsense/blob/v2.59.1/src/media/ros/ros_reader.cpp#L1383-L1430)).
- **The doc and source disagree on one topic.** The legacy doc lists IMU intrinsics at
  `.../<stream>/info/imu_intrinsic`; the source writes `.../<stream>/imu_intrinsic`
  ([`ros_file_format.h` L193-196](https://github.com/realsenseai/librealsense/blob/v2.59.1/src/media/ros/ros_file_format.h#L193-L196)).
  Trust the source.

## Reading it with rosbags

All of the above reads without ROS or librealsense (verified on both sample files):

- **ROS1 `.bag`**: `rosbags.rosbag1.Reader(path)`, which the repo already uses. Deserialize with
  `get_typestore(Stores.ROS1_NOETIC).deserialize_ros1(raw, conn.msgtype)`. rosbags renames
  message types to their ROS2 form (`realsense_msgs/msg/StreamInfo`,
  `diagnostic_msgs/msg/KeyValue`) ([rosbag1 docs](https://ternaris.gitlab.io/rosbags/topics/rosbag1.html)).
  `realsense_msgs/msg/StreamInfo` and `ImuIntrinsic` are not in the stock typestore. Register them
  from the definition the bag carries:
  `typestore.register(get_types_from_msg(conn.msgdef.data, conn.msgtype))`. `AnyReader` does that
  automatically for every ROS1 connection
  ([`highlevel/anyreader.py` L135-165](https://gitlab.com/ternaris/rosbags/-/blob/v0.11.8/src/rosbags/highlevel/anyreader.py#L135-165)).
- **ROS2 `.db3`**: `rosbags.rosbag2.Reader(path)` accepts a bare `.db3` file as well as a bag
  directory. It picks the plugin by suffix (`'.db3': Sqlite3Reader`), and only the directory form
  needs `metadata.yaml`
  ([`rosbag2/reader.py` L317-353](https://gitlab.com/ternaris/rosbags/-/blob/v0.11.8/src/rosbags/rosbag2/reader.py#L317-353)).
  librealsense writes no `metadata.yaml` (the file has only the `topics` and `messages` tables),
  and the reader still reports connections, counts and duration. Every type it uses is standard
  (`std_msgs`, `sensor_msgs`, `tf2_msgs`), so `get_typestore(Stores.ROS2_HUMBLE)
  .deserialize_cdr(raw, msgtype)` decodes them all. `AnyReader` opens it too, but only when given
  `default_typestore=` (otherwise `AnyReaderError: Bag contains no type definitions`).
- **One reader for both**: `AnyReader([path], default_typestore=get_typestore(Stores.ROS2_HUMBLE))`
  opened both sample files; `reader.is2` tells them apart. Topic names line up between formats
  except camera_info (`info/camera_info` vs `camera_info`) and extrinsics (`tf/0` vs
  `tf/ref_0`). Payloads need two decoders: typed messages for `.bag`, and `key=value;` string
  parsing for `.db3`.

### The other way: a pyrealsense2 playback device

`rs.context().load_device(path)` opens either format (all file versions) as a playback device.
Its camera info, sensors, profiles (with intrinsics), control values and stream-to-stream
extrinsics come back through the normal SDK calls, the same ones `rs info` and `rs config list`
use. Verified on both sample files. The cost is that `rs bag` would create an `rs.context` and
import pyrealsense2, which CLAUDE.md currently rules out for `bag`.

## Sample files used

- `single_depth_color_640x480.bag`: ROS1, `/file_version` 3, a D435 with Depth (Z16, 6 fps) and
  Color (RGB8, 6 fps) at 640x480, 9 camera info fields, 13 + 15 controls. From librealsense's
  unit-test resources
  ([`unit-tests/resources/single_depth_color_640x480.bag`](https://github.com/realsenseai/librealsense/blob/v2.59.1/unit-tests/resources/single_depth_color_640x480.bag),
  1 MB). The sample recordings in `doc/sample-data.md` are 170-420 MB `.bag` files.
- `d435.db3`: recorded for this research with `rs.recorder("d435.db3", d435().device)` around the
  repo's simulated D435 (`realsense_cli/driver/software.py`), streaming the default Depth, Color,
  Gyro and Accel profiles for 10 pushed frames. This produced 44 topics, `/file_version` 4, and
  PNG-compressed image topics (the Python recorder compressed by default). Gyro and Accel have no
  `tf` topic because the simulated device registers no extrinsics for them.

## Open points

- `rs bag info` cannot read anything the pinned SDK records, since pyrealsense2 2.59.1 writes
  only `.db3`. Supporting `.db3` (e.g. `rosbags.rosbag2.Reader` or `AnyReader`) is a separate
  decision from showing profiles and camera info, though #44 will run into it.
- The command and README call the file a "ROS bag"/`.bag`, and the glossary says "a recording is a
  `.bag` file". With `.db3` the default, both need revisiting.
- `.db3` string payloads join camera info and per-frame metadata with `;` without escaping. A
  value containing `;` or `=` would split wrongly. No sample showed one, but serials, ports and
  firmware strings come from the device.
