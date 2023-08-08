from abc import ABC, abstractmethod

from realsense_cli.types import DeviceInfo
from realsense_cli.utils.singleton import Singleton


class Driver(ABC, metaclass=Singleton):

    @abstractmethod
    def query_devices(self) -> list[DeviceInfo]:
        ...

