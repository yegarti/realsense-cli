from collections import Counter
from itertools import count
from typing import NamedTuple

import pyrealsense2 as rs

from realsense_cli.types import DeviceInfo, Sensor, Profile, Stream, Resolution, Option


MOCK_DEVICE: DeviceInfo = DeviceInfo(
    name="Intel RealSense D435",
    serial="012345678",
    fw="5.15.0.0",
    connection="3.2",
    sensors=[
        "Stereo Module",
        "RGB Camera",
    ],
)

MOCK_SENSORS: dict = {
    "profiles": {
        Sensor.STEREO_MODULE: [
            Profile(Stream.DEPTH, Resolution(640, 480), 15, "Z16", 0),
            Profile(Stream.DEPTH, Resolution(640, 480), 30, "Z16", 0),
        ]
    },
    "options": {
        Sensor.STEREO_MODULE: [
            Option("exposure", "", 0.0, 10000.0, 1.0, 8500, int),
            Option("depth_units", "", 0.0, 10000.0, 1.0, 8500, int),
            Option("laser_power", "", 0.0, 360.0, 1.0, 120.0, int),
            Option("enable_auto_exposure", "", 0.0, 1.0, 1.0, 1.0, int),
        ]
    },
}


def build_software_device(
    device: DeviceInfo,
    profiles: dict[Sensor, list[Profile]],
    options: dict[Sensor, list[Option]],
):
    soft_dev = rs.software_device()
    # using `update_info` because already registered, register again would append
    soft_dev.update_info(rs.camera_info.name, device.name)
    soft_dev.register_info(rs.camera_info.serial_number, device.serial)
    soft_dev.register_info(rs.camera_info.usb_type_descriptor, device.connection)
    soft_dev.register_info(rs.camera_info.firmware_version, device.fw)

    _sensors: dict[Sensor, rs.sensor] = {}
    stream_idx = count()
    for sensor in device.sensors:
        soft_sensor: rs.software_sensor = soft_dev.add_sensor(sensor)
        _sensors[Sensor(sensor)] = soft_sensor

    for sensor, profiles in profiles.items():
        soft_sensor = _sensors[sensor]
        for profile in profiles:
            stream = rs.video_stream()
            if profile.stream == Stream.DEPTH:
                stream.type = rs.stream.depth
                stream.bpp = 2
            stream.width = profile.resolution.width
            stream.height = profile.resolution.height
            stream.fmt = getattr(rs.format, profile.format.lower())
            stream.fps = profile.fps
            stream.index = profile.index
            stream.uid = next(stream_idx)
            soft_sensor.add_video_stream(stream)

    for sensor, options in options.items():
        soft_sensor = _sensors[sensor]
        for option in options:
            rng = rs.option_range()
            rng.min = option.min_value
            rng.max = option.max_value
            rng.step = option.step
            rng.default = option.default_value
            soft_sensor.add_option(getattr(rs.option, option.name), rng)
    return soft_dev
