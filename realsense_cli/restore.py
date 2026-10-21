"""
Control restore: set a sensor's controls back to their defaults.

On a real camera some controls move others. Writing a visual preset rewrites the controls it
covers, and writing a control the camera drives in an auto mode (exposure, gain, white balance)
turns that auto mode off. So the preset is written first, then the plain controls, then the
auto modes, each step only writing what still differs from its default when it runs. A control
the camera drives is left alone while its auto mode is on and stays on.
"""

from typing import Any

from realsense_cli.driver.base import DriverProtocol
from realsense_cli.errors import InvalidValue, UnknownControl

PRESET = "visual_preset"

# Auto mode -> the controls the camera drives while it's on
AUTO_MODES: dict[str, list[str]] = {
    "enable_auto_exposure": ["exposure", "gain"],
    "enable_auto_white_balance": ["white_balance"],
}

Row = dict[str, Any]


def restore_controls(
    driver: DriverProtocol, sensor: str, names: list[str] | None, keep_going: bool = False
) -> tuple[list[Row], list[Row]]:
    """
    Restore the writable controls in NAMES (all if None) on SENSOR to their defaults.

    Returns the controls whose value changed and, with KEEP_GOING, the ones that failed to
    write; without it the first failure raises.
    """
    controls = driver.list_controls(sensor)
    known = sorted(control.name for control in controls)
    for name in names or []:
        if name not in known:
            raise UnknownControl(name, sensor, known)
    defaults = {
        c.name: c.default_value
        for c in controls
        if not c.read_only and (not names or c.name in names)
    }
    for control in _auto_driven(driver, sensor, known, defaults):
        defaults.pop(control, None)

    old = driver.get_control_values(sensor, list(defaults))
    failed = []
    plain = [name for name in defaults if name != PRESET and name not in AUTO_MODES]
    for step in ([PRESET], plain, list(AUTO_MODES)):
        step = [name for name in step if name in defaults]
        current = driver.get_control_values(sensor, step)
        for name in step:
            # Defaults are rounded to 6 decimals, values are read back as raw float32
            if round(current[name], 6) == defaults[name]:
                continue
            try:
                driver.set_control_values(sensor, {name: defaults[name]})
            except InvalidValue as e:
                if not keep_going:
                    raise
                failed.append({"sensor": sensor, "control": name, "error": str(e)})

    new = driver.get_control_values(sensor, list(defaults))
    restored = [
        {"sensor": sensor, "control": name, "old": old[name], "new": new[name]}
        for name in defaults
        if old[name] != new[name]
    ]
    return restored, failed


def _auto_driven(
    driver: DriverProtocol, sensor: str, known: list[str], defaults: dict[str, float]
) -> list[str]:
    """
    Controls the camera drives because their auto mode is on now and stays on after restoring
    """
    driven = []
    for mode, controls in AUTO_MODES.items():
        if mode not in known:
            continue
        on = driver.get_control_values(sensor, [mode])[mode] == 1
        # An auto mode that isn't being restored keeps its current value
        if on and defaults.get(mode, 1) == 1:
            driven += controls
    return driven
