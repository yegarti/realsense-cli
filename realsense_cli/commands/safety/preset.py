import json
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

import typer

from realsense_cli import printer
from realsense_cli.driver import get_driver

safety_preset_app = typer.Typer(help="Safety Preset options", no_args_is_help=True)


@safety_preset_app.command(name="print", help="Print safety preset and export to JSON file")
def preset_print(
    preset_index: Annotated[int, typer.Argument(help="Preset index", show_default=False)],
    raw: Annotated[bool, typer.Option(help="Print prest directly from driver")] = False,
):
    driver = get_driver()
    preset = driver.get_safety_preset(preset_index)
    if raw:
        print(preset.raw_form)
    else:
        printer.print_safety_preset(preset)
    pass


@safety_preset_app.command(name="export", help="Export to JSON file")
def preset_export(
    preset_index: Annotated[int, typer.Argument(help="Preset index", show_default=False)],
    file: Annotated[Path, typer.Argument(help="Export preset to JSON", file_okay=True)],
):
    driver = get_driver()
    preset = driver.get_safety_preset(preset_index)
    data = asdict(preset)
    del data["raw_form"]
    file.write_text(json.dumps(data))
