from realsense_cli.driver.base import Driver
from realsense_cli.model import DeviceInfo, Sensor, Option, Profile, Stream, Resolution

import pyrealsense2 as rs


class Realsense(Driver):
    def __init__(self):
        self._ctx: rs.context = rs.context()
        self._devices: list[rs.device] = []
        self._sensors: dict[rs.device, dict[Sensor, rs.sensor]] = {}
        self._origin_sensor: dict[rs.device, dict[Stream, Sensor]] = {}
        self._setup()

    def _setup(self) -> None:
        for dev in self._ctx.devices:
            self._devices.append(dev)
            self._sensors[dev] = {}
            self._origin_sensor[dev] = {}

            rs_sensor: rs.sensor
            for rs_sensor in dev.sensors:
                sensor: Sensor = Sensor(rs_sensor.get_info(rs.camera_info.name))
                self._sensors[dev][sensor] = rs_sensor

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
                    resolution=Resolution(width, height),
                    fps=profile.fps(),
                    format=profile.format().name.upper(),
                )
            )
        return res

    def _get_sensor(self, sensor: Sensor) -> rs.sensor:
        # TODO - refactor to use directly in functions
        dev = self._devices[0]
        return self._sensors[dev][sensor]
