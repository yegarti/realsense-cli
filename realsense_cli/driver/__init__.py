import os

from realsense_cli.driver.mock import MockDriver
from realsense_cli.driver.realsense import Realsense


def get_driver():
    driver_type = os.environ.get("RSCLI_DRIVER", "realsense")
    match driver_type:
        case "realsense":
            return Realsense()
        case "mock":
            return MockDriver()
