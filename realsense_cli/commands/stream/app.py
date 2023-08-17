from typing import Annotated, Optional

import typer

from realsense_cli.driver import get_driver
from realsense_cli.model import CliSensor, CliStream
from realsense_cli.utils.rich import list_profiles

stream_app = typer.Typer(help="Stream options", no_args_is_help=True)


@stream_app.command(name="list", help="List supported streams for given SENSOR")
def stream_list(
    sensor: Annotated[
        CliSensor, typer.Argument(help="Sensor to query for streams", show_default=False)
    ],
) -> None:
    driver = get_driver()
    profiles = driver.list_streams(sensor.rs_enum)
    list_profiles(profiles, sensor.rs_enum)

