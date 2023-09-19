import sys
from typing import Annotated

from loguru import logger
import typer

from realsense_cli.commands.config import config_app
from realsense_cli.commands.stream import stream_app
from realsense_cli.driver import get_driver
from realsense_cli.utils.rich import list_devices

app = typer.Typer(
    no_args_is_help=True, context_settings={"help_option_names": ["-h", "--help"]}
)


@app.command(name="list")
def rs_list() -> None:
    """
    List connected devices with basic info
    """
    driver = get_driver()
    devices = driver.query_devices()
    list_devices(devices)


app.add_typer(config_app, name="config")

app.add_typer(stream_app, name="stream")


@app.callback()
def callback(
    ctx: typer.Context,
    verbose: Annotated[int, typer.Option("--verbose", "-v", count=True)] = 0,
    serial: Annotated[str, typer.Option("-s", "--serial", help="Act on device with this serial number")] = "",
):
    logger.remove()
    if verbose == 1:
        logger.add(sys.stderr, level="INFO")
    if verbose > 1:
        logger.add(sys.stderr, level="DEBUG")

    logger.info("Logger verbosity: {}", verbose)

    driver = get_driver()
    logger.debug(f"setting '{serial}' as active device")
    try:
        driver.active_device = serial
    except ValueError:
        print(f"Serial {serial} does not match any connected device:")
        raise typer.Abort()

    if ctx.invoked_subcommand != "list":
        logger.debug("checking device exist for subcommand '{}'", ctx.invoked_subcommand)
        dev_n = len(driver.query_devices())
        if dev_n == 0:
            logger.error("no devices found - exiting")
            print("No devices are connected")
            raise typer.Exit(1)
        if dev_n > 1 and not serial:
            logger.warning("Multiple devices without serial!")
            print(
                f"Multiple devices are connected but no serial provided, using device: '{driver.active_device}'"
            )
