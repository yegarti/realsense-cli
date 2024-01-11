from typing import Annotated

import typer

from realsense_cli.commands.safety.preset import safety_preset_app
from realsense_cli.commands.safety.interface import safety_interface_app

safety_app = typer.Typer(help="Safety options", no_args_is_help=True)

safety_app.add_typer(safety_preset_app, name="preset")
safety_app.add_typer(safety_interface_app, name="interface")
