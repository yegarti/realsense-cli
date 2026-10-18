from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from realsense_cli.driver.base import DriverProtocol

_driver: Optional["DriverProtocol"] = None


def get_driver() -> "DriverProtocol":
    global _driver
    if _driver is None:
        from realsense_cli.driver.realsense import Realsense

        _driver = Realsense()
    return _driver


def reset_driver() -> None:
    global _driver
    _driver = None
