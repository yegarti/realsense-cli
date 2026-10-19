import sys
from typing import Annotated

import typer
from loguru import logger
from rich.markup import escape
from typer.core import TyperGroup
from typer.exceptions import Abort, Exit, TyperException

from realsense_cli.commands.bag import bag_app
from realsense_cli.commands.config import config_app
from realsense_cli.commands.stream import stream_app
from realsense_cli.console import console, err_console
from realsense_cli.errors import RsCliError
from realsense_cli.printer import list_devices
from realsense_cli.session import Session, get_driver, require_device


class RsCliGroup(TyperGroup):
    """
    Root command group that reports errors as one line on stderr with a matching exit code.
    Every subcommand runs inside its `invoke`.
    """

    def invoke(self, ctx):
        try:
            return super().invoke(ctx)
        except (TyperException, Abort, Exit):
            raise
        except RsCliError as e:
            _print_error(str(e))
            raise Exit(e.exit_code) from e
        except Exception as e:
            if ctx.params.get("verbose"):
                raise
            _print_error(f"{type(e).__name__}: {e} (run with --verbose for the traceback)")
            raise Exit(1) from e


def _print_error(message: str) -> None:
    err_console.print(f"[bold red]Error:[/] {escape(message)}", soft_wrap=True)


app = typer.Typer(
    cls=RsCliGroup,
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


@app.command(name="list")
def rs_list(ctx: typer.Context) -> None:
    """
    List connected devices with basic info
    """
    driver = get_driver(ctx)
    devices = driver.query_devices()
    list_devices(devices)


app.add_typer(config_app, name="config")

app.add_typer(stream_app, name="stream")

app.add_typer(bag_app, name="bag")


@app.command(name="reset")
def rs_reset(ctx: typer.Context) -> None:
    """
    Send hardware reset command to device
    """
    driver = require_device(ctx)
    dev = driver.active_device
    console.print(f"Performing hardware reset for device '{dev}'")
    driver.reset()


@app.callback()
def callback(
    ctx: typer.Context,
    verbose: Annotated[int, typer.Option("--verbose", "-v", count=True)] = 0,
    serial: Annotated[
        str, typer.Option("-s", "--serial", help="Act on device with this serial number")
    ] = "",
):
    logger.remove()
    if verbose == 1:
        logger.add(sys.stderr, level="INFO")
    if verbose > 1:
        logger.add(sys.stderr, level="DEBUG")

    logger.info("Logger verbosity: {}", verbose)
    ctx.obj = Session(serial)
