from typing import Annotated, Optional

import typer

from realsense_cli.driver import get_driver
from realsense_cli.types import CliSensor
from realsense_cli.utils.rich import list_options, list_options_values

config_app = typer.Typer(help="Configure controls", no_args_is_help=True)


@config_app.command(
    name="list",
    help="List SENSOR supported controls with description and possible values for given sensor",
)
def config_list(
    sensor: Annotated[
        CliSensor, typer.Argument(help="The sensor to configure", show_default=False)
    ],
) -> None:
    driver = get_driver()
    controls = driver.list_controls(sensor.rs_enum)
    list_options(controls)


@config_app.command(
    name="get", help="Get control values for given SENSOR or all controls if '--all' is used"
)
def config_get(
    sensor: Annotated[
        CliSensor, typer.Argument(help="The sensor to configure", show_default=False)
    ],
    controls: Annotated[Optional[list[str]], typer.Argument(help="Controls to query")] = None,
    all_controls: Annotated[
        bool, typer.Option("--all/", help="Query all supported controls")
    ] = False,
):
    driver = get_driver()
    if all_controls:
        controls = [opt.name for opt in driver.list_controls(sensor.rs_enum)]
    control_values = driver.get_control_values(sensor.rs_enum, controls)
    list_options_values(control_values)


@config_app.command(name="set", help="Set controls for given SENSOR")
def config_set(
    sensor: Annotated[
        CliSensor, typer.Argument(help="The sensor to configure", show_default=False)
    ],
    controls_values: Annotated[
        list[str],
        typer.Argument(help="Controls to set followed by the value in form of CONTROL=VALUE"),
    ],
):
    driver = get_driver()
    controls = {}
    for ctrl_val in controls_values:
        try:
            ctrl, val = ctrl_val.split("=")
            controls[ctrl] = float(val)
        except ValueError:
            print(f"Failed to parse control value pair: {ctrl_val}")
            raise typer.Abort()
    driver.set_control_values(sensor.rs_enum, controls)
    config_get(sensor, list(controls.keys()))
