from dataclasses import replace

import pytest
from typer.testing import CliRunner

from realsense_cli.cli import app
from realsense_cli.driver.realsense import ADVANCED_GROUPS, Realsense
from realsense_cli.driver.software import (
    D435,
    D435_DEFAULT_TUNING,
    D435_SENSORS,
    SoftwareCamera,
    d435,
    software_driver,
)
from realsense_cli.types import Sensor
from tests.test_json import invoke_json, json_error

runner = CliRunner()

# Every advanced control the SDK has: 13 groups, 63 fields
GROUPS = list(ADVANCED_GROUPS)
FIELDS = 63

UINT32_MAX = 2**32 - 1
FLOAT32_MAX = 3.4028235e38


def _advanced_mode_off():
    return d435(advanced_mode=False)


advanced_mode_off = pytest.mark.parametrize("camera", [_advanced_mode_off], indirect=True)


def _controls(*args: str) -> dict[str, dict]:
    controls = invoke_json("advanced", "list", *args)["controls"]
    return {control["name"]: control for control in controls}


def test_list_shows_every_control(driver):
    payload = invoke_json("advanced", "list")
    assert payload["advanced_mode_enabled"] is False
    controls = payload["controls"]
    assert len(controls) == FIELDS
    assert list(dict.fromkeys(c["group"] for c in controls)) == GROUPS
    by_name = {c["name"]: c for c in controls}
    assert by_name["rsm.diffThresh"] == {
        "name": "rsm.diffThresh",
        "group": "rsm",
        "vtype": "float",
        "min_value": 0.0,
        "max_value": FLOAT32_MAX,
    }
    assert by_name["depth_control.plusIncrement"]["vtype"] == "int"
    assert by_name["depth_control.plusIncrement"]["max_value"] == UINT32_MAX
    assert by_name["depth_table.depthClampMax"]["max_value"] == 2**31 - 1  # int32


def test_list_shows_no_range_for_hdad(driver):
    controls = _controls("hdad")
    assert list(controls) == ["hdad.lambdaCensus", "hdad.lambdaAD", "hdad.ignoreSAD"]
    for control in controls.values():
        assert control["min_value"] is None
        assert control["max_value"] is None


def test_list_takes_groups_in_any_case(driver):
    controls = _controls("RSM", "census")
    assert list(controls) == [
        "rsm.rsmBypass",
        "rsm.diffThresh",
        "rsm.sloRauDiffThresh",
        "rsm.removeThresh",
        "census.uDiameter",
        "census.vDiameter",
    ]


def test_list_prints_a_table(driver):
    result = runner.invoke(app, ["advanced", "list", "rsm", "hdad"])
    assert result.exit_code == 0, result.output
    lines = list(map(str.split, result.stdout.splitlines()))
    assert ["Name", "Type", "Min", "Max"] in lines
    assert ["rsm.removeThresh", "int", "0", str(UINT32_MAX)] in lines
    assert ["hdad.ignoreSAD", "int", "-", "-"] in lines


def test_get_reads_fields(driver):
    assert invoke_json("advanced", "get", "rsm.diffThresh", "census.uDiameter") == {
        "values": {"rsm.diffThresh": 4.0, "census.uDiameter": 9},
        "advanced_mode_enabled": False,
    }


def test_get_spells_names_as_the_sdk_does(driver):
    values = invoke_json("advanced", "get", "RSM.DIFFTHRESH", "Depth_Control.plusincrement")
    assert values["values"] == {"rsm.diffThresh": 4.0, "depth_control.plusIncrement": 10}


def test_get_reads_a_group(driver):
    values = invoke_json("advanced", "get", "color_correction")["values"]
    assert len(values) == 12
    # float32 values read back as the decimal they were set to
    assert values["color_correction.colorCorrection1"] == 0.298828


def test_get_reads_each_name_once(driver):
    values = invoke_json("advanced", "get", "rsm.diffThresh", "rsm", "RSM.diffthresh")
    assert list(values["values"]) == [
        "rsm.diffThresh",
        "rsm.rsmBypass",
        "rsm.sloRauDiffThresh",
        "rsm.removeThresh",
    ]


def test_get_all_reads_the_default_tuning(driver):
    values = invoke_json("advanced", "get", "--all")["values"]
    assert len(values) == FIELDS
    assert values == {
        f"{group}.{field}": pytest.approx(value)
        for group, fields in D435_DEFAULT_TUNING.items()
        for field, value in fields.items()
    }


def test_get_reads_the_current_values(driver, camera):
    camera.advanced_mode.groups["rsm"].diffThresh = 2.5
    driver.set_control_values(Sensor.STEREO_MODULE, {"depth_units": 0.0001})
    values = invoke_json("advanced", "get", "rsm.diffThresh", "depth_table.depthUnits")
    # the depth table holds the depth units in micrometers
    assert values["values"] == {"rsm.diffThresh": 2.5, "depth_table.depthUnits": 100}


def test_get_prints_a_table(driver):
    result = runner.invoke(app, ["advanced", "get", "rsm.diffThresh", "census.uDiameter"])
    assert result.exit_code == 0, result.output
    lines = list(map(str.split, result.stdout.splitlines()))
    assert ["Name", "Value"] in lines
    assert ["rsm.diffThresh", "4.0"] in lines
    assert ["census.uDiameter", "9"] in lines


def test_get_needs_names_or_all(driver):
    result = runner.invoke(app, ["advanced", "get"])
    assert result.exit_code == 2, result.output
    assert "--all" in result.stderr


def test_unknown_group_lists_the_groups(driver):
    error = json_error(runner.invoke(app, ["--json", "advanced", "get", "nope.diffThresh"]), 5)
    assert error["type"] == "UnknownAdvancedControl"
    assert error["message"] == (
        f"Unknown advanced-control group 'nope'. Valid groups: {', '.join(GROUPS)}"
    )


def test_unknown_field_lists_the_group_fields(driver):
    error = json_error(runner.invoke(app, ["--json", "advanced", "list", "rsm.nope"]), 5)
    assert error["message"] == (
        "Advanced-control group 'rsm' has no field 'nope'. "
        "Valid fields: rsmBypass, diffThresh, sloRauDiffThresh, removeThresh"
    )


@advanced_mode_off
def test_unknown_name_fails_before_turning_advanced_mode_on(driver):
    json_error(runner.invoke(app, ["--json", "advanced", "get", "rsm.nope", "--yes"]), 5)
    assert driver.advanced_mode() is False


@advanced_mode_off
@pytest.mark.parametrize("command", [["list"], ["get", "--all"]])
def test_advanced_mode_off_without_tty_needs_yes(driver, command):
    result = runner.invoke(app, ["advanced", *command])
    assert result.exit_code == 8, result.output
    assert "--yes" in result.stderr
    assert driver.advanced_mode() is False


@advanced_mode_off
def test_advanced_mode_off_under_json_needs_yes_even_on_tty(driver, tty):
    error = json_error(runner.invoke(app, ["--json", "advanced", "list"]), 8)
    assert error["type"] == "ConfirmationRequired"
    assert driver.advanced_mode() is False


@advanced_mode_off
@pytest.mark.parametrize("command", [["list", "rsm"], ["get", "rsm"]])
def test_yes_turns_advanced_mode_on(driver, command):
    payload = invoke_json("advanced", *command, "--yes")
    assert payload["advanced_mode_enabled"] is True
    assert driver.advanced_mode() is True


@advanced_mode_off
def test_confirmed_prompt_turns_advanced_mode_on(driver, tty):
    result = runner.invoke(app, ["advanced", "get", "rsm.diffThresh"], input="y\n")
    assert result.exit_code == 0, result.output
    assert f"Advanced mode is off on {D435.name} ({D435.serial}). Turn it on?" in (
        result.stderr
    )
    assert driver.advanced_mode() is True
    assert ["rsm.diffThresh", "4.0"] in map(str.split, result.stdout.splitlines())


@advanced_mode_off
def test_declined_prompt_aborts(driver, tty):
    result = runner.invoke(app, ["advanced", "list"], input="n\n")
    assert result.exit_code == 1, result.output
    assert driver.advanced_mode() is False


@pytest.mark.parametrize("camera", [lambda: SoftwareCamera(D435, D435_SENSORS)], indirect=True)
def test_device_without_advanced_mode_fails(driver):
    error = json_error(runner.invoke(app, ["--json", "advanced", "list"]), 1)
    assert error["message"] == f"{D435.name} ({D435.serial}) has no advanced mode"


def test_several_devices_use_the_first_with_a_warning(inject_driver):
    second = SoftwareCamera(replace(D435, serial="987654321"), D435_SENSORS)
    inject_driver(software_driver(d435(), second))
    result = runner.invoke(app, ["advanced", "get", "rsm.diffThresh"])
    assert result.exit_code == 0, result.output
    assert f"using device: '{D435.serial}'" in result.stderr


class _PerGroupOnly:
    """An advanced mode with no bulk read, as on pyrealsense2 < 2.59"""

    def __init__(self, advanced_mode):
        self._advanced_mode = advanced_mode

    def __getattr__(self, name: str):
        if name == "get_all_controls":
            raise AttributeError(name)
        return getattr(self._advanced_mode, name)


def test_per_group_reads_match_the_bulk_read(camera):
    camera.advanced_mode.groups["rsm"].diffThresh = 2.5
    bulk = software_driver(camera).advanced_controls()
    per_group = Realsense(
        [camera.device], {D435.serial: _PerGroupOnly(camera.advanced_mode)}
    ).advanced_controls()
    assert per_group == bulk
    hdad = [c for c in per_group if c.group == "hdad"]
    assert all(c.min_value is None and c.max_value is None for c in hdad)
