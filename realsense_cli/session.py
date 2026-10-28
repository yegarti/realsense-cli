import sys

import typer
from loguru import logger

from realsense_cli.console import err_console
from realsense_cli.driver import create_driver
from realsense_cli.driver.base import DriverProtocol
from realsense_cli.errors import DeviceNotFound


class Session:
    """
    Per-run CLI state, kept in `ctx.obj`. The driver is created on first use, so commands
    that need no camera (`bag`, `--help`) never reach a device.
    """

    def __init__(self, serial: str, json: bool = False):
        self.serial = serial
        self.json = json
        self._driver: DriverProtocol | None = None

    @property
    def driver(self) -> DriverProtocol:
        if self._driver is None:
            driver = create_driver()
            logger.debug("setting '{}' as active device", self.serial)
            driver.active_device = self.serial
            self._driver = driver
        return self._driver

    def require_device(self, warn_ambiguous: bool = True) -> DriverProtocol:
        """
        The driver, once at least one device is connected. Says which device it picked when
        the device is ambiguous, unless WARN_AMBIGUOUS is off
        """
        driver = self.driver
        if not driver.query_devices():
            raise DeviceNotFound("No devices are connected")
        if warn_ambiguous and self.device_is_ambiguous():
            logger.warning("Multiple devices without serial!")
            err_console.print(
                "Multiple devices are connected but no serial provided, "
                f"using device: '{driver.active_device}'"
            )
        return driver

    def device_is_ambiguous(self) -> bool:
        """
        Whether several devices are connected and `--serial` didn't pick one
        """
        return not self.serial and len(self.driver.query_devices()) > 1


def _session(ctx: typer.Context) -> Session:
    session = ctx.find_object(Session)
    assert session is not None, "the root callback sets ctx.obj"
    return session


def json_output(ctx: typer.Context) -> bool:
    """
    Whether `--json` was given
    """
    return _session(ctx).json


def interactive(ctx: typer.Context) -> bool:
    """
    Whether the user can answer a prompt: stdin is a terminal and `--json` wasn't given
    """
    return not json_output(ctx) and _stdin_is_tty()


def _stdin_is_tty() -> bool:
    return sys.stdin.isatty()


def device_is_ambiguous(ctx: typer.Context) -> bool:
    """
    Whether several devices are connected and `--serial` didn't pick one
    """
    return _session(ctx).device_is_ambiguous()


def get_driver(ctx: typer.Context) -> DriverProtocol:
    """
    The driver, for commands that work with no device connected
    """
    return _session(ctx).driver


def require_device(ctx: typer.Context, warn_ambiguous: bool = True) -> DriverProtocol:
    """
    The driver, for commands that need a device. Raises `DeviceNotFound` when none is connected
    """
    return _session(ctx).require_device(warn_ambiguous)
