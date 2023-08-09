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


class ConfigOpMode(Enum):
    SET = "set"
    GET = "get"
    LIST = "list"
