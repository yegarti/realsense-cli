from typing import Annotated

import typer

from realsense_cli import printer
from realsense_cli.driver import get_driver

safety_preset_app = typer.Typer(help="Safety Preset options", no_args_is_help=True)


@safety_preset_app.command(
    name="show",
    help="Print safety preset and export to JSON file"
)
def preset_show(
        preset_index: Annotated[int, typer.Argument(help='Preset index', show_default=False)],
        raw: Annotated[bool, typer.Option(help='Show prest directly from driver')] = False,
        # export: Annotated[Path, typer.Option(help='Export preset to JSON')] = None,
):
    driver = get_driver()
    preset = driver.get_safety_preset(preset_index)
    if raw:
        print(preset.raw_form)
    else:
        print(preset)
        # printer.show_safety_preset(preset)
    pass


@safety_preset_app.command(
    name="import",
    help="Import safety preset from JSON file"
)
def preset_show(
        preset_index: Annotated[int, typer.Argument(help='Preset index', show_default=False)],
        # export: Annotated[Path, typer.Option(help='Export preset to JSON')] = None,
):
    driver = get_driver()
    # preset = driver.set_safety_preset(preset_index, driver.get_safety_preset(0))
    preset = driver.set_safety_preset(preset_index, driver.get_safety_preset(preset_index))
    # if raw:
    #     print(preset.raw_form)
    # else:
    #     print(preset)
    #     # printer.show_safety_preset(preset)
    # pass
