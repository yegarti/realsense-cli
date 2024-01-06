from dataclasses import dataclass
from enum import Enum
from typing import Any, NamedTuple

from loguru import logger

import pyrealsense2 as rs  # type: ignore


@dataclass
class DeviceInfo:
    name: str
    serial: str
    fw: str
    connection: str
    sensors: list[str]


class Sensor(Enum):
    STEREO_MODULE = "Stereo Module"
    RGB_CAMERA = "RGB Camera"
    MOTION_SENSOR = "Motion Module"


@dataclass(frozen=True)
class Option:
    name: str
    description: str
    min_value: Any
    max_value: Any
    step: Any
    default_value: Any
    vtype: type


class Stream(Enum):
    DEPTH = "Depth"
    INFRARED = "Infrared 1"
    INFRARED2 = "Infrared 2"
    COLOR = "Color"
    GYRO = "Gyro"
    ACCEL = "Accel"


class CliStream(Enum):
    DEPTH = "depth"
    INFRARED = "infrared"
    INFRARED2 = "infrared2"
    COLOR = "color"
    GYRO = "gyro"
    ACCEL = "accel"

    @property
    def rs_enum(self) -> Stream:
        match self:
            case self.DEPTH:
                return Stream.DEPTH
            case self.GYRO:
                return Stream.GYRO
            case self.ACCEL:
                return Stream.ACCEL
            case self.COLOR:
                return Stream.COLOR
            case self.INFRARED:
                return Stream.INFRARED
            case self.INFRARED2:
                return Stream.INFRARED2
            case _:
                raise RuntimeError(f"Unmatched stream: {self}")


class CliSensor(Enum):
    DEPTH = "depth"
    COLOR = "color"
    MOTION = "motion"

    @property
    def rs_enum(self) -> Sensor:
        match self:
            case self.DEPTH:
                return Sensor.STEREO_MODULE
            case self.COLOR:
                return Sensor.RGB_CAMERA
            case self.MOTION:
                return Sensor.MOTION_SENSOR
            case _:
                raise RuntimeError(f"Unmatched sensor: {self}")


class Resolution(NamedTuple):
    width: int
    height: int

    @classmethod
    def from_string(cls, res: str):
        try:
            width, height = [int(n) for n in res.split("x")]
        except Exception:
            raise ValueError(f"Failed to parse resolution provided: {res}")
        return Resolution(width, height)

    def __str__(self):
        return f"{self.width}x{self.height}"


@dataclass(frozen=True)
class Profile:
    stream: Stream
    resolution: Resolution = Resolution(0, 0)
    fps: int = 0
    format: str = "any"
    index: int = -1

    def __post_init__(self):
        match self.stream:
            case Stream.INFRARED:
                index = 1
            case Stream.INFRARED2:
                index = 2
            case _:
                index = -1
        if self.index == -1:
            object.__setattr__(self, "index", index)

    def __str__(self):
        return f"{self.stream} ({self.index}) {self.resolution} {self.format} @ {self.fps}"

    @classmethod
    def from_string(cls, profile: str) -> "Profile":
        logger.debug(f"parsing profile from string: {profile}")
        try:
            parts = profile.split("-")
            stream = CliStream(parts[0]).rs_enum
            res = Resolution.from_string(parts[1] if len(parts) > 1 else "0x0")
            fps = int(parts[2] if len(parts) > 2 else 0)
            fmt = parts[3] if len(parts) > 3 else "any"
            return cls(stream, res, fps, fmt)
        except Exception as e:
            logger.error(e)
            raise ValueError(f"Failed to parse profile: '{profile}'")

    @classmethod
    def from_rs(cls, profile: rs.stream_profile) -> "Profile":
        """Convert pyrealsense2 profile to Profile"""
        width, height = 0, 0
        if profile.is_video_stream_profile():
            vsp: rs.video_stream_profile = profile.as_video_stream_profile()
            width, height = vsp.width(), vsp.height()

        return cls(
            stream=Stream(profile.stream_name()),
            resolution=Resolution(width, height),
            fps=profile.fps(),
            format=profile.format().name,
            index=profile.stream_index(),
        )


@dataclass
class Frame:
    profile: Profile
    timestamp: float
    index: int
    metadata: dict[str, Any]


FrameSet = dict[Stream, Frame]
