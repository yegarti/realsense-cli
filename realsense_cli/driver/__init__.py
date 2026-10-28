import os
from pathlib import Path
from tempfile import TemporaryDirectory
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


def open_recording(path: Path) -> tuple["DriverProtocol", float]:
    """
    The driver over the SDK's playback device for the recording at PATH, and the recording's
    duration in seconds. It reaches no connected device: the playback device is the only one
    """
    import pyrealsense2 as rs

    from realsense_cli.driver.realsense import Realsense

    with TemporaryDirectory() as tmp:
        if path.suffix != ".db3":
            # the SDK picks its reader by a case-sensitive suffix: `.DB3` goes to the ROS1 one
            link = Path(tmp) / "recording.db3"
            link.symlink_to(path)
            path = link
        # reads the whole header, so the link may go once it returns
        playback = rs.context().load_device(str(path))
    return Realsense(devices=[playback]), playback.get_duration().total_seconds()
