from typing import Annotated

import typer

from realsense_cli.driver import get_driver
from realsense_cli.types import Sensor
from realsense_cli.utils.rich import list_options

config_app = typer.Typer(help="List connected devices", no_args_is_help=True)


@config_app.command(name="list")
def config_list(
    sensor: Annotated[
        Sensor, typer.Argument(help="The sensor to configure", show_default=False)
    ],
) -> None:
    driver = get_driver()
    controls = driver.list_controls(sensor)
    list_options(controls)
