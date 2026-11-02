from typing import Annotated

import typer

from realsense_cli.advanced import resolve_names
from realsense_cli.advanced_mode import YesOption, require_advanced_mode
from realsense_cli.printer import emit, list_advanced_controls, list_options_values
from realsense_cli.session import get_driver
from realsense_cli.types import AdvancedControl

advanced_app = typer.Typer(
    help="Read advanced controls: the depth tuning advanced mode unlocks",
    no_args_is_help=True,
)

_NAMES_HELP = (
    "group.field with the SDK's names (rsm.diffThresh), or a group for all its fields; "
    "case-insensitive"
)
_ADVANCED_MODE_HELP = "Turns advanced mode on first if it's off, which resets the device"


def _read(
    ctx: typer.Context, names: list[str], yes: bool
) -> tuple[list[AdvancedControl], bool]:
    """
    The advanced controls NAMES pick (every one when empty), checked before advanced mode is
    turned on, and whether this run turned it on
    """
    resolved = resolve_names(get_driver(ctx).advanced_groups(), names)
    driver, enabled = require_advanced_mode(ctx, yes)
    controls = {control.name: control for control in driver.advanced_controls()}
    return [controls[name] for name in resolved], enabled


@advanced_app.command(
    name="list",
    help=f"List advanced controls with their type and range. {_ADVANCED_MODE_HELP}",
)
def advanced_list(
    ctx: typer.Context,
    groups: Annotated[
        list[str] | None,
        typer.Argument(
            metavar="[GROUP]...",
            help=f"Groups to list (default: all). {_NAMES_HELP}",
            show_default=False,
        ),
    ] = None,
    yes: YesOption = False,
):
    controls, enabled = _read(ctx, groups or [], yes)
    payload = {
        "controls": [
            {
                "name": c.name,
                "group": c.group,
                "vtype": c.vtype.__name__,
                "min_value": c.min_value,
                "max_value": c.max_value,
            }
            for c in controls
        ],
        "advanced_mode_enabled": enabled,
    }
    emit(ctx, payload, lambda: list_advanced_controls(controls))


@advanced_app.command(
    name="get",
    help=f"Read advanced controls, or every one with --all. {_ADVANCED_MODE_HELP}",
)
def advanced_get(
    ctx: typer.Context,
    names: Annotated[
        list[str] | None,
        typer.Argument(metavar="[NAME]...", help=_NAMES_HELP, show_default=False),
    ] = None,
    all_controls: Annotated[
        bool, typer.Option("--all/", help="Read every advanced control")
    ] = False,
    yes: YesOption = False,
):
    if not names and not all_controls:
        raise typer.BadParameter(
            "Specify advanced-control names or use --all to read them all.",
            param_hint="'NAME...'",
        )
    controls, enabled = _read(ctx, [] if all_controls else names or [], yes)
    values = {c.name: c.value for c in controls}
    emit(
        ctx,
        {"values": values, "advanced_mode_enabled": enabled},
        lambda: list_options_values(values),
    )
