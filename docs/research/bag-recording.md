# Recording with pyrealsense2 2.59.1, including from the mock device

Research for [#35](https://github.com/yegarti/realsense-cli/issues/35), feeding the grilling
ticket [#45](https://github.com/yegarti/realsense-cli/issues/45) (`rs bag record`).

Sources are librealsense at tag `v2.59.1` (the version the repo's pyrealsense2 wheel is
built from). `SRC` below means `https://github.com/IntelRealSense/librealsense/blob/v2.59.1/`.
Every **Verified** line was run with throwaway scripts outside the repo:

- on the repo's simulated D435 (`realsense_cli/driver/software.py`) through the repo's
  `Realsense` driver;
- on a real **D435I** (S/N 918512073869, FW 5.17.3.10, attached over USB/IP; only Stereo
  Module and RGB Camera are exposed, no Motion Module). The one option changed on it
  (`laser_power`) was restored to its original value.

## Answer in brief

1. **pyrealsense2 2.59.1 cannot write a ROS1 `.bag`.** Every recording is a ROS2 rosbag2
   SQLite file, and the output path **must end in `.db3`**. Any other extension raises
   `RuntimeError: Output file must have .db3 extension: '<path>'`. It can still *play back*
   legacy `.bag` files, and `rs.context().convert_bag_to_db3(bag, db3)` converts them.
2. **Two ways to record.** `rs.recorder(path, device[, compress])` wraps a device. A
   pipeline started with `cfg.enable_record_to_file(path)` builds that same recorder
   internally. Both write identical content.
3. **The mock records.** An `rs.recorder` wrapping the simulated D435's
   `rs.software_device` produces a valid `.db3`. The SDK's playback device, stdlib `sqlite3`
   and `rosbags.rosbag2.Reader` all read it back. Streaming can stay on the driver's
   own (live) sensors, so `play(pipeline=False)` works unchanged.
4. **Ending a recording.** Stop streaming, then release the recorder (or the pipeline
   profile); the destructor flushes the write queue. Each message is committed to SQLite as
   it is written. Ctrl-C, interpreter exit without cleanup, and even SIGKILL all left
   readable files in testing.

## 1. File format: `.db3` only

- The CMake option `BUILD_ROSBAG2` is `ON` by default: "Build and use rosbag2 recording
  system ... temporary flag, should be removed when deprecated ROSBAG1 recording system is
  removed" (`SRC/CMake/lrs_options.cmake#L88`).
- With `BUILD_ROSBAG2`, `create_writer_for_file()` always returns a `ros2_writer`. The ROS1
  `ros_writer` is used only without the flag (`SRC/src/media/ros_factory.cpp#L84-L96`). The
  reader still dispatches on the extension: `.db3` goes to ROS2, anything else to ROS1.
- `ros2_writer` rejects any path not ending in `.db3`
  (`SRC/src/media/ros2/ros2_writer.cpp#L38-L43`).
- Official doc: "The SDK records a single device to a single `.db3` file using the ROS2
  rosbag2 storage format (SQLite-based). The output file path must end with the `.db3`
  extension" (`SRC/doc/record-and-playback.md`).
- History: the change landed in **2.58.1** ("Native ROS2 Record and Playback", PR #14882
  "Upgrade record-playback system to ROS2 based"), per the librealsense Release-Notes wiki.
- **Verified:** `rs.recorder("x.bag", dev)` and `rs.recorder("noext", dev)` both raise
  `RuntimeError: Output file must have .db3 extension`.
- **Verified:** the output is a single bare `.db3` file with no `metadata.yaml` beside it.
  `ros2_writer` drives `SqliteStorage` directly, not the rosbag2 `Writer`.
  `rosbags.rosbag2.Reader(path)` (rosbags 0.11.8, already a dependency) opens the bare file
  and reports `duration`, `message_count` and per-connection `msgcount`.
- **Verified:** today's `rs bag info` uses `rosbags.rosbag1`. On a `.db3` it fails with
  `Error: UnicodeDecodeError: 'utf-8' codec can't decode byte 0x86 ...`.

## 2. The two APIs

### `rs.recorder(path, device)` / `rs.recorder(path, device, compress)`

- Python binding (`SRC/wrappers/python/pyrs_record_playback.cpp#L38-L42`): two
  constructors, plus `pause()` and `resume()`. `rs.recorder` is an `rs.device`. The C++
  `filename()` getter is **not** bound.
- `rs2_create_record_device` uses the device's `compress_while_record()` as the default
  (`SRC/src/rs.cpp#L2384-L2401`).
- A recorder is a `record_device` holding one `record_sensor` per live sensor
  (`SRC/src/media/record/record_device.cpp#L14-L62`).
- Each `record_sensor` hooks the **live** sensor through
  `register_before_streaming_changes_callback`
  (`SRC/src/media/record/record_sensor.cpp#L54`). From then on, whenever that sensor starts
  streaming, its frame callback is wrapped and every frame is cloned into the recording.
  So streaming either `recorder.sensors` or the original device's sensors gets recorded.
  **Verified** both ways on the mock, and on the D435I with the live sensor API.
- **Verified pitfall:** a recorder's sensors return an **empty**
  `get_supported_options()`, while `supports()`, `get_option()` and `set_option()` still
  forward. `record_sensor` inherits an empty `options_container`
  (`SRC/src/media/record/record_sensor.h#L21`). The driver's `_get_option()` lists
  supported options, so a `Realsense(devices=[recorder])` driver raises
  `UnknownControl ... Valid controls: none`. Keep the driver on the live device and hold
  the recorder beside it.
- **Verified pitfall:** wrapping a context device in `rs.recorder` and then streaming that
  camera through a *separate* `rs.pipeline` records nothing: the file holds only
  `/file_version`. The pipeline resolves its own device instance, and the recorder's hooks
  never see it. With the pipeline, use `enable_record_to_file`.

### `rs.config.enable_record_to_file(path)` on the pipeline

- It sets `record_output` on the config. Combining it with `enable_device_from_file`
  raises "Configuring both device from file, and record to file is unsupported"
  (`SRC/src/pipeline/config.cpp#L58-L67`).
- On `start()`, the resolved pipeline `profile` wraps the device in a `record_device` with
  that device's default compression (`SRC/src/pipeline/profile.cpp#L17-L24`).
  `profile.get_device().is_recorder()` is `True` (**Verified** on the D435I).
- `pipeline.stop()` stops and closes the sensors and drops the pipeline's own profile
  reference (`SRC/src/pipeline/pipeline.cpp#L161-L187`). The writer lives as long as the
  `record_device`, so a Python `pipeline_profile` still in hand (the driver keeps
  `self._pipe_profile`) keeps the file handle open until it is released. **Verified** that
  this doesn't matter for content: all 392 messages were in the file right after
  `pipe.stop()`, with the profile still held.
- It can't reach the mock: the pipeline can't see an `rs.software_device` (see
  `CLAUDE.md`). Recording a playback device through the pipeline also fails: it aborts the
  process with `not_implemented_exception: playback_sensor::unregister_before_start_callback`.

### One code path for mock and hardware

`rs.recorder(path, driver._device)` plus `play(pipeline=False)` recorded both the mock and
the D435I (**Verified**). On hardware it gives up the pipeline's syncer, and frames
arrive per sensor, which is what the driver's sensor mode already does. The alternative is
two paths: `enable_record_to_file` for real devices, `rs.recorder` for injected ones.

## 3. What gets written

Recording is device-level: device info, sensor info, stream profiles, options and frames
(`SRC/doc/record-and-playback.md`, "Recording"). Topic layout is `/device_0/sensor_<i>/<Stream>_<idx>/...`.
Here is what a 10-frame depth+color recording of the mock contained (**Verified**, 36 topics,
91 messages):

| Topic | Type | Count |
|---|---|---|
| `/file_version` | `std_msgs/UInt32` | 1, written when the recorder is constructed |
| `/device_0/info`, `/device_0/sensor_N/info` | `std_msgs/String` | 1 each: camera info and sensor name |
| `/device_0/sensor_N/option/<Name>/value` (+ `/description`) | `std_msgs/String` | 1 per option at start, plus one per change (below) |
| `.../<Stream>_<i>/info`, `.../<Stream>_<i>/camera_info` | `std_msgs/String` | 1 per started stream: profile and intrinsics |
| `.../<Stream>_<i>/image/data` (uncompressed) or `.../image/data/compressed`, `.../image/data/compressedDepth` | `sensor_msgs/Image` / `sensor_msgs/CompressedImage` | 1 per frame |
| `.../<Stream>_<i>/image/camera_info` | `sensor_msgs/CameraInfo` | 1 per frame |
| `.../<Stream>_<i>/image/metadata` | `std_msgs/String` | 1 per frame: frame metadata as `key=value;` |
| `.../<Stream>_<i>/tf/ref_N`, `/tf_static` | `String`, `tf2_msgs/TFMessage` | extrinsics, once per stream |
| `.../Gyro_0/imu/data`, `.../Accel_0/imu/data`, `.../imu_intrinsic` | `sensor_msgs/Imu`, `String` | 1 per motion frame (**Verified** on the mock) |

- **Only started streams are written** (`wrap_streams()` snapshots active profiles,
  `SRC/src/media/record/record_sensor.cpp#L411`). A sensor that never streams still gets
  its info and option snapshots.
- **The header is written on the first frame**, not at construction
  (`std::call_once(m_first_frame_flag, write_header)`,
  `SRC/src/media/record/record_device.cpp#L162`). Option values in the header are therefore
  those at first-frame time. **Verified:** `laser_power` set after the recorder was created,
  but before streaming, is the value recorded.
- **Option changes during recording**: live sensor options are hooked with
  `enable_recording` (`SRC/src/media/record/record_sensor.cpp#L353`). An option records a
  change only if its `set()` calls the recording function. UVC options do
  (`SRC/src/platform/uvc-option.cpp#L73-L85`); the software device's `float_option::set`
  does not (`SRC/src/option.cpp#L75-L81`).
  - **Verified on the D435I:** `laser_power` 150 → 60 → 150 mid-run gave three
    `Laser_Power/value` messages.
  - **Verified on the mock:** a mid-run change is not recorded.
- **Message timestamps are recording time, not frame timestamps**: nanoseconds since the
  first frame, minus paused time (`get_capture_time()`,
  `SRC/src/media/record/record_device.cpp#L113`). The mock pushes 10 frames in about 10 ms,
  so its recording "duration" is about 10 ms, whatever the pushed frame timestamps say. A
  recording's duration is wall-clock time between first and last frame.

### Compression

- The default is `device::compress_while_record()`, which is `true`
  (`SRC/src/device.h#L85`). The D435i, D436, D405 and D455 override it to `false`
  (`SRC/src/ds/d400/d400-factory.cpp#L896`, `#L943`, `#L1029`, `#L1108`). The plain D435
  and the software device inherit `true`.
- Compressed recordings store images as PNG (lossless) `CompressedImage`, with zstd
  fallback for formats PNG can't hold, so they stay playable by stock ROS2
  (`SRC/src/media/ros2/ros2_writer.cpp`, `SRC/doc/record-and-playback.md`).
- **Verified (mock, 10 depth+color frames at 640x480):** 102 KB compressed against
  15.4 MB uncompressed. The mock's ramp pixels compress unrealistically well.
- **Verified (D435I, about 2 s depth+color at 640x480@30, default `false`):** 75 MB of raw
  `sensor_msgs/Image`, about 37 MB/s.

## 4. Pause and resume

- `pause()` queues a flag flip on the write thread and flushes it. Frames queued afterwards
  are dropped when their write runs. `resume()` adds the paused interval to a running total
  that is subtracted from capture time, so the recording has no gap
  (`SRC/src/media/record/record_device.cpp#L379-L440`).
- Streaming is unaffected; frames still reach the user's callback.
- **Verified (mock):** pausing for 3 of 10 pushed frames recorded 7 per stream. Playback
  returned 7.

## 5. Ending a recording, and what a killed process leaves

- **Clean end:** stop the sensors, or `pipeline.stop()`, then drop the last reference to
  the recorder or pipeline profile. `~record_device()` disables recording on every sensor,
  flushes the write thread (logging an error on timeout), and stops it
  (`SRC/src/media/record/record_device.cpp#L64-L77`). **Verified:** deleting the recorder
  while the sensor was still streaming also produced a complete, readable file.
- **Storage is crash-tolerant by construction.** Single-message writes don't open an
  explicit transaction, so each frame is its own autocommitted SQLite insert
  (`.../rosbag2_storage_default_plugins/sqlite/sqlite_storage.cpp#L139-L153`). The
  embedded wrapper sets `journal_mode = MEMORY` and `synchronous = OFF` for throughput. Its
  comment warns that a crash *mid-write* or a power loss "may" corrupt the file
  (`.../sqlite/sqlite_wrapper.cpp#L60-L78`).
- **Verified (mock):**
  - SIGKILL mid-recording: `integrity_check` returned `ok`, all 5 pushed frames were
    present, and the SDK played the file back.
  - Ctrl-C (`KeyboardInterrupt`, no cleanup) and `sys.exit()` with the recorder still
    alive: both left complete, playable files.
  - Frames still in the write queue at SIGKILL time are lost. Power loss can't be tested
    here.
- **No back-pressure:** the write queue is effectively unbounded. The dispatcher is created
  with `max()` capacity, and the `MAX_CACHED_DATA_SIZE` check never fires because the size
  accounting is commented out as `TODO: restore` (`record_device.cpp#L16`, `#L143-L150`).
  If the disk is slower than the stream, memory grows instead of frames being dropped.
- **Overwrite is silent:** `ros2_writer` deletes an existing file at the path before
  opening (`SRC/src/media/ros2/ros2_writer.cpp#L53-L62`). **Verified:** an existing file is
  replaced without error.
- **Missing directory:** `RuntimeError: Failed to setup storage. Error: Could not read-write
  open database. SQLite error (14): unable to open database file` (**Verified**).
- **The file exists from construction.** It is 16 KB, holding `/file_version` only, before
  any frame arrives (**Verified**).
- **Verified (mock): a recording with zero frames hangs SDK playback.** If no frame ever
  arrived, the file has just `/file_version`, or that plus stream info when streams opened
  without frames. `rs.context().load_device()` on it hung for over 15 s. sqlite and rosbags
  read it fine.

## 6. Mock-driver behaviour, summarized

| Behaviour | Mock (`software_device`) | Real D400 |
|---|---|---|
| `rs.recorder` wrapping it | works | works |
| `enable_record_to_file` (pipeline) | unreachable (pipeline can't see it) | works |
| `rs.recorder` + `play(pipeline=False)` | works | works (**Verified** on the D435I) |
| Default compression | on (PNG) | off on D435i, D455, D405, D436; on for the plain D435 |
| Option change mid-run recorded | no (`float_option`) | yes |
| Read back by SDK playback, sqlite, `rosbags.rosbag2` | yes | yes |
| Recording duration | wall-clock push spacing (ms when pushed in a tight loop) | wall-clock |

## Open points this surfaced

- **Naming:** the command and the ticket say "bag", but the file is a `.db3`. Settle what
  `rs bag record` writes (only `.db3` is possible), and whether a `.bag` path is an
  `InvalidValue` or is rewritten.
- **`rs bag info` and `.db3`:** recordings made by this SDK version can't be read by today's
  `rs bag info` (rosbag1 only; it crashes with `UnicodeDecodeError`). This touches #37
  (what a `.bag` stores) and #44 (`rs bag info`). `rosbags.rosbag2.Reader` reads a bare
  `.db3`.
- **Zero-frame runs** leave a file that hangs SDK playback, so `rs bag record` probably
  needs to treat "no frames" as `NoFrames` and decide whether to delete the file.
