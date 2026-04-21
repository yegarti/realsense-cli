import os
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from realsense_cli.driver.base import DriverProtocol

_driver: Optional["DriverProtocol"] = None


def get_driver() -> "DriverProtocol":
    global _driver
    if _driver is None:
        from realsense_cli.driver.mock import MockDriver
        from realsense_cli.driver.realsense import Realsense

        match os.environ.get("RSCLI_DRIVER", "realsense"):
            case "realsense":
                _driver = Realsense()
            case "mock":
                _driver = MockDriver()
            case t:
                raise ValueError(f"Unknown driver: {t}")
    return _driver


def reset_driver() -> None:
    global _driver
    _driver = None
