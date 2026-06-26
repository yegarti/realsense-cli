from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, NamedTuple

from loguru import logger

if TYPE_CHECKING:
    import pyrealsense2 as rs


@dataclass
class DeviceInfo:
    name: str
    serial: str
    fw: str
    connection: str
    sensors: list[str]


Sensor = str  # sensor name as reported by pyrealsense2, e.g. "Stereo Module"
Stream = str  # stream name as reported by pyrealsense2, e.g. "Depth"


@dataclass(frozen=True)
class Option:
    name: str
    description: str
    min_value: Any
    max_value: Any
    step: Any
    default_value: Any
    vtype: type


_SENSOR_ALIASES: dict[str, str] = {
    "depth": "Stereo Module",
    "color": "RGB Camera",
    "motion": "Motion Module",
}

_STREAM_ALIASES: dict[str, str] = {
    "depth": "Depth",
    "infrared": "Infrared 1",
    "infrared2": "Infrared 2",
    "color": "Color",
    "gyro": "Gyro",
    "accel": "Accel",
}


def resolve_sensor_name(name: str) -> str:
    return _SENSOR_ALIASES.get(name.lower(), name)


def resolve_stream_name(name: str) -> str:
    return _STREAM_ALIASES.get(name.lower(), name)


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
            case "Infrared 1":
                index = 1
            case "Infrared 2":
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
            stream = resolve_stream_name(parts[0])
            res = Resolution.from_string(parts[1] if len(parts) > 1 else "0x0")
            fps = int(parts[2] if len(parts) > 2 else 0)
            fmt = parts[3] if len(parts) > 3 else "any"
            return cls(stream, res, fps, fmt)
        except Exception as e:
            logger.error(e)
            raise ValueError(f"Failed to parse profile: '{profile}'")

    @classmethod
    def from_rs(cls, profile: Any) -> "Profile":
        import pyrealsense2 as rs

        width, height = 0, 0
        if profile.is_video_stream_profile():
            vsp = profile.as_video_stream_profile()
            width, height = vsp.width(), vsp.height()

        return cls(
            stream=profile.stream_name(),
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
