from dataclasses import dataclass
from enum import Enum
from typing import Any
from typing import Any, NamedTuple


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


class CliSensor(Enum):
    DEPTH = "depth"
    COLOR = "color"

    @property
    def rs_enum(self) -> Sensor:
        match self:
            case self.DEPTH:
                return Sensor.STEREO_MODULE
            case self.COLOR:
                return Sensor.RGB_CAMERA


class Resolution(NamedTuple):
    width: int
    height: int

    @classmethod
    def from_string(cls, res: str):
        return Resolution(*res.split('x'))


@dataclass(frozen=True)
class Profile:
    stream: Stream
    resolution: Resolution = Resolution(0, 0)
    fps: int = 0
    format: str = 'any'
    index: int = -1

