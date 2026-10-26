"""
Simulated cameras built on `rs.software_device`.

The software device runs through the real `Realsense` driver code, so tests exercise the same
pyrealsense2 calls as production. It produces no frames on its own: call
`SoftwareCamera.push_frames()` to feed every active stream one frame, or
`start_frame_pump()` to keep feeding them from a background thread.

The last profile listed for each stream in a `SensorSpec` is that stream's default.

A software device keeps extrinsics per profile, where a real device keeps them per stream: each
stream's profiles are linked to each other, so extrinsics registered between two streams reach
every profile of both.
"""

import threading
import time
from collections.abc import Collection
from dataclasses import dataclass, field
from itertools import count

import pyrealsense2 as rs

from realsense_cli.types import (
    DeviceInfo,
    Extrinsics,
    Intrinsics,
    Option,
    Profile,
    Resolution,
    Sensor,
    Stream,
)

_BYTES_PER_PIXEL: dict[str, int] = {"z16": 2, "y8": 1, "rgb8": 3, "bgr8": 3, "yuyv": 2}


@dataclass
class SensorSpec:
    name: str
    profiles: list[Profile]
    options: list[Option] = field(default_factory=list)
    read_only_options: dict[str, float] = field(default_factory=dict)
    intrinsics: dict[str, Intrinsics] = field(default_factory=dict)  # keyed by stream name


class SoftwareCamera:
    def __init__(
        self,
        info: DeviceInfo,
        sensors: list[SensorSpec],
        camera_info: dict[str, str] | None = None,
        extrinsics: list[Extrinsics] | None = None,
    ):
        """
        CAMERA_INFO registers more camera info fields on top of those INFO holds, keyed by
        their `rs.camera_info` name. EXTRINSICS are registered between the streams they name
        """
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
        # fields the installed SDK doesn't know, such as imu_type on 2.56, are left out
        for name, value in (camera_info or {}).items():
            if name in rs.camera_info.__members__:
                self.device.register_info(rs.camera_info.__members__[name], value)

        self._sensors: list[rs.software_sensor] = []
        self._frame_numbers = count()
        uid = count()
        stream_profiles: dict[str, list[rs.stream_profile]] = {}
        for spec in sensors:
            sensor = self.device.add_sensor(spec.name)
            self._sensors.append(sensor)
            defaults = {p.stream: p for p in spec.profiles}
            for profile in spec.profiles:
                rs_profile = _add_stream(
                    sensor,
                    profile,
                    next(uid),
                    defaults[profile.stream] is profile,
                    spec.intrinsics.get(profile.stream),
                )
                stream_profiles.setdefault(profile.stream, []).append(rs_profile)
            for option in spec.options:
                rng = rs.option_range()
                rng.min = option.min_value
                rng.max = option.max_value
                rng.step = option.step
                rng.default = option.default_value
                sensor.add_option(getattr(rs.option, option.name), rng, True)
            for name, value in spec.read_only_options.items():
                sensor.add_read_only_option(getattr(rs.option, name), value)

        for first, *others in stream_profiles.values():
            for other in others:
                first.register_extrinsics_to(other, _rs_extrinsics(_IDENTITY, (0, 0, 0)))
        for ext in extrinsics or []:
            source, target = stream_profiles[ext.source][0], stream_profiles[ext.target][0]
            source.register_extrinsics_to(target, _rs_extrinsics(ext.rotation, ext.translation))

    def start_frame_pump(self, fps: int = 30) -> None:
        """Push frames to active streams at FPS from a daemon thread until exit."""

        def pump():
            while True:
                self.push_frames()
                time.sleep(1 / fps)

        threading.Thread(target=pump, name="software-camera-pump", daemon=True).start()

    def push_frames(self, streams: Collection[str] | None = None) -> None:
        """
        Push one frame to every stream currently started on the device, or only to those
        named in STREAMS
        """
        frame_number = next(self._frame_numbers)
        timestamp = frame_number * 1000 / 30
        for sensor in self._sensors:
            for profile in sensor.get_active_streams():
                if streams is not None and profile.stream_name() not in streams:
                    continue
                if profile.is_motion_stream_profile():
                    motion = rs.software_motion_frame()
                    motion.data = rs.vector()
                    motion.profile = profile.as_motion_stream_profile()
                    motion.frame_number = frame_number
                    motion.timestamp = timestamp
                    motion.domain = rs.timestamp_domain.hardware_clock
                    sensor.on_motion_frame(motion)
                else:
                    vsp = profile.as_video_stream_profile()
                    bpp = _BYTES_PER_PIXEL[vsp.format().name]
                    video = rs.software_video_frame()
                    video.pixels = bytearray(
                        pixels(vsp.width() * vsp.height() * bpp, frame_number)
                    )
                    video.bpp = bpp
                    video.stride = vsp.width() * bpp
                    video.profile = vsp
                    video.frame_number = frame_number
                    video.timestamp = timestamp
                    video.domain = rs.timestamp_domain.hardware_clock
                    sensor.on_video_frame(video)


_BYTE_RAMP = bytes(range(256))


def pixels(size: int, frame_number: int) -> bytes:
    """
    The SIZE bytes of pixel data pushed in frame FRAME_NUMBER: a ramp of byte values that
    starts one higher in each frame
    """
    start = frame_number % 256
    ramp = _BYTE_RAMP * (size // 256 + 2)
    return ramp[start : start + size]


def _add_stream(
    sensor: rs.software_sensor,
    profile: Profile,
    uid: int,
    is_default: bool,
    intrinsics: Intrinsics | None,
) -> rs.stream_profile:
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
        if intrinsics is not None:
            stream.intrinsics = _rs_intrinsics(profile.resolution, intrinsics)
    stream.type = stream_type
    stream.index = index
    stream.uid = uid
    stream.fps = profile.fps
    stream.fmt = fmt
    if isinstance(stream, rs.motion_stream):
        return sensor.add_motion_stream(stream, is_default)
    return sensor.add_video_stream(stream, is_default)


def _rs_intrinsics(resolution: Resolution, intrinsics: Intrinsics) -> rs.intrinsics:
    rs_intrinsics = rs.intrinsics()
    rs_intrinsics.width, rs_intrinsics.height = resolution
    rs_intrinsics.ppx, rs_intrinsics.ppy = intrinsics.ppx, intrinsics.ppy
    rs_intrinsics.fx, rs_intrinsics.fy = intrinsics.fx, intrinsics.fy
    rs_intrinsics.model = rs.distortion.__members__[intrinsics.model]
    rs_intrinsics.coeffs = list(intrinsics.coeffs)
    return rs_intrinsics


def _rs_extrinsics(
    rotation: tuple[float, ...], translation: tuple[float, ...]
) -> rs.extrinsics:
    rs_extrinsics = rs.extrinsics()
    rs_extrinsics.rotation = list(rotation)
    rs_extrinsics.translation = list(translation)
    return rs_extrinsics


def _video(stream: str, fps: int, fmt: str, index: int = -1) -> Profile:
    return Profile(stream, Resolution(640, 480), fps, fmt, index)


D435 = DeviceInfo(
    name="Intel RealSense D435",
    serial="012345678",
    fw="5.15.0.0",
    connection="3.2",
    sensors=[Sensor.STEREO_MODULE, Sensor.RGB_CAMERA, Sensor.MOTION_MODULE],
)

D435_CAMERA_INFO: dict[str, str] = {
    "recommended_firmware_version": "5.16.0.1",
    "physical_port": "/sys/devices/pci0000:00/usb2/2-1",
    "product_id": "0B07",
    "camera_locked": "YES",
    "connection_type": "USB",
    "product_line": "D400",
    "asic_serial_number": "123456789012",
    "imu_type": "BMI055",
}

_D435_DEPTH_INTRINSICS = Intrinsics(320.5, 240.25, 385.5, 385.12345, "brown_conrady", (0,) * 5)

D435_SENSORS: list[SensorSpec] = [
    SensorSpec(
        name=Sensor.STEREO_MODULE,
        profiles=[
            *(_video(Stream.DEPTH, fps, "z16", 0) for fps in (6, 15, 30)),
            *(_video(Stream.INFRARED, fps, "y8") for fps in (15, 30)),
            _video(Stream.INFRARED2, 30, "y8"),
        ],
        options=[
            Option("exposure", "", 1.0, 200000.0, 1.0, 8500.0, int),
            Option("enable_auto_exposure", "", 0.0, 1.0, 1.0, 1.0, int),
            Option("laser_power", "", 0.0, 360.0, 30.0, 150.0, int),
            Option("depth_units", "", 0.00001, 0.001, 0.00001, 0.001, float),
        ],
        read_only_options={"asic_temperature": 40.0},
        intrinsics=dict.fromkeys(
            (Stream.DEPTH, Stream.INFRARED, Stream.INFRARED2), _D435_DEPTH_INTRINSICS
        ),
    ),
    SensorSpec(
        name=Sensor.RGB_CAMERA,
        profiles=[
            *(_video(Stream.COLOR, fps, "rgb8", 0) for fps in (6, 15, 30)),
            _video(Stream.COLOR, 30, "yuyv"),
        ],
        options=[Option("brightness", "", -64.0, 64.0, 1.0, 0.0, int)],
        intrinsics={
            Stream.COLOR: Intrinsics(
                321.75,
                243.5,
                615.25,
                615.5,
                "inverse_brown_conrady",
                (0.125, -0.25, 0.001, -0.0005, 0.0625),
            )
        },
    ),
    SensorSpec(
        name=Sensor.MOTION_MODULE,
        profiles=[
            Profile(Stream.GYRO, Resolution(0, 0), 200, "motion_xyz32f", 0),
            Profile(Stream.ACCEL, Resolution(0, 0), 63, "motion_xyz32f", 0),
        ],
    ),
]


_IDENTITY = (1, 0, 0, 0, 1, 0, 0, 0, 1)

D435_EXTRINSICS: list[Extrinsics] = [
    Extrinsics(Stream.DEPTH, Stream.INFRARED, _IDENTITY, (0, 0, 0)),
    Extrinsics(Stream.DEPTH, Stream.INFRARED2, _IDENTITY, (-0.05, 0, 0)),
    Extrinsics(Stream.DEPTH, Stream.COLOR, _IDENTITY, (0.0147, 0.0001, 0.0004)),
]


def d435() -> SoftwareCamera:
    return SoftwareCamera(D435, D435_SENSORS, D435_CAMERA_INFO, D435_EXTRINSICS)


def d435_sensor(name: str) -> SensorSpec:
    return next(s for s in D435_SENSORS if s.name == name)
