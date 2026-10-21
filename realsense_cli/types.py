from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, NamedTuple

from loguru import logger

from realsense_cli.errors import InvalidProfile

if TYPE_CHECKING:
    import pyrealsense2 as rs


@dataclass
class DeviceInfo:
    name: str
    serial: str
    fw: str
    connection: str
    sensors: list[str]


# Sensor and stream names are typed `str` wherever they come from a device: a new camera can
# report a name these enums don't list, and it passes through unchanged. The enums name the
# sensors and streams the CLI knows, and compare equal to the matching plain string.


class Sensor(StrEnum):
    STEREO_MODULE = "Stereo Module"
    RGB_CAMERA = "RGB Camera"
    MOTION_MODULE = "Motion Module"


class Stream(StrEnum):
    DEPTH = "Depth"
    INFRARED = "Infrared 1"
    INFRARED2 = "Infrared 2"
    COLOR = "Color"
    GYRO = "Gyro"
    ACCEL = "Accel"


@dataclass(frozen=True)
class Option:
    name: str
    description: str
    min_value: float
    max_value: float
    step: float
    default_value: float
    vtype: type[int] | type[float]
    read_only: bool = False


_SENSOR_ALIASES: dict[str, Sensor] = {
    "depth": Sensor.STEREO_MODULE,
    "color": Sensor.RGB_CAMERA,
    "motion": Sensor.MOTION_MODULE,
}

_STREAM_ALIASES: dict[str, Stream] = {
    "depth": Stream.DEPTH,
    "infrared": Stream.INFRARED,
    "infrared2": Stream.INFRARED2,
    "color": Stream.COLOR,
    "gyro": Stream.GYRO,
    "accel": Stream.ACCEL,
}


def resolve_sensor_name(name: str) -> str:
    return _SENSOR_ALIASES.get(name.lower(), name)


def sensor_label(name: str) -> str:
    """
    NAME followed by its aliases, e.g. 'Stereo Module (depth)'
    """
    aliases = [alias for alias, sensor in _SENSOR_ALIASES.items() if sensor == name]
    return f"{name} ({', '.join(aliases)})" if aliases else name


def resolve_stream_name(name: str) -> str:
    return _STREAM_ALIASES.get(name.lower(), name)


class Resolution(NamedTuple):
    width: int
    height: int

    @classmethod
    def from_string(cls, res: str) -> "Resolution":
        try:
            width, height = [int(n) for n in res.split("x")]
        except Exception as e:
            raise ValueError(f"Failed to parse resolution provided: {res}") from e
        return Resolution(width, height)

    def __str__(self):
        return f"{self.width}x{self.height}"


@dataclass(frozen=True)
class Profile:
    stream: str
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
            stream = resolve_stream_name(parts[0])
            res = Resolution.from_string(parts[1] if len(parts) > 1 else "0x0")
            fps = int(parts[2] if len(parts) > 2 else 0)
            fmt = parts[3] if len(parts) > 3 else "any"
            return cls(stream, res, fps, fmt)
        except Exception as e:
            logger.debug(e)
            # Not a ValueError: click would turn that into a generic "invalid value" message
            raise InvalidProfile(
                f"Failed to parse profile '{profile}'. Expected STREAM-RESOLUTION-FPS-FORMAT, "
                f"e.g. depth-640x480-30-z16. Stream aliases: {', '.join(_STREAM_ALIASES)}"
            ) from e

    @classmethod
    def from_rs(cls, profile: "rs.stream_profile") -> "Profile":

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


@dataclass(frozen=True)
class Intrinsics:
    """
    A video profile's calibration: principal point and focal length in pixels, and the lens
    distortion MODEL (an `rs.distortion` name) with its COEFFS
    """

    ppx: float
    ppy: float
    fx: float
    fy: float
    model: str
    coeffs: tuple[float, ...]


@dataclass(frozen=True)
class StreamIntrinsics:
    """
    INTRINSICS shared by a stream's profiles at one resolution, which differ in FORMATS and FPS.
    None when the SDK has no intrinsics for them
    """

    stream: str
    index: int
    resolution: Resolution
    formats: tuple[str, ...]
    fps: tuple[int, ...]
    intrinsics: Intrinsics | None


@dataclass(frozen=True)
class Extrinsics:
    """
    The transform of a point from stream SOURCE's coordinate frame to stream TARGET's: a 3x3
    ROTATION in column-major order, then a TRANSLATION in meters
    """

    source: str
    target: str
    rotation: tuple[float, ...]
    translation: tuple[float, ...]


@dataclass
class Calibration:
    intrinsics: list[StreamIntrinsics]
    extrinsics: list[Extrinsics]


@dataclass
class Frame:
    profile: Profile
    timestamp: float
    index: int
    metadata: dict[str, int]


FrameSet = dict[str, Frame]  # keyed by stream name
