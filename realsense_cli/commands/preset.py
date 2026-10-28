import json
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer

from realsense_cli.advanced_mode import YesOption, require_advanced_mode
from realsense_cli.console import console
from realsense_cli.errors import InvalidValue
from realsense_cli.printer import emit
from realsense_cli.utils import new_path

preset_app = typer.Typer(help="Save preset files", no_args_is_help=True)


@preset_app.command(
    name="save",
    help="Save the device's preset file, in librealsense's JSON (as the Viewer saves it). "
    "Turns advanced mode on first if it's off, which resets the device",
)
def preset_save(
    ctx: typer.Context,
    file: Annotated[
        Path | None,
        typer.Argument(
            metavar="[FILE]",
            dir_okay=False,
            help="File to write (default: ./rs-preset-<timestamp>.json)",
            show_default=False,
        ),
    ] = None,
    force: Annotated[bool, typer.Option("--force", help="Overwrite FILE if it exists")] = False,
    yes: YesOption = False,
):
    if file is None:
        file = new_path(f"rs-preset-{datetime.now():%Y%m%d-%H%M%S}", ".json")
    path = file.absolute()
    if path.exists() and not force:
        raise InvalidValue(f"'{file}' already exists; pass --force to overwrite it")
    driver, enabled = require_advanced_mode(ctx, yes)
    preset = driver.serialize_preset()
    keys = len(json.loads(preset)["parameters"])
    path.write_text(preset)
    payload = {"saved": str(path), "keys": keys, "advanced_mode_enabled": enabled}
    emit(ctx, payload, lambda: console.print(f"Saved {keys} keys to {file}"))
