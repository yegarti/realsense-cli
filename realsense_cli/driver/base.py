from abc import ABC, abstractmethod
from typing import Optional

from realsense_cli.types import DeviceInfo, Sensor, Option, Profile, FrameSet
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
    def list_streams(self, sensor: Sensor) -> list[Profile]:
        """
        List supported streams for SENSOR
        """

    @abstractmethod
    def play(self, profiles: list[Profile]) -> None:
        """
        Start streaming selected profiles
        """

    @abstractmethod
    def stop(self) -> None:
        """
        Stop streaming
        """

    @abstractmethod
    def wait_for_frameset(self, timeout: float = 1.0) -> Optional[FrameSet]:
        """
        Get next frameset waiting in queue.
        return None when no frameset arrive after timeout
        """

    @property
    @abstractmethod
    def sensors(self) -> list[Sensor]:
        """Sensors"""

    @property
    @abstractmethod
    def active_device(self) -> str:
        """Read active device"""

    @active_device.setter
    def active_device(self, serial: Optional[str]):
        """Set active device"""
