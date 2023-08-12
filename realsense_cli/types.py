from dataclasses import dataclass
from enum import Enum
from typing import Any


@dataclass
class DeviceInfo:
    name: str
    serial: str
    fw: str
    connection: str
    sensors: list[str]


class Sensor(Enum):
    STEREO_MODULE = "Stereo Module"
    RGB_SENSOR = "RGB Sensor"
    # MOTION = "motion"


@dataclass(frozen=True)
class Option:
    name: str
    description: str
    min_value: Any
    max_value: Any
    step: Any
    default_value: Any


class Stream(Enum):
    DEPTH = "Depth"
    INFRARED = "Infrared 1"
    INFRARED2 = "Infrared 2"
    COLOR = "Color"


@dataclass(frozen=True)
class Profile:
    stream: Stream
    resolution: tuple[int, int]
    fps: int
    format: str
