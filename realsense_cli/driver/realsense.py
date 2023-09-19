import operator
from typing import Optional

from loguru import logger

from realsense_cli.driver.base import Driver
from realsense_cli.types import (
    DeviceInfo,
    Sensor,
    Option,
    Profile,
    Stream,
    Resolution,
    FrameSet,
    Frame,
)

import pyrealsense2 as rs  # type: ignore


class Realsense(Driver):
    def __init__(self):
        logger.info("Instancing Realsense driver")
        self._ctx: rs.context = rs.context()
        self._devices: list[rs.device] = []
        self._sensors: dict[rs.device, dict[Sensor, rs.sensor]] = {}
        self._streams_map: dict[Stream, rs.stream] = {
            Stream.DEPTH: rs.stream.depth,
            Stream.INFRARED: rs.stream.infrared,
            Stream.INFRARED2: rs.stream.infrared,
            Stream.COLOR: rs.stream.color,
            Stream.GYRO: rs.stream.gyro,
            Stream.ACCEL: rs.stream.accel,
        }

        self._setup()
        if self._devices:
            logger.debug(f"setting first device as active one")
            # sorting to be deterministic every run
            self._active_device = sorted(
                [(d.get_info(rs.camera_info.serial_number), d) for d in self._devices]
            )[0][1]
        logger.info("active device: {}", self._active_device)
        self._streaming = False
        self._pipeline: rs.pipeline = rs.pipeline(self._ctx)
        self._pipe_profile: Optional[rs.pipeline_profile] = None
        self._frame_queue: rs.frame_queue = rs.frame_queue(capacity=1)

    def _setup(self) -> None:
        for dev in self._ctx.devices:
            logger.debug("Adding device: {}", dev)
            self._devices.append(dev)
            self._sensors[dev] = {}

            rs_sensor: rs.sensor
            for rs_sensor in dev.sensors:
                logger.debug("Adding sensor {} for device {}", rs_sensor, dev)
                self._sensors[dev][Sensor(rs_sensor.name)] = rs_sensor
        logger.info("Found {} devices", len(self._devices))

    def _setup_device(self, serial: str):
        logger.debug("getting first device with serial {}", serial)
        try:
            dev = [
                d for d in self._devices if d.get_info(rs.camera_info.serial_number) == serial
            ][0]
        except KeyError:
            raise ValueError(f"Could find a device with serial: {serial}")
        self._active_device = dev

    def query_devices(self) -> list[DeviceInfo]:
        devices = []
        rsdev: rs.device
        for device, sensors in self._sensors.items():
            rs_sensors = [s for s in sensors.values()]
            logger.debug("adding device info for device {}", device)
            info = DeviceInfo(
                name=device.get_info(rs.camera_info.name),
                serial=device.get_info(rs.camera_info.serial_number),
                fw=device.get_info(rs.camera_info.firmware_version),
                connection=device.get_info(rs.camera_info.usb_type_descriptor),
                sensors=[s.get_info(rs.camera_info.name) for s in rs_sensors],
            )
            logger.debug("adding device info: {}", info)
            devices.append(info)
        return devices

    def list_controls(self, sensor: Sensor) -> list[Option]:
        rs_sensor = self._get_sensor(sensor)
        logger.info("listing controls for sensor {}", rs_sensor)

        options = rs_sensor.get_supported_options()
        res = []
        for option in options:
            logger.debug("querying option: {}", option)
            if rs_sensor.is_option_read_only(option):
                logger.debug("skipping read only option")
                continue
            rng: rs.option_range = rs_sensor.get_option_range(option)
            opt = Option(
                name=option.name,
                description=rs_sensor.get_option_description(option),
                min_value=round(rng.min, 6),
                max_value=round(rng.max, 6),
                step=round(rng.step, 6),
                default_value=round(rng.default, 6),
            )
            logger.debug("adding Option: {}", opt)
            res.append(opt)
        return res

    def get_control_values(self, sensor: Sensor, controls: list[str]) -> dict[str, float]:
        res = {}
        rs_sensor: rs.sensor = self._get_sensor(sensor)
        logger.info("querying controls {} for sensor {}", controls, rs_sensor)
        for control in controls:
            option = getattr(rs.option, control, None)
            logger.debug('getting value for option: "{}"', option)
            if not option or not rs_sensor.supports(option):
                raise ValueError(f"control '{control}' is not supported for sensor '{sensor}'")
            res[control] = rs_sensor.get_option(option)
            logger.debug('"{}" value: {}', option, res[control])
        return res

    def set_control_values(self, sensor: Sensor, control_values: dict[str, float]) -> None:
        rs_sensor = self._get_sensor(sensor)

        logger.info("setting controls {} for sensor {}", control_values, rs_sensor)
        for control, value in control_values.items():
            option = getattr(rs.option, control, None)
            logger.debug('setting "{}" with value {}', option, value)
            if not option or not rs_sensor.supports(option):
                logger.debug("no such option or not supported by sensor")
                raise ValueError(
                    f"control '{control}' is not supported for sensor '{sensor.value}'"
                )
            rs_sensor.set_option(option, value)

    def list_streams(self, sensor: Sensor) -> list[Profile]:
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
                    stream=Stream(profile.stream_name()),
                    resolution=Resolution(width, height),
                    fps=profile.fps(),
                    format=profile.format().name.upper(),
                )
            )
            logger.debug("adding profile {}", res[-1])
        return res

    def play(self, profiles: Optional[list[Profile]] = None) -> None:
        cfg = rs.config()
        logger.info("Playing profiles: {}", profiles)
        cfg.enable_device(self._active_device.get_info(rs.camera_info.serial_number))
        if profiles:
            for profile in profiles:
                rs_stream = self._streams_map[profile.stream]
                rs_format = rs.format.any
                cfg.enable_stream(
                    rs_stream,
                    profile.index,
                    profile.resolution.width,
                    profile.resolution.height,
                    rs_format,
                    profile.fps,
                )
        else:
            cfg.enable_all_streams()
        logger.info("Starting stream")
        self._pipe_profile = self._pipeline.start(cfg, self._frame_queue)
        self._streaming = True

    def stop(self) -> None:
        logger.info("Stopping stream")
        self._pipeline.stop()
        self._streaming = False

    def wait_for_frameset(self, timeout: float = 3.0) -> Optional[FrameSet]:
        result: FrameSet = {}
        rs_frameset: rs.composite_frame = self._frame_queue.wait_for_frame(
            int(timeout * 1000)
        ).as_frameset()
        logger.debug("frameset received")

        rs_frame: rs.frame
        for rs_frame in rs_frameset:
            rs_profile: rs.stream_profile = rs_frame.get_profile()
            profile = self._convert_profile(rs_profile)
            frame = Frame(
                profile=profile,
                timestamp=rs_frame.get_timestamp(),
                index=rs_frame.get_frame_number(),
            )
            logger.debug("{}\t#{} - {}", frame.profile.stream.value, frame.index, frame)
            result[profile.stream] = frame

        return result

    def _convert_profile(self, profile: rs.stream_profile) -> Profile:
        width, height = 0, 0
        if profile.is_video_stream_profile():
            vsp: rs.video_stream_profile = profile.as_video_stream_profile()
            width, height = vsp.width(), vsp.height()

        return Profile(
            stream=Stream(profile.stream_name()),
            resolution=Resolution(width, height),
            fps=profile.fps(),
            format=profile.format().name,
            index=profile.stream_index(),
        )

    def _get_sensor(self, sensor: Sensor) -> rs.sensor:
        if sensor not in self._sensors[self._active_device]:
            raise RuntimeError(
                f'Sensor "{sensor.value}" is not supported on device: {self._active_device.get_info(rs.camera_info.serial_number)}'
            )
        return self._sensors[self._active_device][sensor]

    @property
    def sensors(self) -> list[Sensor]:
        return list(self._sensors[self._active_device].keys())

    @property
    def active_device(self) -> str:
        return self._active_device.get_info(rs.camera_info.serial_number)

    @active_device.setter
    def active_device(self, serial: Optional[str] = None):
        if not serial:
            return
        for dev in self._devices:
            if dev.get_info(rs.camera_info.serial_number) == serial:
                self._active_device = dev
                break
        else:
            raise ValueError(f"No device with serial {serial} is connected")
