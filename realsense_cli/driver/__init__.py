import os
from typing import TYPE_CHECKING, Optional

from realsense_cli.errors import RsCliError

if TYPE_CHECKING:
    from realsense_cli.driver.base import DriverProtocol

_driver: Optional["DriverProtocol"] = None


def get_driver() -> "DriverProtocol":
    global _driver
    if _driver is None:
        from realsense_cli.driver.realsense import Realsense

        match os.environ.get("RSCLI_DRIVER", "realsense"):
            case "realsense":
                _driver = Realsense()
            case "mock":
                from realsense_cli.driver.software import d435

                camera = d435()
                camera.start_frame_pump()
                _driver = Realsense(devices=[camera.device])
            case t:
                raise RsCliError(f"Unknown RSCLI_DRIVER '{t}'. Valid drivers: realsense, mock")
    return _driver


def reset_driver() -> None:
    global _driver
    _driver = None
