import json
import sys
from dataclasses import asdict
from typing import Annotated

import typer
from loguru import logger
from rich.markup import escape
from typer.core import TyperGroup
from typer.exceptions import Abort, Exit, TyperException

from realsense_cli.commands.bag import bag_app
from realsense_cli.commands.config import config_app
from realsense_cli.commands.info import rs_info
from realsense_cli.commands.stream import stream_app
from realsense_cli.console import console, err_console
from realsense_cli.errors import ConfirmationRequired, DeviceNotFound, RsCliError
from realsense_cli.printer import emit, list_devices
from realsense_cli.session import (
    Session,
    device_is_ambiguous,
    get_driver,
    interactive,
    json_output,
    require_device,
)


class RsCliGroup(TyperGroup):
    """
    Root command group that reports errors as one line on stderr with a matching exit code,
    or as a JSON object under `--json`. Every subcommand runs inside its `invoke`.
    """

    def invoke(self, ctx):
        as_json = bool(ctx.params.get("json_output"))
        try:
            return super().invoke(ctx)
        except (Abort, Exit):
            raise
        except TyperException as e:
            # click's own errors, usage errors among them: click prints them unless --json.
            # A group run with no arguments has already printed its help and has no message.
            exit_code = getattr(e, "exit_code", 1)
            if not as_json or not getattr(e, "format_message", lambda: "")():
                raise
            error_type = "UsageError" if exit_code == 2 else type(e).__name__
            _print_json_error(error_type, e.format_message(), exit_code)
            raise Exit(exit_code) from e
        except RsCliError as e:
            if as_json:
                _print_json_error(type(e).__name__, str(e), e.exit_code)
            else:
                _print_error(str(e))
            raise Exit(e.exit_code) from e
        except Exception as e:
            if ctx.params.get("verbose"):
                raise
            if as_json:
                _print_json_error(type(e).__name__, str(e), 1)
            else:
                _print_error(f"{type(e).__name__}: {e} (run with --verbose for the traceback)")
            raise Exit(1) from e


def _print_error(message: str) -> None:
    err_console.print(f"[bold red]Error:[/] {escape(message)}", soft_wrap=True)


def _print_json_error(error_type: str, message: str, exit_code: int) -> None:
    error = {"type": error_type, "message": message, "exit_code": exit_code}
    err_console.out(json.dumps({"error": error}), highlight=False)


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
    emit(ctx, {"devices": [asdict(d) for d in devices]}, lambda: list_devices(devices))


app.command(name="info")(rs_info)

app.add_typer(config_app, name="config")

app.add_typer(stream_app, name="stream")

app.add_typer(bag_app, name="bag")


RESET_WAIT_TIMEOUT = 30


@app.command(name="reset")
def rs_reset(
    ctx: typer.Context,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Don't ask which device when several are connected"),
    ] = False,
    wait: Annotated[
        bool, typer.Option("--wait", help="Wait until the device is connected again")
    ] = False,
    timeout: Annotated[
        float | None,
        typer.Option(
            "--timeout",
            help=f"Seconds --wait waits for the device (default {RESET_WAIT_TIMEOUT})",
            show_default=False,
        ),
    ] = None,
) -> None:
    """
    Send hardware reset command to device
    """
    if timeout is not None and not wait:
        raise typer.BadParameter("only applies with --wait", param_hint="'--timeout'")
    if timeout is not None and timeout <= 0:
        raise typer.BadParameter("must be more than 0 seconds", param_hint="'--timeout'")
    # with --yes the usual notice says which device it picked; otherwise the prompt names it
    driver = require_device(ctx, warn_ambiguous=yes)
    dev = driver.active_device
    if not yes and device_is_ambiguous(ctx):
        if not interactive(ctx):
            serials = ", ".join(d.serial for d in driver.query_devices())
            raise ConfirmationRequired(
                f"Several devices are connected ({serials}); pass --serial to pick one, "
                f"or --yes to reset '{dev}'"
            )
        name = next(d.name for d in driver.query_devices() if d.serial == dev)
        typer.confirm(f"Reset {name} ({dev})?", abort=True, err=True)
    if not json_output(ctx):
        console.print(f"Performing hardware reset for device '{dev}'")
    if not wait:
        driver.reset()
        emit(ctx, {"reset": dev}, lambda: None)
        return
    timeout = RESET_WAIT_TIMEOUT if timeout is None else timeout
    if not driver.reset(timeout):
        raise DeviceNotFound(f"Device '{dev}' did not reconnect within {timeout:g}s")
    emit(
        ctx,
        {"reset": dev, "reconnected": True},
        lambda: console.print(f"Device '{dev}' reconnected"),
    )


@app.callback()
def callback(
    ctx: typer.Context,
    verbose: Annotated[int, typer.Option("--verbose", "-v", count=True)] = 0,
    serial: Annotated[
        str, typer.Option("-s", "--serial", help="Act on device with this serial number")
    ] = "",
    json_output: Annotated[
        bool, typer.Option("--json", help="Print results as JSON, for scripts and agents")
    ] = False,
):
    logger.remove()
    if verbose == 1:
        logger.add(sys.stderr, level="INFO")
    if verbose > 1:
        logger.add(sys.stderr, level="DEBUG")

    logger.info("Logger verbosity: {}", verbose)
    ctx.obj = Session(serial, json=json_output)
