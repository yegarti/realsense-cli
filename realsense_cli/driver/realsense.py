import struct
import time
from collections import defaultdict
from itertools import permutations

import pyrealsense2 as rs
from loguru import logger

from realsense_cli.driver.reconnect import ReconnectWatch, reset_and_wait
from realsense_cli.errors import (
    DeviceNotFound,
    InvalidProfile,
    InvalidValue,
    UnknownControl,
    UnknownSensor,
)
from realsense_cli.types import (
    Calibration,
    DeviceInfo,
    Extrinsics,
    Frame,
    FrameSet,
    Image,
    Intrinsics,
    Option,
    Profile,
    Resolution,
    Stream,
    StreamIntrinsics,
    sensor_label,
)
from realsense_cli.utils import find_origin_sensor, stream_rank

_PROFILES_HINT = "Run `rs stream list` to see the supported profiles"

# The SDK's camera info fields, with the connection type (USB, GMSL, DDS) moved up to the USB
# type it qualifies
_CAMERA_INFO_ORDER = [name for name in rs.camera_info.__members__ if name != "connection_type"]
_CAMERA_INFO_ORDER.insert(_CAMERA_INFO_ORDER.index("usb_type_descriptor"), "connection_type")

# Frames waiting for `wait_for_frameset`. Sensors deliver into one queue, which drops frames
# once full: a capacity of 1 starves every sensor but the last to deliver
_FRAME_QUEUE_CAPACITY = 32


def _float32(value: float) -> float:
    """
    VALUE, a float32 the SDK widened to a Python float, as the shortest decimal that reads
    back as the same float32: 0.001 comes back from the SDK as 0.0010000000474974513
    """
    # a float32 round-trips through 9 significant digits, and often fewer
    for digits in range(1, 9):
        shorter = float(f"{value:.{digits}g}")
        if struct.unpack("f", struct.pack("f", shorter))[0] == value:
            return shorter
    return float(f"{value:.9g}")


def _intrinsics(rs_intrinsics: rs.intrinsics) -> Intrinsics:
    return Intrinsics(
        ppx=_float32(rs_intrinsics.ppx),
        ppy=_float32(rs_intrinsics.ppy),
        fx=_float32(rs_intrinsics.fx),
        fy=_float32(rs_intrinsics.fy),
        model=rs_intrinsics.model.name,
        coeffs=tuple(map(_float32, rs_intrinsics.coeffs)),
    )


def _image(rs_frame: rs.video_frame) -> Image:
    width, height = rs_frame.get_width(), rs_frame.get_height()
    data = bytes(rs_frame.get_data())
    row = width * rs_frame.get_bytes_per_pixel()
    stride = rs_frame.get_stride_in_bytes()
    if stride != row:
        data = b"".join(data[y * stride : y * stride + row] for y in range(height))
    return Image(width, height, rs_frame.get_profile().format().name, data)


class Realsense:
    """
    pyrealsense2 wrapper driver
    """

    def __init__(self, devices: list[rs.device] | None = None):
        """
        DEVICES overrides the devices enumerated from the context, e.g. `rs.software_device`
        instances, which pyrealsense2 cannot add to a context. The pipeline API only sees
        context devices, so injected devices stream with `play(pipeline=False)`.
        """
        logger.info("Instancing Realsense driver")
        self._ctx: rs.context = rs.context()
        self._injected_devices = devices
        self._devices: list[rs.device] = []
        self._sensors: dict[rs.device, dict[str, rs.sensor]] = {}
        self._streams_map: dict[str, rs.stream] = {
            Stream.DEPTH: rs.stream.depth,
            Stream.INFRARED: rs.stream.infrared,
            Stream.INFRARED2: rs.stream.infrared,
            Stream.COLOR: rs.stream.color,
            Stream.GYRO: rs.stream.gyro,
            Stream.ACCEL: rs.stream.accel,
        }
        self._metadata: list[rs.frame_metadata_value] = []
        self._stream_method: str = "pipe"

        self._setup()
        self._active_device: rs.device | None = None
        if self._devices:
            logger.debug("setting first device as active one")
            # sorting to be deterministic every run
            self._active_device = sorted(
                [(d.get_info(rs.camera_info.serial_number), d) for d in self._devices]
            )[0][1]
        logger.info("active device: {}", self._active_device)
        self._streaming = False
        self._pipeline: rs.pipeline = rs.pipeline(self._ctx)
        self._pipe_profile: rs.pipeline_profile | None = None
        self._frame_queue: rs.frame_queue = rs.frame_queue(capacity=_FRAME_QUEUE_CAPACITY)
        self._colorizer: rs.colorizer = rs.colorizer()

    def _setup(self) -> None:
        self._query()
        self._prep_valid_md_attrs()

    def _query(self):
        devices = (
            self._ctx.devices if self._injected_devices is None else self._injected_devices
        )
        for dev in devices:
            logger.debug("Adding device: {}", dev)
            self._devices.append(dev)
            self._sensors[dev] = {}

            rs_sensor: rs.sensor
            for rs_sensor in dev.sensors:
                logger.debug("Adding sensor {} for device {}", rs_sensor, dev)
                self._sensors[dev][rs_sensor.name] = rs_sensor

        logger.info("Found {} devices", len(self._devices))

    def _prep_valid_md_attrs(self):
        for name in dir(rs.frame_metadata_value):
            attr = getattr(rs.frame_metadata_value, name)
            if isinstance(attr, rs.frame_metadata_value):
                self._metadata.append(attr)

    def query_devices(self) -> list[DeviceInfo]:
        """
        Query connected devices
        """
        devices = []
        for device, sensors in self._sensors.items():
            rs_sensors = [s for s in sensors.values()]
            logger.debug("adding device info for device {}", device)

            def _safe_get_info(info: rs.camera_info, device=device):
                try:
                    return device.get_info(info)
                except Exception as e:
                    logger.error(e)
                return "N/A"

            info = DeviceInfo(
                name=device.get_info(rs.camera_info.name),
                serial=device.get_info(rs.camera_info.serial_number),
                fw=_safe_get_info(rs.camera_info.firmware_version),
                connection=_safe_get_info(rs.camera_info.usb_type_descriptor),
                sensors=[s.get_info(rs.camera_info.name) for s in rs_sensors],
            )
            logger.debug("adding device info: {}", info)
            devices.append(info)
        return devices

    def camera_info(self) -> dict[str, str]:
        """
        Every camera info field the active device supports, keyed by its `rs.camera_info` name.
        A field the device reports as 'unknown' says nothing, e.g. the IMU type of a D415,
        which has no IMU, and is left out
        """
        info = {}
        # by `__members__` key: `rs.camera_info.name` is a member, so members have no `.name`
        for name in _CAMERA_INFO_ORDER:
            rs_info = rs.camera_info.__members__[name]
            if not self._device.supports(rs_info):
                continue
            value = self._device.get_info(rs_info)
            if value.lower() != "unknown":
                info[name] = value
        return info

    def list_controls(self, sensor: str) -> list[Option]:
        """
        List controls supported by SENSOR
        """
        rs_sensor = self._get_sensor(sensor)
        logger.info("listing controls for sensor {}", rs_sensor)

        options = rs_sensor.get_supported_options()
        res = []
        for option in options:
            logger.debug("querying option: {}", option)
            rng: rs.option_range = rs_sensor.get_option_range(option)
            vtype = float
            if rng.step == int(rng.step) and rng.min == int(rng.min):
                vtype = int
            opt = Option(
                name=option.name,
                description=rs_sensor.get_option_description(option),
                min_value=round(rng.min, 6),
                max_value=round(rng.max, 6),
                step=round(rng.step, 6),
                default_value=round(rng.default, 6),
                vtype=vtype,
                read_only=rs_sensor.is_option_read_only(option),
            )
            logger.debug("adding Option: {}", opt)
            res.append(opt)
        return res

    def get_control_values(self, sensor: str, controls: list[str]) -> dict[str, float]:
        """
        Get values for CONTROLS from SENSOR
        """
        res = {}
        rs_sensor: rs.sensor = self._get_sensor(sensor)
        logger.info("querying controls {} for sensor {}", controls, rs_sensor)
        for control in controls:
            option = self._get_option(rs_sensor, sensor, control)
            logger.debug('getting value for option: "{}"', option)
            res[control] = rs_sensor.get_option(option)
            logger.debug('"{}" value: {}', option, res[control])
        return res

    def set_control_values(self, sensor: str, control_values: dict[str, float]) -> None:
        """
        Set CONTROL_VALUES on SENSOR
        """
        rs_sensor = self._get_sensor(sensor)

        logger.info("setting controls {} for sensor {}", control_values, rs_sensor)
        for control, value in control_values.items():
            option = self._get_option(rs_sensor, sensor, control)
            if rs_sensor.is_option_read_only(option):
                raise InvalidValue(f"Control '{control}' on '{sensor}' is read-only")
            logger.debug('setting "{}" with value {}', option, value)
            try:
                rs_sensor.set_option(option, value)
            except RuntimeError as e:
                rng = rs_sensor.get_option_range(option)
                raise InvalidValue(
                    f"Failed to set '{control}' to {value}: {e}. "
                    f"Valid range: {rng.min:g} to {rng.max:g}, step {rng.step:g}"
                ) from e

    def list_streams(self, sensor: str) -> list[Profile]:
        """
        List supported streams for SENSOR
        """
        rs_sensor = self._get_sensor(sensor)
        logger.info("listing streams for sensor {}", rs_sensor)
        profiles: list[rs.stream_profile] = rs_sensor.get_stream_profiles()
        res = []
        for profile in profiles:
            logger.debug("found profile: {}", profile)
            if profile.is_video_stream_profile():
                vsp: rs.video_stream_profile = profile.as_video_stream_profile()
                width, height = vsp.width(), vsp.height()
            else:
                width, height = 0, 0

            res.append(
                Profile(
                    stream=profile.stream_name(),
                    resolution=Resolution(width, height),
                    fps=profile.fps(),
                    format=profile.format().name.upper(),
                    index=profile.stream_index(),
                )
            )
            logger.debug("adding profile {}", res[-1])
        return res

    def play(
        self, profiles: list[Profile] | None = None, pipeline: bool = True
    ) -> list[Profile]:
        """
        Start streaming selected profiles; the profiles the device actually started
        """
        logger.info("Playing profiles: {}", profiles)
        if pipeline and self._injected_devices is not None:
            logger.info("pipeline cannot see injected devices, streaming with sensor API")
            pipeline = False
        if pipeline:
            started = self._stream_pipe(profiles)
        else:
            started = self._stream_sensor(profiles)
        self._streaming = True
        return started

    def _stream_sensor(self, profiles: list[Profile] | None) -> list[Profile]:
        self._stream_method = "sensor"
        if not profiles:
            profiles = self._default_profiles()
        sensor_profiles = {}
        for sensor in self._sensors[self._device]:
            sensor_profiles[sensor] = self.list_streams(sensor)
        origin_streams: dict[str, str] = find_origin_sensor(sensor_profiles)

        stream_profiles: dict[str, list[Profile]] = {s: [] for s in origin_streams.values()}
        for profile in profiles:
            if profile.stream not in origin_streams:
                raise InvalidProfile(
                    f"Unknown stream '{profile.stream}'. "
                    f"Valid streams: {', '.join(origin_streams)}"
                )
            stream_profiles[origin_streams[profile.stream]].append(profile)

        rs_stream_profiles: dict[str, list[rs.stream_profile]] = defaultdict(list)
        for sensor, sprofiles in stream_profiles.items():
            rs_sensor: rs.sensor = self._get_sensor(sensor)
            rs_profiles = rs_sensor.get_stream_profiles()

            for profile in sprofiles:
                logger.debug(f"Looking a match for {profile}")
                for rs_profile in rs_profiles:
                    if self._matches(rs_profile, profile):
                        logger.debug(f"Found match: {rs_profile}")
                        rs_stream_profiles[sensor].append(rs_profile)
                        break
                else:
                    raise InvalidProfile(
                        f"No profile on '{sensor}' matches '{profile}'. {_PROFILES_HINT}"
                    )

        if not rs_stream_profiles:
            raise InvalidProfile(f"The device has no default profiles. {_PROFILES_HINT}")

        for sensor, rs_profiles in rs_stream_profiles.items():
            logger.info(f"Starting stream for {sensor} with {rs_profiles}")
            rs_sensor = self._get_sensor(sensor)
            rs_sensor.open(rs_profiles)
            rs_sensor.start(self._frame_queue)
        return [Profile.from_rs(sp) for sps in rs_stream_profiles.values() for sp in sps]

    def _matches(self, rs_profile: rs.stream_profile, profile: Profile) -> bool:
        """
        Whether RS_PROFILE is PROFILE, whose unset parts (index -1, fps 0, width or height 0,
        format 'any') match anything
        """
        width, height = 0, 0
        if rs_profile.is_video_stream_profile():
            vsp = rs_profile.as_video_stream_profile()
            width, height = vsp.width(), vsp.height()
        return (
            rs_profile.stream_type() == self._get_rs_stream(profile.stream)
            and profile.index in (-1, rs_profile.stream_index())
            and (
                profile.format == "any"
                or rs_profile.format() == self._get_rs_format(profile.format)
            )
            and profile.fps in (0, rs_profile.fps())
            and profile.resolution.width in (0, width)
            and profile.resolution.height in (0, height)
        )

    def _default_profiles(self) -> list[Profile]:
        return [
            Profile.from_rs(rs_profile)
            for rs_sensor in self._sensors[self._device].values()
            for rs_profile in rs_sensor.get_stream_profiles()
            if rs_profile.is_default()
        ]

    def _stream_pipe(self, profiles) -> list[Profile]:
        self._stream_method = "pipe"
        cfg = rs.config()
        cfg.enable_device(self._device.get_info(rs.camera_info.serial_number))
        if profiles:
            for profile in profiles:
                cfg.enable_stream(
                    self._get_rs_stream(profile.stream),
                    profile.index,
                    profile.resolution.width,
                    profile.resolution.height,
                    self._get_rs_format(profile.format),
                    profile.fps,
                )
        else:
            cfg.enable_all_streams()
        logger.info("Starting stream")
        try:
            self._pipe_profile = self._pipeline.start(cfg, self._frame_queue)
        except RuntimeError as e:
            requested = ", ".join(str(p) for p in profiles or [])
            raise InvalidProfile(
                f"Failed to start profiles [{requested}]: {e}. {_PROFILES_HINT}"
            ) from e
        return [Profile.from_rs(sp) for sp in self._pipe_profile.get_streams()]

    def calibration(self, profiles: list[Profile] | None = None) -> Calibration:
        """
        Intrinsics of the video profiles matching PROFILES (every video profile when None), and
        the extrinsics between their streams in both directions
        """
        rs_profiles = [
            rs_profile
            for rs_sensor in self._sensors[self._device].values()
            for rs_profile in rs_sensor.get_stream_profiles()
            if rs_profile.is_video_stream_profile()
        ]
        # known streams first, in the order the CLI lists them; a stable sort keeps the
        # device's own order within a stream
        rs_profiles.sort(key=lambda rs_profile: stream_rank(rs_profile.stream_name()))

        if profiles is not None:
            for profile in profiles:
                if not any(self._matches(p, profile) for p in rs_profiles):
                    streams = ", ".join(dict.fromkeys(p.stream_name() for p in rs_profiles))
                    raise InvalidProfile(
                        f"No video profile matches '{profile}'. Video streams: {streams}. "
                        f"{_PROFILES_HINT}"
                    )
            rs_profiles = [
                rs_profile
                for rs_profile in rs_profiles
                if any(self._matches(rs_profile, profile) for profile in profiles)
            ]

        groups: dict[tuple, list[rs.video_stream_profile]] = defaultdict(list)
        for rs_profile in rs_profiles:
            vsp = rs_profile.as_video_stream_profile()
            try:
                intr = _intrinsics(vsp.get_intrinsics())
            except RuntimeError:
                # the SDK has none for some profiles, e.g. the unrectified infrared Y16 ones
                intr = None
            key = (
                vsp.stream_name(),
                vsp.stream_index(),
                Resolution(vsp.width(), vsp.height()),
                intr,
            )
            groups[key].append(vsp)
        intrinsics = [
            StreamIntrinsics(
                stream=stream,
                index=index,
                resolution=resolution,
                formats=tuple(dict.fromkeys(p.format().name.upper() for p in group)),
                fps=tuple(sorted({p.fps() for p in group})),
                intrinsics=intr,
            )
            for (stream, index, resolution, intr), group in groups.items()
        ]

        # a device keeps extrinsics per stream, so any one profile stands for its stream
        streams: dict[str, rs.stream_profile] = {}
        for rs_profile in rs_profiles:
            streams.setdefault(rs_profile.stream_name(), rs_profile)
        extrinsics = []
        for (source, source_profile), (target, target_profile) in permutations(
            streams.items(), 2
        ):
            try:
                rs_extrinsics = source_profile.get_extrinsics_to(target_profile)
            except RuntimeError as e:
                logger.debug("no extrinsics from {} to {}: {}", source, target, e)
                continue
            extrinsics.append(
                Extrinsics(
                    source=source,
                    target=target,
                    rotation=tuple(map(_float32, rs_extrinsics.rotation)),
                    translation=tuple(map(_float32, rs_extrinsics.translation)),
                )
            )
        return Calibration(intrinsics, extrinsics)

    def stop(self) -> None:
        """
        Stop streaming
        """
        logger.info("Stopping stream")
        if self._stream_method == "pipe":
            self._pipeline.stop()
        else:
            for rs_sensor in self._sensors[self._device].values():
                if rs_sensor.get_active_streams():
                    rs_sensor.stop()
                    rs_sensor.close()
        self._streaming = False

    def depth_scale(self) -> float | None:
        """
        Meters per depth unit of the active device, None when it has no depth sensor
        """
        for rs_sensor in self._sensors[self._device].values():
            if rs_sensor.is_depth_sensor():
                return _float32(rs_sensor.as_depth_sensor().get_depth_scale())
        return None

    def wait_for_frameset(self, timeout: float = 3.0, images: bool = False) -> FrameSet | None:
        """
        Get next frameset waiting in queue.
        return None when no frameset arrive after timeout.
        With IMAGES, video frames also carry their image, and depth frames their colorized one
        """
        result: FrameSet = {}
        arrived, rs_frame = self._frame_queue.try_wait_for_frame(int(timeout * 1000))
        if not arrived:
            return None
        frames: list[rs.frame]
        if rs_frame.is_frameset():
            frames = [f for f in rs_frame.as_frameset()]
        else:
            frames = [rs_frame]
        logger.debug("frameset received")

        t0 = time.time()
        rs_frame: rs.frame
        for rs_frame in frames:
            t1 = time.time()
            rs_profile: rs.stream_profile = rs_frame.get_profile()
            profile = Profile.from_rs(rs_profile)
            metadata = {}
            for md in self._metadata:
                if rs_frame.supports_frame_metadata(md):
                    metadata[md.name] = rs_frame.get_frame_metadata(md)
            frame = Frame(
                profile=profile,
                timestamp=rs_frame.get_timestamp(),
                index=rs_frame.get_frame_number(),
                metadata=metadata,
            )
            if images and rs_frame.is_video_frame():
                frame.image = _image(rs_frame.as_video_frame())
                if rs_frame.is_depth_frame():
                    colorized = self._colorizer.colorize(rs_frame)
                    frame.colorized = _image(colorized.as_video_frame())
            logger.debug(
                "{}\t#{} {:.2}ms - {}",
                frame.profile.stream,
                frame.index,
                (time.time() - t1) * 1000,
                frame,
            )
            result[profile.stream] = frame
        logger.debug(f"Total callback time: {(time.time() - t0) * 1000:.2}ms")

        return result

    def reset(self, timeout: float | None = None) -> bool:
        """
        Send hardware reset to device. With TIMEOUT, wait up to TIMEOUT seconds for it to come
        back and answer; whether it did
        """
        serial = self.active_device
        device = self._device
        watch = ReconnectWatch(serial)

        def on_change(info: rs.event_information) -> None:
            if info.was_removed(device):
                watch.on_removed(serial)
            for new in info.get_new_devices():
                watch.on_added(new.get_info(rs.camera_info.serial_number))

        def ready() -> bool:
            try:
                for dev in rs.context().devices:
                    if dev.get_info(rs.camera_info.serial_number) == serial:
                        sensor = dev.sensors[0]
                        sensor.get_option(sensor.get_supported_options()[0])
                        return True
            except RuntimeError as e:
                logger.debug("device '{}' not ready yet: {}", serial, e)
            return False

        self._ctx.set_devices_changed_callback(on_change)
        return reset_and_wait(watch, device.hardware_reset, ready, timeout)

    def _get_sensor(self, sensor: str) -> rs.sensor:
        if sensor not in self._sensors[self._device]:
            raise UnknownSensor(sensor, map(sensor_label, self._sensors[self._device]))
        return self._sensors[self._device][sensor]

    @staticmethod
    def _get_option(rs_sensor: rs.sensor, sensor: str, control: str) -> rs.option:
        option = rs.option.__members__.get(control)
        if option is None or not rs_sensor.supports(option):
            supported = sorted(o.name for o in rs_sensor.get_supported_options())
            raise UnknownControl(control, sensor, supported)
        return option

    def _get_rs_stream(self, stream: str) -> rs.stream:
        rs_stream = self._streams_map.get(stream)
        if rs_stream is None:
            raise InvalidProfile(
                f"Unknown stream '{stream}'. Valid streams: {', '.join(self._streams_map)}"
            )
        return rs_stream

    @staticmethod
    def _get_rs_format(fmt: str) -> rs.format:
        rs_format = rs.format.__members__.get(fmt.lower())
        if rs_format is None:
            raise InvalidProfile(
                f"Unknown format '{fmt}'. Valid formats: {', '.join(rs.format.__members__)}"
            )
        return rs_format

    @property
    def _device(self) -> rs.device:
        if self._active_device is None:
            raise DeviceNotFound("No devices are connected")
        return self._active_device

    @property
    def sensors(self) -> list[str]:
        return list(self._sensors[self._device].keys())

    @property
    def active_device(self) -> str:
        return self._device.get_info(rs.camera_info.serial_number)

    @active_device.setter
    def active_device(self, serial: str | None = None):
        if not serial:
            return
        for dev in self._devices:
            if dev.get_info(rs.camera_info.serial_number) == serial:
                self._active_device = dev
                break
        else:
            connected = ", ".join(
                d.get_info(rs.camera_info.serial_number) for d in self._devices
            )
            raise DeviceNotFound(
                f"No device with serial '{serial}' is connected. "
                f"Connected devices: {connected or 'none'}"
            )
