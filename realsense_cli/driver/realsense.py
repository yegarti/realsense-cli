from typing import Any

from realsense_cli.driver.base import Driver
from realsense_cli.types import DeviceInfo, Sensor, Option, Profile, Stream

import pyrealsense2 as rs


class Realsense(Driver):
    def __init__(self):
        self._ctx: rs.context = rs.context()
        self._devices: list[rs.device] = self._ctx.query_devices()

    def query_devices(self) -> list[DeviceInfo]:
        devices = []
        rsdev: rs.device
        for rsdev in self._devices:
            sensors: list[rs.sensor] = rsdev.query_sensors()
            devices.append(
                DeviceInfo(
                    name=rsdev.get_info(rs.camera_info.name),
                    serial=rsdev.get_info(rs.camera_info.serial_number),
                    fw=rsdev.get_info(rs.camera_info.firmware_version),
                    connection=rsdev.get_info(rs.camera_info.usb_type_descriptor),
                    sensors=[s.get_info(rs.camera_info.name) for s in sensors],
                )
            )
        return devices

    def list_controls(self, sensor: Sensor) -> list[Option]:
        rs_sensor: rs.sensor = self._get_sensor(sensor)

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
        res = {}
        rs_sensor: rs.sensor = self._get_sensor(sensor)
        for control in controls:
            option = getattr(rs.option, control, None)
            if not option or not rs_sensor.supports(option):
                raise ValueError(f"control '{control}' is not supported for sensor '{sensor}'")
            res[control] = rs_sensor.get_option(option)
        return res

    def set_control_values(self, sensor: Sensor, control_values: dict[str, float]) -> None:
        rs_sensor = self._get_sensor(sensor)

        for control, value in control_values.items():
            option = getattr(rs.option, control, None)
            if not option or not rs_sensor.supports(option):
                raise ValueError(
                    f"control '{control}' is not supported for sensor '{sensor.value}'"
                )
            rs_sensor.set_option(option, value)

    def list_streams(self, sensor: Sensor) -> list[Profile]:
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
                    resolution=(width, height),
                    fps=profile.fps(),
                    format=profile.format().name.upper(),
                )
            )
        return res

    def _get_sensor(self, sensor: Sensor) -> rs.sensor:
        # TODO - get device by serial
        dev = self._devices[0]
        rs_sensor: rs.sensor
        if sensor == Sensor.STEREO_MODULE:
            rs_sensor = dev.first_depth_sensor()
        elif sensor == Sensor.RGB_SENSOR:
            rs_sensor = dev.first_color_sensor()
        else:
            raise ValueError(f"Unknown sensor: {sensor}")
        return rs_sensor
