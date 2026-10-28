"""
Turning on advanced mode for the commands that need it. Turning it on resets the device, so it
asks first; nothing in `rs` turns it off.
"""

from typing import Annotated

import typer

from realsense_cli.console import err_console
from realsense_cli.driver.base import DriverProtocol
from realsense_cli.errors import ConfirmationRequired, DeviceNotFound, RsCliError
from realsense_cli.session import interactive, json_output, require_device

ADVANCED_MODE_TIMEOUT = 30

YesOption = Annotated[
    bool,
    typer.Option("--yes", "-y", help="Turn advanced mode on without asking, if it's off"),
]


def require_advanced_mode(ctx: typer.Context, yes: bool) -> tuple[DriverProtocol, bool]:
    """
    The driver, with advanced mode on on its active device, and whether this run turned it on.
    When it's off, asks before turning it on, unless YES; with no one to ask, raises
    `ConfirmationRequired`
    """
    driver = require_device(ctx)
    serial = driver.active_device
    name = next(d.name for d in driver.query_devices() if d.serial == serial)
    device = f"{name} ({serial})"
    enabled = driver.advanced_mode()
    if enabled is None:
        raise RsCliError(f"{device} has no advanced mode")
    if enabled:
        return driver, False
    if not yes:
        if not interactive(ctx):
            raise ConfirmationRequired(
                f"Advanced mode is off on {device}, and turning it on resets the device. "
                "Pass --yes to turn it on"
            )
        typer.confirm(
            f"Advanced mode is off on {device}. Turn it on? The device resets",
            abort=True,
            err=True,
        )
    if not json_output(ctx):
        err_console.print(f"Turning on advanced mode on {device}, waiting for it to reconnect")
    if not driver.enable_advanced_mode(ADVANCED_MODE_TIMEOUT):
        raise DeviceNotFound(
            f"Device '{serial}' did not reconnect within {ADVANCED_MODE_TIMEOUT}s"
        )
    return driver, True
