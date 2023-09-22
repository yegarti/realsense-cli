import os

from realsense_cli.driver.realsense import Realsense
from realsense_cli.driver.mock import MockDriver


def get_driver() -> Realsense:
    driver_type = os.environ.get("RSCLI_DRIVER", "realsense")
    match driver_type:
        case "realsense":
            return Realsense()
        case "mock":
            return MockDriver()
        case _:
            raise ValueError(f"Unknown driver: {driver_type}")
