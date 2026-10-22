# Aligning depth to color on framesets from the mock device

Research for [#36](https://github.com/yegarti/realsense-cli/issues/36), feeding
[#42 `rs depth`](https://github.com/yegarti/realsense-cli/issues/42). Sources are librealsense
**v2.59.1** (the pyrealsense2 version this repo locks), linked as `L<n>` to the tagged source.
"Verified" means run against the repo's simulated D435 (`driver/software.py`) with
pyrealsense2 2.59.1 on Linux x86-64. **No camera was connected**: claims about real hardware come
from source only.

## Answer

- **`rs.align` works on the mock, but not on what the driver produces today.** The sensor path
  starts every sensor into one `rs.frame_queue`, so frames come out one at a time, never as a
  frameset (verified: `is_frameset()` is false, and `wait_for_frameset()` returns
  `{'Depth': ...}`, then `{'Color': ...}`). `align.process()` only accepts a `composite_frame`. It
  raises `TypeError` on a lone frame (verified).
- **What it needs: start the depth and color sensors into an `rs.syncer` instead of the queue.**
  `sensor.start(syncer)` is a first-class pyrealsense2 overload. `syncer.wait_for_frames()` then
  returns depth+color framesets that `rs.align(rs.stream.color).process()` aligns (verified on
  the mock). This is the pattern librealsense's own
  [`align-with-software-device.py`][ex-sw] example uses, and the same syncer the pipeline runs
  internally.
- **Real hardware:** the pipeline path (`play()` default) already hands the driver framesets,
  because the pipeline routes frames through a syncer before the callback/queue
  ([pipeline.cpp L200-245][pipe]). `align` applies to those directly, as in the official
  [`align-depth2color.py`][ex-a]. Sensor API + syncer on a real D435 uses the device's own
  matcher ([d400-factory.cpp L1362-1366][d435m]), so it should behave like the pipeline. Not
  verified (no camera).
- **The driver drops the `rs.frameset` today.** `wait_for_frameset()` turns frames into
  `Frame` dicts, so alignment has to happen **inside the driver**, before that conversion, on both
  paths.
- **Single pixel without full alignment:** `rs.rs2_project_color_pixel_to_depth_pixel` works on
  mock frames (verified). It needs the raw depth buffer, depth scale, a min/max search depth,
  both intrinsics and both extrinsics. It returns `[-1, -1]` when it finds no valid depth. For an
  ROI, full `align` is simpler and cheap (≈5.6 ms per 640x480 frame here).
- **Depth units:** the mock's depth scale is the Stereo Module's `depth_units` control (default
  0.001 m, settable). Frames are stamped with its value when pushed, and
  `depth_frame.get_distance()` / `get_units()` follow it (verified). On a real D400 it is the same
  `depth_units` option: 0.001 by default, 0.0001 on D405 ([d400-device.cpp L1073-1099][d400du]).

## 1. Why today's frames can't be aligned

`Realsense._stream_sensor()` opens each sensor and calls `rs_sensor.start(self._frame_queue)`.
A `frame_queue` stores single frames. Nothing groups depth with color, so `try_wait_for_frame`
yields one stream's frame at a time. The pipeline path differs. In `pipeline::on_start` /
`get_callback` ([pipeline.cpp L200-245][pipe]), every synced stream goes through a
`syncer_process_unit`, then an aggregator, then the user callback. So under
`pipeline.start(cfg, frame_queue)` the queue receives framesets, which is why
`wait_for_frameset()` checks `rs_frame.is_frameset()`.

`align` itself only processes a frameset that contains **both** a Z16 depth frame and a frame of
the target stream type ([align.cpp `should_process` L210-232][alsp]). The pyrealsense2 binding
types `process(frames: composite_frame)` (verified: a lone frame raises `TypeError`, and
`rs.composite_frame(lone_frame)` raises `RuntimeError: null pointer`).

## 2. Syncer on the sensor path (what it needs)

```python
sync = rs.syncer(queue_size)          # default queue_size=1
depth_sensor.open(depth_profile); color_sensor.open(color_profile)
depth_sensor.start(sync); color_sensor.start(sync)
fs = sync.wait_for_frames()           # or try_wait_for_frames(timeout_ms)
aligned = rs.align(rs.stream.color).process(fs)
depth = aligned.get_depth_frame()     # color resolution, color intrinsics
```

- **Matching.** The syncer asks the frame's device for a matcher
  ([sync.cpp L210-222][sync]). A `software_device` defaults to `RS2_MATCHER_DEFAULT`
  ([software-device.h L39][swdh], [software-device.cpp L69-81][swd]), which relates all its
  streams by timestamp ([matcher-factory.cpp L141-152][mf]). `SoftwareCamera.push_frames()` gives
  every active stream the same timestamp, so depth and color pair up. A real D435 also uses
  `RS2_MATCHER_DEFAULT` over depth/IR/IR/color ([d400-factory.cpp L1362-1366][d435m]).
- **Python only exposes the syncer as a sink.** `rs.syncer` has `wait_for_frame(s)`,
  `poll_for_frame(s)` and `try_wait_for_frame(s)`, but no `invoke`/`__call__` (verified with
  `dir()`). So you can't keep today's `frame_queue` and push its frames into a syncer
  afterwards. The sensors must be **started into** the syncer.
- **Queue size matters.** `syncer(int queue_size = 1)` ([rs_processing.hpp L705][rsp]) keeps only
  the newest frameset. After 4 pushes with the default, one frameset came out. With
  `rs.syncer(16)` all of them did (verified). Averaging N frames or counting frames in a bounded
  run needs a larger queue or a consumer that keeps up.
- **Warm-up singles.** The first syncer outputs were unmatched one-frame sets (`[Depth]`,
  `[Color]`, `[Gyro]` at ts 0), and matched sets only came after that (verified). Code must skip
  framesets that lack depth or color.
- **`align` silently passes through incomplete sets.** On a depth-only frameset,
  `align.process()` returned the depth frame unchanged, at depth intrinsics, with no error
  (verified, consistent with `should_process` returning false). Check
  `aligned.get_color_frame()` (or the depth frame's intrinsics) before trusting the result.
- **IMU in the same syncer.** With the Motion Module started into the same syncer, the mock
  grouped Gyro into the depth/color frameset, because the timestamps are identical (verified).
  Harmless for align, but `rs depth` has no reason to open the IMU.
- **What align reads from the device:** both profiles' intrinsics and the depth→color extrinsics
  ([align.cpp L107-109][alz]), plus depth units from the depth frame
  ([align.cpp L290][alpf]). The mock registers all of these (`D435_SENSORS` intrinsics,
  `D435_EXTRINSICS`). A software device with no registered extrinsics would make
  `get_extrinsics_to` fail.
- **Output.** The aligned depth frame keeps stream type Depth but takes the color profile's
  resolution and intrinsics ([align.cpp L197-201][alpr]). Verified: the aligned depth reported
  `Inverse Brown Conrady` color intrinsics. Its pixel (x, y) is the color pixel (x, y).
- **Holes.** `align_images` skips zero-depth pixels and depth pixels whose projected corners fall
  outside the color image. Where several depth pixels land on one color pixel, it keeps the
  nearest ([align.cpp L50-120][alimg]). Aligned depth therefore contains zeros that raw depth
  doesn't: on the mock, raw depth was 100 % non-zero and aligned depth 94 % (verified).
- **Cost.** About 5.6 ms per 640x480 depth+color align in this environment. The SSE
  implementation is picked at build time ([align.cpp L28-46][alc]).

## 3. Mapping one pixel/ROI without full alignment

Each function below is bound in pyrealsense2 2.59.1 (verified present):

- `rs2_project_color_pixel_to_depth_pixel(data, depth_scale, depth_min, depth_max, depth_intrin,
  color_intrin, color_to_depth, depth_to_color, from_pixel)`. Declared in
  [rsutil.h L32-40][rsu] and implemented in [rs.cpp L4602-4655][rscpp]. It deprojects the color
  pixel at `depth_min` and `depth_max`, projects both points into the depth image to get a
  line, walks that line, and keeps the depth pixel whose re-projection lands closest to the
  input. Zero-depth pixels are skipped. The Python wrapper returns `[-1, -1]` when nothing is
  found ([pyrsutil.cpp L41-55][pyu]). Note the argument order: **color_to_depth before
  depth_to_color**.
  - Verified on the mock: color (320, 240) → depth (318.5, 238.05). The distance there equalled
    the aligned frame's value at (320, 240). At (100, 100) and (600, 400) the two methods
    differed by about 1 m, because the mock's depth is a byte ramp whose neighbouring pixels
    differ wildly. Agreement on a real, smooth scene was not verified.
  - `depth_min`/`depth_max` bound the search. A pixel whose true depth lies outside that range
    maps to the wrong place.
- Depth pixel → color pixel (the inverse, exact):
  `rs2_deproject_pixel_to_point(depth_intrin, px, d)` →
  `rs2_transform_point_to_point(depth_to_color, pt)` →
  `rs2_project_point_to_pixel(color_intrin, pt)`. This is the per-pixel step `align` itself runs
  ([align.cpp L62-66][alimg]). Verified: depth (320, 240) → color (321.2, 243.1).
- Every intrinsic and extrinsic above is what `rs info` already reports (`Realsense.calibration()`).
  The point functions need `rs.intrinsics`/`rs.extrinsics` objects, which the driver gets from
  the profiles (`get_intrinsics()`, `get_extrinsics_to()`).
- For an ROI, per-pixel projection means one line search per pixel in Python. Aligning the frame
  and cropping the ROI is simpler, and with an SDK-native loop it is also cheaper.

## 4. Depth units

- **Mock.** A `software_sensor` counts as a depth sensor only if it has a `depth_units` option
  ([software-sensor.cpp L166-185][sws]). Its `get_depth_scale()` reads that option
  ([software-sensor.cpp L59][sws59]). The mock's Stereo Module adds `depth_units` as a writable
  control (0.00001–0.001, default 0.001). That makes `is_depth_sensor()` true and gives
  `Realsense.depth_scale()` 0.001 (verified).
- **Per frame.** A depth frame's units come from `software_video_frame.depth_units` when it is
  set. Otherwise they come from the sensor's `depth_units` value at push time
  ([software-sensor.cpp L334-342][swsdu]). `depth_frame::get_units()` returns them
  ([depth-frame.h L32][dfh]). Verified: after `set_option(depth_units, 0.0001)`, both
  `get_depth_scale()` and the frame's `get_units()` read 1e-4. `get_distance(320, 240)` went from
  33.152 m to 3.3152 m for the same raw value, 33152.
- **Real D400.** Same `depth_units` option. It is constant 0.001 (0.0001 on D405/D401) unless
  advanced mode is on with firmware ≥ 5.6.3, in which case it is writable
  ([d400-device.cpp L1073-1099][d400du]). `align` uses the depth **frame's** units
  ([align.cpp L290][alpf]), so `get_distance()` on the aligned frame is already in metres.
- Raw value 0 means "no depth" in both `align` and the pixel search. Code must treat it as
  invalid, not as 0 m.

## 5. Mock caveats for #42

- The mock pushes a byte ramp (`software.pixels()`). Read as Z16 that gives roughly 0.25–65 m,
  changing sharply between neighbours, and **no zero pixels** in raw depth. Tests of averaging,
  ROI statistics or invalid-pixel handling get no meaningful values from it. librealsense's
  example shows that `software_video_frame.pixels` accepts a numpy array
  ([align-with-software-device.py L225-239][ex-sw]), so a known depth pattern could be pushed
  instead.
- The mock's only color profiles are 640x480, the same as depth. A color resolution different
  from depth, where aligned size ≠ raw size, can't be exercised without new mock profiles.

## Sources

All of the sources below are librealsense v2.59.1 on GitHub. The key first-party examples:

- [wrappers/python/examples/align-with-software-device.py][ex-sw]: software device, then a syncer,
  then align. This is the mock's case.
- [wrappers/python/examples/align-depth2color.py][ex-a]: pipeline, then align. This is the real
  camera's case.

The throwaway probe scripts that produced the "verified" results lived outside the repo. They
drove `realsense_cli.driver.software.d435()` through `Realsense(devices=[...]).play()` and
through the raw sensors.

[ex-sw]: https://github.com/IntelRealSense/librealsense/blob/v2.59.1/wrappers/python/examples/align-with-software-device.py#L195-L270
[ex-a]: https://github.com/IntelRealSense/librealsense/blob/v2.59.1/wrappers/python/examples/align-depth2color.py#L53-L77
[pipe]: https://github.com/IntelRealSense/librealsense/blob/v2.59.1/src/pipeline/pipeline.cpp#L200-L245
[d435m]: https://github.com/IntelRealSense/librealsense/blob/v2.59.1/src/ds/d400/d400-factory.cpp#L1362-L1366
[d400du]: https://github.com/IntelRealSense/librealsense/blob/v2.59.1/src/ds/d400/d400-device.cpp#L1073-L1099
[alsp]: https://github.com/IntelRealSense/librealsense/blob/v2.59.1/src/proc/align.cpp#L210-L232
[alpf]: https://github.com/IntelRealSense/librealsense/blob/v2.59.1/src/proc/align.cpp#L281-L316
[alpr]: https://github.com/IntelRealSense/librealsense/blob/v2.59.1/src/proc/align.cpp#L185-L207
[alz]: https://github.com/IntelRealSense/librealsense/blob/v2.59.1/src/proc/align.cpp#L97-L120
[alimg]: https://github.com/IntelRealSense/librealsense/blob/v2.59.1/src/proc/align.cpp#L50-L120
[alc]: https://github.com/IntelRealSense/librealsense/blob/v2.59.1/src/proc/align.cpp#L28-L46
[sync]: https://github.com/IntelRealSense/librealsense/blob/v2.59.1/src/sync.cpp#L205-L230
[swd]: https://github.com/IntelRealSense/librealsense/blob/v2.59.1/src/software-device.cpp#L64-L81
[swdh]: https://github.com/IntelRealSense/librealsense/blob/v2.59.1/src/software-device.h#L39
[mf]: https://github.com/IntelRealSense/librealsense/blob/v2.59.1/src/core/matcher-factory.cpp#L105-L154
[rsp]: https://github.com/IntelRealSense/librealsense/blob/v2.59.1/include/librealsense2/hpp/rs_processing.hpp#L700-L790
[rsu]: https://github.com/IntelRealSense/librealsense/blob/v2.59.1/include/librealsense2/rsutil.h#L32-L40
[rscpp]: https://github.com/IntelRealSense/librealsense/blob/v2.59.1/src/rs.cpp#L4602-L4655
[pyu]: https://github.com/IntelRealSense/librealsense/blob/v2.59.1/wrappers/python/pyrsutil.cpp#L41-L55
[sws]: https://github.com/IntelRealSense/librealsense/blob/v2.59.1/src/software-sensor.cpp#L166-L185
[sws59]: https://github.com/IntelRealSense/librealsense/blob/v2.59.1/src/software-sensor.cpp#L51-L61
[swsdu]: https://github.com/IntelRealSense/librealsense/blob/v2.59.1/src/software-sensor.cpp#L320-L346
[dfh]: https://github.com/IntelRealSense/librealsense/blob/v2.59.1/src/core/depth-frame.h#L32
