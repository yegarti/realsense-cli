from pathlib import Path
from typing import Annotated, Optional

import typer

from realsense_cli import printer
from realsense_cli.driver import get_driver
from realsense_cli.types import SafetyPreset

safety_preset_app = typer.Typer(help="Safety Preset options", no_args_is_help=True)


@safety_preset_app.command(name="print", help="Print safety preset")
def preset_print(
    preset_index: Annotated[int, typer.Argument(help="Preset index", show_default=False)],
    raw: Annotated[bool, typer.Option(help="Print prest directly from driver")] = False,
    export: Annotated[
        Optional[Path],
        typer.Option("--export", help="Export to JSON, same as 'export' cmd", file_okay=True),
    ] = None,
):
    driver = get_driver()
    preset = driver.get_safety_preset(preset_index)
    if raw:
        print(preset.raw_form)
    else:
        printer.print_safety_preset(preset)
    if export:
        export.write_text(preset.to_json())
    pass


@safety_preset_app.command(name="export", help="Export to JSON file")
def preset_export(
    preset_index: Annotated[int, typer.Argument(help="Preset index", show_default=False)],
    file: Annotated[Path, typer.Argument(help="Path to JSON file", file_okay=True)],
):
    driver = get_driver()
    preset = driver.get_safety_preset(preset_index)
    file.write_text(preset.to_json())


@safety_preset_app.command(name="import", help="Import preset from JSON file")
def preset_import(
    preset_index: Annotated[int, typer.Argument(help="Preset index", show_default=False)],
    file: Annotated[
        Path, typer.Argument(help="Path to JSON preset", file_okay=True, exists=True)
    ],
):
    driver = get_driver()
    preset = SafetyPreset.from_json(file.read_text())
    with driver.service_mode(wait=1):
        driver.set_safety_preset(preset_index, preset)
