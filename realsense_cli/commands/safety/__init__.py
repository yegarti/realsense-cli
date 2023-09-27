from typing import Annotated

import typer

from realsense_cli.commands.safety.preset import safety_preset_app

safety_app = typer.Typer(help="Safety options", no_args_is_help=True)

safety_app.add_typer(safety_preset_app, name='preset')