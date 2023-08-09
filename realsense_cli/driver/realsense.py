from realsense_cli.driver.base import Driver
from realsense_cli.types import DeviceInfo

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

