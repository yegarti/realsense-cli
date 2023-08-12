from abc import ABC, abstractmethod

from realsense_cli.types import DeviceInfo, Sensor, Option
from realsense_cli.utils.singleton import Singleton


class Driver(ABC, metaclass=Singleton):
    @abstractmethod
    def query_devices(self) -> list[DeviceInfo]:
        """
        Query connected devices
        """

    @abstractmethod
    def list_controls(self, sensor: Sensor) -> list[Option]:
        """
        List controls supported by SENSOR
        """

    @abstractmethod
    def get_control_values(self, sensor: Sensor, controls: list[str]) -> dict[str, float]:
        """
        Get values for CONTROLS from SENSOR
        """

    @abstractmethod
    def set_control_values(self, sensor: Sensor, control_values: dict[str, float]) -> None:
        """
        Set CONTROL_VALUES on SENSOR
        """

    @abstractmethod
    def list_streams(self, sensor: Sensor) -> list:
        """
        List supported streams for SENSOR
        """
