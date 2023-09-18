# mypy: ignore-errors
from dataclasses import dataclass
from typing import Optional, Any

from realsense_cli.driver.base import Driver
from realsense_cli.types import (
    DeviceInfo,
    Sensor,
    Option,
    Profile,
    Stream,
    Resolution,
    FrameSet,
)

_default_config = {
    "devices": [
        DeviceInfo(
            name="Intel Realsense D435",
            serial="1234567890",
            fw="5.13.0.0",
            connection="3.2",
            sensors=["Stereo Module", "RGB Sensor"],
        ),
    ],
    "sensors": {
        Sensor.STEREO_MODULE: {
            "options": [
                Option(
                    name="exposure",
                    description="Exposure",
                    min_value=1.0,
                    max_value=200000.0,
                    step=1.0,
                    default_value=8500.0,
                ),
                Option(
                    name="enable_auto_exposure",
                    description="Auto Exposure",
                    min_value=0.0,
                    max_value=1.0,
                    step=1.0,
                    default_value=1.0,
                ),
                Option(
                    name="depth_units",
                    description="Depth Units",
                    min_value=0.00001,
                    max_value=0.001,
                    step=0.0001,
                    default_value=0.001,
                ),
            ],
            "profiles": [
                Profile(Stream.DEPTH, Resolution(640, 480), 6, "z16"),
                Profile(Stream.DEPTH, Resolution(640, 480), 15, "z16"),
                Profile(Stream.DEPTH, Resolution(640, 480), 30, "z16"),
                Profile(Stream.INFRARED, Resolution(640, 480), 15, "y8"),
                Profile(Stream.INFRARED, Resolution(640, 480), 30, "y8"),
                Profile(Stream.INFRARED2, Resolution(640, 480), 30, "y8"),
            ],
        },
        Sensor.RGB_CAMERA: {
            "options": [
                Option(
                    name="brightness",
                    description="Brightness",
                    min_value=-64.0,
                    max_value=64.0,
                    step=1.0,
                    default_value=0.0,
                ),
            ],
            "profiles": [
                Profile(Stream.COLOR, Resolution(640, 480), 6, "rgb8"),
                Profile(Stream.COLOR, Resolution(640, 480), 15, "rgb8"),
                Profile(Stream.COLOR, Resolution(640, 480), 30, "rgb8"),
            ],
        },
    },
}


@dataclass
class MockDriver(Driver):
    def __init__(self, config: Optional[dict] = None):
        if not config:
            config = _default_config
        self._config = config

    def query_devices(self) -> list[DeviceInfo]:
        return self._config["devices"]

    def list_controls(self, sensor: Sensor) -> list[Option]:
        return self._config["sensors"][sensor]["options"]

    def get_control_values(self, sensor: Sensor, controls: list[str]) -> dict[str, Any]:
        opts = self._config["sensors"][sensor]["options"]
        res = {}
        for control in controls:
            for opt in opts:
                if opt.name == control:
                    res[opt.name] = opt.default_value
        return res

    def set_control_values(self, sensor: Sensor, control_values: dict[str, Any]) -> None:
        pass

    def list_streams(self, sensor: Sensor) -> list[Profile]:
        return self._config["sensors"][sensor]["profiles"]

    def play(self, profiles: list[Profile]) -> None:
        pass

    def stop(self) -> None:
        pass

    def wait_for_frameset(self, timeout: float = 1.0) -> Optional[FrameSet]:
        pass

    @property
    def sensors(self) -> list[Sensor]:
        return list(self._config["sensors"].keys())

    @property
    def active_device(self) -> str:
        return self._config["devices"][0].serial

    @active_device.setter
    def active_device(self, serial: Optional[str] = None) -> str:
        pass
