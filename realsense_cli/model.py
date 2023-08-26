from dataclasses import dataclass
from enum import Enum
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
    RGB_CAMERA = "RGB Camera"
    MOTION_SENSOR = "Motion Sensor"


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
                raise RuntimeError(f'Unmatched stream: {self}')


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


class Resolution(NamedTuple):
    width: int
    height: int

    @classmethod
    def from_string(cls, res: str):
        return Resolution(*res.split("x"))


@dataclass(frozen=True)
class Profile:
    stream: Stream
    resolution: Resolution = Resolution(0, 0)
    fps: int = 0
    format: str = "any"
    index: int = -1

    @staticmethod
    def new(stream: Stream):
        if stream == Stream.INFRARED:
            index = 1
        elif stream == Stream.INFRARED2:
            index = 2
        else:
            index = -1
        return Profile(stream=stream, index=index)


@dataclass
class Frame:
    profile: Profile
    timestamp: float
    index: int


FrameSet = dict[Stream, Frame]
