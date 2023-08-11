from realsense_cli.driver.base import Driver
from realsense_cli.types import DeviceInfo, Sensor, Option

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
        dev = self._devices[0]
        rs_sensor: rs.sensor
        if sensor == Sensor.STEREO_MODULE:
            rs_sensor = dev.first_depth_sensor()
        elif sensor == Sensor.RGB_SENSOR:
            rs_sensor = dev.first_color_sensor()
        else:
            raise ValueError(f"Unknown sensor: {sensor}")

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

