"""
Errors the CLI reports to the user as a one-line message instead of a traceback.

Each error has a fixed exit code (listed in the README). 2 is left to click's usage errors.
"""

from collections.abc import Collection, Iterable
from typing import ClassVar


def _choices(values: Iterable[str]) -> str:
    return ", ".join(values) or "none"


class RsCliError(Exception):
    exit_code: ClassVar[int] = 1


class DeviceNotFound(RsCliError):
    exit_code = 3


class UnknownSensor(RsCliError):
    exit_code = 4

    def __init__(self, sensor: str, valid: Iterable[str]):
        super().__init__(f"Unknown sensor '{sensor}'. Valid sensors: {_choices(valid)}")


class UnknownControl(RsCliError):
    exit_code = 5

    def __init__(self, control: str, sensor: str, valid: Iterable[str]):
        super().__init__(
            f"Control '{control}' is not supported by '{sensor}'. "
            f"Valid controls: {_choices(valid)}"
        )


class UnknownAdvancedControl(RsCliError):
    """An advanced-control name that names no group, or no field in its group"""

    exit_code = 5


class InvalidProfile(RsCliError):
    exit_code = 6


class InvalidValue(RsCliError):
    exit_code = 7


class ConfirmationRequired(RsCliError):
    exit_code = 8


class NoFrames(RsCliError):
    exit_code = 9


def with_bandwidth_hint(message: str, streams: Collection[str]) -> str:
    """
    MESSAGE, about frames that didn't arrive while STREAMS played, with a hint that the USB link
    may not carry them all when there are several
    """
    if len(streams) < 2:
        return message
    return (
        f"{message}. The USB link may not carry all {len(streams)} streams at once (over "
        "usbipd on WSL, for example): try fewer streams or lower resolutions, such as "
        "depth-640x480-30-z16"
    )


class ControlUnavailable(RsCliError):
    """A control the sensor lists but can't read right now, e.g. a temperature while idle"""

    exit_code = 10

    def __init__(self, control: str, sensor: str):
        super().__init__(
            f"Control '{control}' on '{sensor}' can't be read right now; "
            "the camera may report it only while streaming"
        )
