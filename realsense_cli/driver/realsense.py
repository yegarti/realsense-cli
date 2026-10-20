import time
from collections import defaultdict
from collections.abc import Iterable

import pyrealsense2 as rs
from loguru import logger

from realsense_cli.errors import (
    DeviceNotFound,
    InvalidProfile,
    InvalidValue,
    UnknownControl,
    UnknownSensor,
)
from realsense_cli.types import (
    DeviceInfo,
    Frame,
    FrameSet,
    Option,
    Profile,
    Resolution,
    Stream,
    sensor_label,
)
from realsense_cli.utils import find_origin_sensor, wait_for_reconnect

_PROFILES_HINT = "Run `rs stream list` to see the supported profiles"


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
        self._frame_queue: rs.frame_queue = rs.frame_queue(capacity=1)

    def _setup(self) -> None:
        self._query()
        self._prep_valid_md_attrs()

    def _connected_devices(self) -> Iterable[rs.device]:
        return self._ctx.devices if self._injected_devices is None else self._injected_devices

    def _query(self):
        for dev in self._connected_devices():
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

    def play(self, profiles: list[Profile] | None = None, pipeline: bool = True) -> None:
        """
        Start streaming selected profiles
        """
        logger.info("Playing profiles: {}", profiles)
        if pipeline and self._injected_devices is not None:
            logger.info("pipeline cannot see injected devices, streaming with sensor API")
            pipeline = False
        if pipeline:
            self._stream_pipe(profiles)
        else:
            self._stream_sensor(profiles)
        self._streaming = True

    def _stream_sensor(self, profiles: list[Profile] | None):
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

                rs_stream_type = self._get_rs_stream(profile.stream)

                skip_index = profile.index == -1
                skip_fps = profile.fps == 0
                skip_width = profile.resolution.width == 0
                skip_height = profile.resolution.height == 0
                skip_format = profile.format == "any"
                fmt = self._get_rs_format(profile.format)

                logger.debug(
                    f"{skip_index=}, {skip_fps=}, {skip_format=}, {skip_height=}, {skip_width=}"
                )

                for rs_profile in rs_profiles:
                    if rs_profile.is_video_stream_profile():
                        sp: rs.video_stream_profile = rs_profile.as_video_stream_profile()
                        width, height = sp.width(), sp.height()
                    else:
                        sp = rs_profile
                        width, height = 0, 0

                    logger.debug(f"checking {rs_profile}...")
                    if (
                        sp.stream_type() == rs_stream_type
                        and (skip_index or (sp.stream_index() == profile.index))
                        and (skip_format or (sp.format() == fmt))
                        and (skip_fps or (sp.fps() == profile.fps))
                        and (skip_width or (width == profile.resolution.width))
                        and (skip_height or (height == profile.resolution.height))
                    ):
                        logger.debug(f"Found match: {sp}")
                        rs_stream_profiles[sensor].append(sp)
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

    def _default_profiles(self) -> list[Profile]:
        return [
            Profile.from_rs(rs_profile)
            for rs_sensor in self._sensors[self._device].values()
            for rs_profile in rs_sensor.get_stream_profiles()
            if rs_profile.is_default()
        ]

    def _stream_pipe(self, profiles):
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

    def wait_for_frameset(self, timeout: float = 3.0) -> FrameSet | None:
        """
        Get next frameset waiting in queue.
        return None when no frameset arrive after timeout
        """
        result: FrameSet = {}
        try:
            rs_frame: rs.frame = self._frame_queue.wait_for_frame(int(timeout * 1000))
        except RuntimeError as e:
            if "Frame didn't arrive within" in str(e):
                return None
            raise
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

    def reset(self):
        """
        Send hardware reset to device
        """
        self._device.hardware_reset()

    def wait_for_reconnect(self, serial: str, timeout: float) -> bool:
        """
        Wait for device SERIAL to drop off and come back, after `reset()`. The serial is
        passed in because the reset device's handle may no longer answer
        """

        def connected() -> set[str]:
            return {d.get_info(rs.camera_info.serial_number) for d in self._connected_devices()}

        if self._injected_devices is not None:
            # injected devices never drop off, so there is nothing to wait for
            return serial in connected()
        return wait_for_reconnect(serial, connected, timeout)

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
