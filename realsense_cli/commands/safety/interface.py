from pathlib import Path
from typing import Annotated, Optional
import typer
from realsense_cli import printer

from realsense_cli.driver import get_driver
from realsense_cli.types import SafetyInterfaceConfig

safety_interface_app = typer.Typer(help="Safety Interface options", no_args_is_help=True)


@safety_interface_app.command(name="print", help="Print safety interface config")
def interface_print(
    export: Annotated[
        Optional[Path],
        typer.Option("--export", help="Export to JSON, same as 'export' cmd", file_okay=True),
    ] = None,
):
    driver = get_driver()
    interface_config = driver.get_safety_interface()
    printer.print_safety_interface(interface_config)
    if export:
        export.write_text(interface_config.to_json())


@safety_interface_app.command(name="export", help="Export safety interface config to JSON file")
def interface_export(
    file: Annotated[Path, typer.Argument(help="Path to JSON file", file_okay=True)],
):
    driver = get_driver()
    config = driver.get_safety_interface()
    file.write_text(config.to_json())


@safety_interface_app.command(name="import", help="Import interface config from JSON file")
def interface_import(
    file: Annotated[
        Path, typer.Argument(help="Path to JSON preset", file_okay=True, exists=True)
    ],
):
    driver = get_driver()
    config = SafetyInterfaceConfig.from_json(file.read_text())
    # print(config)
    driver.set_safety_interface(config)
    # with driver.service_mode(wait=1):
    #     driver.set_safety_interface(config)
