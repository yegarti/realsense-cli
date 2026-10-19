"""
Errors the CLI reports to the user as a one-line message instead of a traceback.

Each error has a fixed exit code (listed in the README). 2 is left to click's usage errors.
"""

from collections.abc import Iterable
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


class InvalidProfile(RsCliError):
    exit_code = 6


class InvalidValue(RsCliError):
    exit_code = 7
