import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, NamedTuple, Optional, Literal

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
    SAFETY_CAMERA = "Safety Camera"
    DEPTH_MAPPING_CAMERA = "Depth Mapping Camera"


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
    SAFETY = "Safety"
    LABELED_POINT_CLOUD = "Labeled Point Cloud"
    OCCUPANCY = "Occupancy"


class CliStream(Enum):
    DEPTH = "depth"
    INFRARED = "infrared"
    INFRARED2 = "infrared2"
    COLOR = "color"
    GYRO = "gyro"
    ACCEL = "accel"
    SAFETY = "safety"
    LABELED_POINT_CLOUD = "lpc"
    OCCUPANCY = "occupancy"

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
            case self.SAFETY:
                return Stream.SAFETY
            case self.LABELED_POINT_CLOUD:
                return Stream.LABELED_POINT_CLOUD
            case self.OCCUPANCY:
                return Stream.OCCUPANCY
            case _:
                raise RuntimeError(f"Unmatched stream: {self}")


class CliSensor(Enum):
    DEPTH = "depth"
    COLOR = "color"
    MOTION = "motion"
    SAFETY = "safety"
    DEPTH_MAPPING = "depth_mapping"

    @property
    def rs_enum(self) -> Sensor:
        match self:
            case self.DEPTH:
                return Sensor.STEREO_MODULE
            case self.COLOR:
                return Sensor.RGB_CAMERA
            case self.MOTION:
                return Sensor.MOTION_SENSOR
            case self.SAFETY:
                return Sensor.SAFETY_CAMERA
            case self.DEPTH_MAPPING:
                return Sensor.DEPTH_MAPPING_CAMERA
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


class SafetyMaskingZone(NamedTuple):
    attributes: int
    pixels: list[tuple[int, int]]
    minimal_range: float = 0


class SafetyZone(NamedTuple):
    points: list[tuple[float, float]]
    trigger_confidence: int = 1


@dataclass
class SafetyPreset:
    safety_zones: list[SafetyZone]
    masking_zones: list[SafetyMaskingZone]
    rotation: list[list[float]]
    translation: list[float]
    robot_height: float
    grid_cell_size: float
    surface_height: float
    surface_inclination: float
    safety_trigger_duration: float
    raw_form: Optional[str] = field(repr=False, default="N/A")

    @classmethod
    def from_json(cls, data: str):
        jdata = json.loads(data)
        preset = cls(**jdata)
        preset.safety_zones = [SafetyZone(**zone) for zone in jdata["safety_zones"]]
        preset.masking_zones = [SafetyMaskingZone(**zone) for zone in jdata["masking_zones"]]
        return preset

    def to_json(self) -> str:
        data = asdict(self)
        del data["raw_form"]
        data["safety_zones"] = [s._asdict() for s in data["safety_zones"]]
        data["masking_zones"] = [s._asdict() for s in data["masking_zones"]]
        return json.dumps(data)


class SafetyPin(NamedTuple):
    name: str
    direction: Literal["input", "output"]


@dataclass
class SafetyInterfaceConfig:
    input_delay: float
    pins: dict[str, SafetyPin]

    @classmethod
    def from_json(cls, data: str):
        jdata = json.loads(data)
        config = cls(**jdata)
        config.pins = {n: SafetyPin(**pin) for n, pin in jdata["pins"].items()}
        return config

    def to_json(self) -> str:
        data = asdict(self)
        data["pins"] = {n: p._asdict() for n, p in data["pins"].items()}
        return json.dumps(data)
