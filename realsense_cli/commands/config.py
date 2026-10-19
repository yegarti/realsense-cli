from dataclasses import asdict
from typing import Annotated

import typer

from realsense_cli.errors import InvalidValue
from realsense_cli.printer import emit, list_options, list_options_values
from realsense_cli.session import require_device
from realsense_cli.types import resolve_sensor_name

config_app = typer.Typer(help="Configure controls", no_args_is_help=True)


@config_app.command(
    name="list",
    help="List SENSOR supported controls with description and possible values for given sensor",
)
def config_list(
    ctx: typer.Context,
    sensor: Annotated[
        str,
        typer.Argument(help="Sensor name or alias (depth, color, motion)", show_default=False),
    ],
) -> None:
    driver = require_device(ctx)
    resolved = resolve_sensor_name(sensor)
    controls = driver.list_controls(resolved)
    payload = {
        "sensor": resolved,
        "controls": [asdict(c) | {"vtype": c.vtype.__name__} for c in controls],
    }
    emit(ctx, payload, lambda: list_options(controls))


@config_app.command(
    name="get", help="Get control values for given SENSOR or all controls if '--all' is used"
)
def config_get(
    ctx: typer.Context,
    sensor: Annotated[
        str,
        typer.Argument(help="Sensor name or alias (depth, color, motion)", show_default=False),
    ],
    controls: Annotated[list[str] | None, typer.Argument(help="Controls to query")] = None,
    all_controls: Annotated[
        bool, typer.Option("--all/", help="Query all supported controls")
    ] = False,
):
    driver = require_device(ctx)
    resolved = resolve_sensor_name(sensor)
    if not controls and not all_controls:
        raise typer.BadParameter(
            "Specify control names or use --all to query all controls.",
            param_hint="'CONTROLS...'",
        )
    if not controls:
        controls = []
    if all_controls:
        controls = [opt.name for opt in driver.list_controls(resolved)]
    _emit_values(ctx, resolved, driver.get_control_values(resolved, controls))


@config_app.command(name="set", help="Set controls for given SENSOR")
def config_set(
    ctx: typer.Context,
    sensor: Annotated[
        str,
        typer.Argument(help="Sensor name or alias (depth, color, motion)", show_default=False),
    ],
    controls_values: Annotated[
        list[str],
        typer.Argument(help="Controls to set followed by the value in form of CONTROL=VALUE"),
    ],
):
    driver = require_device(ctx)
    controls = {}
    for ctrl_val in controls_values:
        try:
            ctrl, val = ctrl_val.split("=")
            controls[ctrl] = float(val)
        except ValueError:
            raise InvalidValue(
                f"Failed to parse '{ctrl_val}', expected CONTROL=VALUE with a numeric VALUE"
            ) from None
    resolved = resolve_sensor_name(sensor)
    driver.set_control_values(resolved, controls)
    _emit_values(ctx, resolved, driver.get_control_values(resolved, list(controls)))


def _emit_values(ctx: typer.Context, sensor: str, values: dict[str, float]) -> None:
    emit(ctx, {"sensor": sensor, "values": values}, lambda: list_options_values(values))
