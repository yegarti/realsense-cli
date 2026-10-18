"""
Simulated cameras built on `rs.software_device`.

The software device runs through the real `Realsense` driver code, so tests exercise the same
pyrealsense2 calls as production. It produces no frames on its own: call
`SoftwareCamera.push_frames()` to feed every active stream one frame.
"""

from dataclasses import dataclass, field
from itertools import count

import pyrealsense2 as rs

from realsense_cli.types import DeviceInfo, Option, Profile, Resolution

_BYTES_PER_PIXEL: dict[str, int] = {"z16": 2, "y8": 1, "rgb8": 3}


@dataclass
class SensorSpec:
    name: str
    profiles: list[Profile]
    options: list[Option] = field(default_factory=list)
    read_only_options: dict[str, float] = field(default_factory=dict)


class SoftwareCamera:
    def __init__(self, info: DeviceInfo, sensors: list[SensorSpec]):
        self.info = info
        self.device = rs.software_device()
        # pyrealsense2 < 2.55 pre-registers a name, and registering again appends to it
        if self.device.supports(rs.camera_info.name):
            self.device.update_info(rs.camera_info.name, info.name)
        else:
            self.device.register_info(rs.camera_info.name, info.name)
        self.device.register_info(rs.camera_info.serial_number, info.serial)
        self.device.register_info(rs.camera_info.firmware_version, info.fw)
        self.device.register_info(rs.camera_info.usb_type_descriptor, info.connection)

        self._sensors: list[rs.software_sensor] = []
        self._frame_numbers = count()
        uid = count()
        for spec in sensors:
            sensor = self.device.add_sensor(spec.name)
            self._sensors.append(sensor)
            for profile in spec.profiles:
                _add_stream(sensor, profile, next(uid))
            for option in spec.options:
                rng = rs.option_range()
                rng.min = option.min_value
                rng.max = option.max_value
                rng.step = option.step
                rng.default = option.default_value
                sensor.add_option(getattr(rs.option, option.name), rng, True)
            for name, value in spec.read_only_options.items():
                sensor.add_read_only_option(getattr(rs.option, name), value)

    def push_frames(self) -> None:
        """Push one frame to every stream currently started on the device."""
        frame_number = next(self._frame_numbers)
        timestamp = frame_number * 1000 / 30
        for sensor in self._sensors:
            for profile in sensor.get_active_streams():
                if profile.is_motion_stream_profile():
                    frame = rs.software_motion_frame()
                    frame.data = rs.vector()
                    frame.profile = profile.as_motion_stream_profile()
                    push = sensor.on_motion_frame
                else:
                    vsp = profile.as_video_stream_profile()
                    bpp = _BYTES_PER_PIXEL[vsp.format().name]
                    frame = rs.software_video_frame()
                    frame.pixels = bytearray(vsp.width() * vsp.height() * bpp)
                    frame.bpp = bpp
                    frame.stride = vsp.width() * bpp
                    frame.profile = vsp
                    push = sensor.on_video_frame
                frame.frame_number = frame_number
                frame.timestamp = timestamp
                frame.domain = rs.timestamp_domain.hardware_clock
                push(frame)


def _add_stream(sensor: rs.software_sensor, profile: Profile, uid: int) -> None:
    stream_type = getattr(rs.stream, profile.stream.split()[0].lower())
    index = max(profile.index, 0)
    fmt = getattr(rs.format, profile.format.lower())
    if stream_type in (rs.stream.gyro, rs.stream.accel):
        stream = rs.motion_stream()
    else:
        stream = rs.video_stream()
        stream.width = profile.resolution.width
        stream.height = profile.resolution.height
        stream.bpp = _BYTES_PER_PIXEL[profile.format.lower()]
    stream.type = stream_type
    stream.index = index
    stream.uid = uid
    stream.fps = profile.fps
    stream.fmt = fmt
    if isinstance(stream, rs.motion_stream):
        sensor.add_motion_stream(stream)
    else:
        sensor.add_video_stream(stream)


def _video(stream: str, fps: int, fmt: str, index: int = -1) -> Profile:
    return Profile(stream, Resolution(640, 480), fps, fmt, index)


D435 = DeviceInfo(
    name="Intel RealSense D435",
    serial="012345678",
    fw="5.15.0.0",
    connection="3.2",
    sensors=["Stereo Module", "RGB Camera", "Motion Module"],
)

D435_SENSORS: list[SensorSpec] = [
    SensorSpec(
        name="Stereo Module",
        profiles=[
            *(_video("Depth", fps, "z16", 0) for fps in (6, 15, 30)),
            *(_video("Infrared 1", fps, "y8") for fps in (15, 30)),
            _video("Infrared 2", 30, "y8"),
        ],
        options=[
            Option("exposure", "", 1.0, 200000.0, 1.0, 8500.0, int),
            Option("enable_auto_exposure", "", 0.0, 1.0, 1.0, 1.0, int),
            Option("laser_power", "", 0.0, 360.0, 30.0, 150.0, int),
            Option("depth_units", "", 0.00001, 0.001, 0.00001, 0.001, float),
        ],
        read_only_options={"asic_temperature": 40.0},
    ),
    SensorSpec(
        name="RGB Camera",
        profiles=[_video("Color", fps, "rgb8", 0) for fps in (6, 15, 30)],
        options=[Option("brightness", "", -64.0, 64.0, 1.0, 0.0, int)],
    ),
    SensorSpec(
        name="Motion Module",
        profiles=[
            Profile("Gyro", Resolution(0, 0), 200, "motion_xyz32f", 0),
            Profile("Accel", Resolution(0, 0), 63, "motion_xyz32f", 0),
        ],
    ),
]


def d435() -> SoftwareCamera:
    return SoftwareCamera(D435, D435_SENSORS)
