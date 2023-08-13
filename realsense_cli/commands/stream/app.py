from typing import Annotated

import typer

from realsense_cli.driver import get_driver
from realsense_cli.model import Sensor
from realsense_cli.utils.rich import list_profiles

stream_app = typer.Typer(help="Stream options", no_args_is_help=True)


@stream_app.command(name="list", help="List supported streams for given SENSOR")
def stream_list(
    sensor: Annotated[
        Sensor, typer.Argument(help="The sensor to configure", show_default=False)
    ],
) -> None:
    driver = get_driver()
    profiles = driver.list_streams(sensor)
    list_profiles(profiles, sensor)
