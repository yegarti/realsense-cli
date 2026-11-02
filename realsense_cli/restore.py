"""
Control restore: set a sensor's controls back to their defaults.

On a real camera some controls move others:

- Writing a visual preset rewrites the controls it covers.
- Writing a control the camera drives in an auto mode (exposure, gain, white balance) turns that
  auto mode off.
- A gated control (an auto exposure limit, an HDR sequence) only applies while its gate is on.
  Writing it can turn the gate on, and while the gate is off it may read as something else (a
  D455 reads an exposure limit as 200000).

So the preset is written first, then the plain controls, then the auto modes and gates, each
step only writing what still differs from its default when it runs. A control the camera drives
is left alone while its auto mode is on and stays on, and a gated control while its gate ends
off. Session controls are never written: the SDK resets them in every new process.

`visual_preset` reports `custom` as its default, and writing `custom` changes nothing, so a
control restore never brings back the depth tuning. `restore_tuning()` writes the `default`
preset instead, which the camera applies to every advanced-control group.
"""

from typing import Any

from realsense_cli.driver.base import DriverProtocol
from realsense_cli.errors import ControlUnavailable, InvalidValue, UnknownControl

PRESET = "visual_preset"
# rs.rs400_visual_preset.default: the built-in tuning. The option's own default is custom
DEFAULT_PRESET = 1

# Auto mode -> the controls the camera drives while it's on
AUTO_MODES: dict[str, list[str]] = {
    "enable_auto_exposure": ["exposure", "gain"],
    "enable_auto_white_balance": ["white_balance"],
}

# Gate -> the controls that only apply while it's on
GATES: dict[str, list[str]] = {
    "auto_exposure_limit_toggle": ["auto_exposure_limit"],
    "auto_gain_limit_toggle": ["auto_gain_limit"],
    "hdr_enabled": ["sequence_name", "sequence_id"],
}

SESSION_CONTROLS = {"error_polling_enabled"}

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
    for control in _left_alone(driver, sensor, known, defaults):
        defaults.pop(control, None)

    old = driver.get_control_values(sensor, list(defaults))
    failed = []
    toggles = [*AUTO_MODES, *GATES]
    plain = [name for name in defaults if name != PRESET and name not in toggles]
    for step in ([PRESET], plain, toggles):
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


def restore_tuning(driver: DriverProtocol, sensor: str) -> tuple[list[Row], list[Row]]:
    """
    Write the `default` visual preset on SENSOR, even when it already reads that: the camera
    then reapplies its built-in tuning to every advanced-control group, and a D400 also sets
    laser on, laser power 150 and depth auto exposure on.

    Returns the `visual_preset` row, then every other writable control on SENSOR whose value
    changed, and the write's failure
    """
    controls = driver.list_controls(sensor)
    known = sorted(control.name for control in controls)
    if PRESET not in known:
        raise UnknownControl(PRESET, sensor, known)
    names = [
        c.name
        for c in controls
        if not c.read_only and c.name not in SESSION_CONTROLS and c.name != PRESET
    ]
    names.insert(0, PRESET)

    old, _ = read_available(driver, sensor, names)
    failed = []
    try:
        driver.set_control_values(sensor, {PRESET: DEFAULT_PRESET})
    except InvalidValue as e:
        failed.append({"sensor": sensor, "control": PRESET, "error": str(e)})
    new, _ = read_available(driver, sensor, names)
    restored = [
        {"sensor": sensor, "control": name, "old": old[name], "new": new[name]}
        for name in old
        if name in new and (old[name] != new[name] or (name == PRESET and not failed))
    ]
    return restored, failed


def read_available(
    driver: DriverProtocol, sensor: str, controls: list[str]
) -> tuple[dict[str, float], list[str]]:
    """
    Values of the CONTROLS the sensor can read right now, and the names of those it can't
    """
    values, unavailable = {}, []
    for control in controls:
        try:
            values |= driver.get_control_values(sensor, [control])
        except ControlUnavailable:
            unavailable.append(control)
    return values, unavailable


def _left_alone(
    driver: DriverProtocol, sensor: str, known: list[str], defaults: dict[str, float]
) -> set[str]:
    """
    Controls restoring must not write: session controls, controls the camera drives in an auto
    mode that is on and stays on, and gated controls whose gate ends off
    """
    toggles = [name for name in (*AUTO_MODES, *GATES) if name in known]
    current = driver.get_control_values(sensor, toggles)
    # A toggle that isn't being restored keeps its current value
    final = {name: defaults.get(name, current[name]) for name in toggles}
    left_alone = set(SESSION_CONTROLS)
    for mode, controls in AUTO_MODES.items():
        if current.get(mode) == 1 and final[mode] == 1:
            left_alone.update(controls)
    for gate, controls in GATES.items():
        if final.get(gate) == 0:
            left_alone.update(controls)
    return left_alone
