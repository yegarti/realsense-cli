from typing import Optional

from realsense_cli.driver.base import Driver
from realsense_cli.model import (
    DeviceInfo,
    Sensor,
    Option,
    Profile,
    Stream,
    Resolution,
    FrameSet,
    Frame,
)

import pyrealsense2 as rs


class Realsense(Driver):
    def __init__(self, serial: Optional[str] = None):
        self._ctx: rs.context = rs.context()
        self._devices: list[rs.device] = []
        self._sensors: dict[rs.device, dict[Sensor, rs.sensor]] = {}
        self._streams_map: dict[Stream, rs.stream] = {}

        self._active_device: Optional[rs.device] = None
        self._origin_sensor: dict[rs.stream, Sensor] = {}
        self._setup()
        if serial:
            self._setup_device(serial)
        elif self._devices:
            self._active_device = self._devices[0]
        self._streaming = False
        self._pipeline: rs.pipeline = rs.pipeline(self._ctx)
        self._pipe_profile: Optional[rs.pipeline_profile] = None
        self._frame_queue: rs.frame_queue = rs.frame_queue(capacity=1)

    def _setup(self) -> None:
        for dev in self._ctx.devices:
            self._devices.append(dev)
            self._sensors[dev] = {}

            rs_sensor: rs.sensor
            for rs_sensor in dev.sensors:
                self._sensors[dev][Sensor(rs_sensor.name)] = rs_sensor

        self._streams_map.update(
            {
                Stream.DEPTH: rs.stream.depth,
                Stream.INFRARED: rs.stream.infrared,
                Stream.INFRARED2: rs.stream.infrared,
                Stream.COLOR: rs.stream.color,
                Stream.GYRO: rs.stream.gyro,
                Stream.ACCEL: rs.stream.accel,
            }
        )

    def _setup_device(self, serial: str):
        try:
            dev = [
                d for d in self._devices if d.get_info(rs.camera_info.serial_number) == serial
            ][0]
        except KeyError:
            raise ValueError(f"Could find a device with serial: {serial}")
        self._active_device = dev

        for sensor, rs_sensor in self._sensors[dev].items():
            streams = {profile.stream_type() for profile in rs_sensor.profiles}
            for stream in streams:
                self._origin_sensor[stream] = sensor

    def _verify_single_device(self):
        if len(self._devices) > 1:
            raise RuntimeError(f"Multiple devices are not supported")

    def query_devices(self) -> list[DeviceInfo]:
        devices = []
        rsdev: rs.device
        for device, sensors in self._sensors.items():
            rs_sensors = [s for s in sensors.values()]
            devices.append(
                DeviceInfo(
                    name=device.get_info(rs.camera_info.name),
                    serial=device.get_info(rs.camera_info.serial_number),
                    fw=device.get_info(rs.camera_info.firmware_version),
                    connection=device.get_info(rs.camera_info.usb_type_descriptor),
                    sensors=[s.get_info(rs.camera_info.name) for s in rs_sensors],
                )
            )
        return devices

    def list_controls(self, sensor: Sensor) -> list[Option]:
        self._verify_single_device()
        rs_sensor = self._get_sensor(sensor)

        options = rs_sensor.get_supported_options()
        res = []
        for option in options:
            if rs_sensor.is_option_read_only(option):
                continue
            rng: rs.option_range = rs_sensor.get_option_range(option)
            res.append(
                Option(
                    name=option.name,
                    description=rs_sensor.get_option_description(option),
                    min_value=rng.min,
                    max_value=rng.max,
                    step=rng.step,
                    default_value=rng.default,
                )
            )
        return res

    def get_control_values(self, sensor: Sensor, controls: list[str]) -> dict[str, float]:
        self._verify_single_device()
        res = {}
        rs_sensor: rs.sensor = self._get_sensor(sensor)
        for control in controls:
            option = getattr(rs.option, control, None)
            if not option or not rs_sensor.supports(option):
                raise ValueError(f"control '{control}' is not supported for sensor '{sensor}'")
            res[control] = rs_sensor.get_option(option)
        return res

    def set_control_values(self, sensor: Sensor, control_values: dict[str, float]) -> None:
        self._verify_single_device()
        rs_sensor = self._get_sensor(sensor)

        for control, value in control_values.items():
            option = getattr(rs.option, control, None)
            if not option or not rs_sensor.supports(option):
                raise ValueError(
                    f"control '{control}' is not supported for sensor '{sensor.value}'"
                )
            rs_sensor.set_option(option, value)

    def list_streams(self, sensor: Sensor) -> list[Profile]:
        self._verify_single_device()
        rs_sensor = self._get_sensor(sensor)
        profiles: list[rs.stream_profile] = rs_sensor.get_stream_profiles()
        res = []
        for profile in profiles:
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
        return res

    def play(self, profiles: Optional[list[Profile]] = None) -> None:
        self._verify_single_device()
        cfg = rs.config()
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
        self._pipe_profile = self._pipeline.start(cfg, self._frame_queue)
        self._streaming = True

    def stop(self) -> None:
        self._verify_single_device()
        self._pipeline.stop()
        self._streaming = False

    def wait_for_frameset(self, timeout: float = 1.0) -> FrameSet:
        result: FrameSet = {}
        rs_frameset: rs.composite_frame = self._frame_queue.wait_for_frame(
            int(timeout * 1000)
        ).as_frameset()

        rs_frame: rs.frame
        for rs_frame in rs_frameset:
            rs_profile: rs.stream_profile = rs_frame.get_profile()
            profile = self._convert_profile(rs_profile)
            frame = Frame(
                profile=profile,
                timestamp=rs_frame.get_timestamp(),
                index=rs_frame.get_frame_number(),
            )
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
        return self._sensors[self._active_device][sensor]
