import os
from typing import TYPE_CHECKING

from realsense_cli.errors import RsCliError

if TYPE_CHECKING:
    from realsense_cli.driver.base import DriverProtocol


def create_driver() -> "DriverProtocol":
    """
    Build the driver RSCLI_DRIVER selects. pyrealsense2 is imported here, not at module level,
    so commands that need no camera never load it.
    """
    from realsense_cli.driver.realsense import Realsense

    match os.environ.get("RSCLI_DRIVER", "realsense"):
        case "realsense":
            return Realsense()
        case "mock":
            from realsense_cli.driver.software import d435

            camera = d435()
            camera.start_frame_pump()
            return Realsense(devices=[camera.device])
        case t:
            raise RsCliError(f"Unknown RSCLI_DRIVER '{t}'. Valid drivers: realsense, mock")
