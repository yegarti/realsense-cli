import json
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

import typer

from realsense_cli.advanced_mode import YesOption, device_label, require_advanced_mode
from realsense_cli.console import console
from realsense_cli.errors import InvalidValue
from realsense_cli.preset import preset_changes, read_preset
from realsense_cli.printer import emit, list_preset_changes
from realsense_cli.utils import new_path

preset_app = typer.Typer(help="Save and load preset files", no_args_is_help=True)


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
    emit(
        ctx,
        payload,
        lambda: console.print(f"Saved {keys} keys to {file}", soft_wrap=True, markup=False),
    )


@preset_app.command(
    name="load",
    help="Load a preset file onto the device: librealsense's JSON, as the Viewer or rs preset "
    "save writes it. Turns advanced mode on first if it's off, which resets the device. "
    "rs config restore depth undoes it",
)
def preset_load(
    ctx: typer.Context,
    file: Annotated[
        Path,
        typer.Argument(
            metavar="FILE",
            exists=True,
            dir_okay=False,
            readable=True,
            help="Preset file to load",
            show_default=False,
        ),
    ],
    no_validate: Annotated[
        bool,
        typer.Option(
            "--no-validate",
            help="Hand the file to the SDK without checking its values; the SDK loads a value "
            "it can't read as 0",
        ),
    ] = False,
    diff: Annotated[
        bool,
        typer.Option(
            "--diff",
            help="Also list the preset keys the load changed, with their old and new values",
        ),
    ] = False,
    yes: YesOption = False,
):
    preset = read_preset(file, validate=not no_validate)
    driver, enabled = require_advanced_mode(ctx, yes)
    before = driver.serialize_preset() if diff else None
    driver.load_preset(preset)
    payload: dict[str, Any] = {"loaded": str(file.absolute()), "advanced_mode_enabled": enabled}
    if before is not None:
        payload["changed"] = preset_changes(before, driver.serialize_preset())

    def table() -> None:
        console.print(
            f"Loaded preset {file} onto {device_label(driver)}", soft_wrap=True, markup=False
        )
        if "changed" in payload:
            list_preset_changes(payload["changed"])

    emit(ctx, payload, table)
