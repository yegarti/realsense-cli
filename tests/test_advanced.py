import json
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
from realsense_cli.errors import InvalidValue
from realsense_cli.types import Sensor
from tests.test_json import invoke_json, json_error

runner = CliRunner()

# Every advanced control the SDK has: 13 groups, 63 fields
GROUPS = list(ADVANCED_GROUPS)
FIELDS = 63


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
        "max_value": 7.96875,
    }
    assert by_name["depth_control.plusIncrement"]["vtype"] == "int"
    assert by_name["depth_control.plusIncrement"]["max_value"] == 255
    assert by_name["census.uDiameter"]["min_value"] == 1
    # float32 ranges read back as the shortest decimal that is the same float32
    assert by_name["color_correction.colorCorrection1"]["max_value"] == 1.9990234


def test_list_shows_no_range_for_hdad_and_ae_control(driver):
    controls = _controls("hdad", "ae_control")
    assert list(controls) == [
        "hdad.lambdaCensus",
        "hdad.lambdaAD",
        "hdad.ignoreSAD",
        "ae_control.meanIntensitySetPoint",
    ]
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
    assert ["rsm.removeThresh", "int", "0", "168"] in lines
    assert ["rsm.diffThresh", "float", "0.0", "7.96875"] in lines
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
@pytest.mark.parametrize("command", [["list"], ["get", "--all"], ["restore"]])
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
@pytest.mark.parametrize("command", [["list", "rsm"], ["get", "rsm"], ["restore"]])
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
    no_range = [c for c in per_group if c.group in ("hdad", "ae_control")]
    assert len(no_range) == 4
    assert all(c.min_value is None and c.max_value is None for c in no_range)


def test_set_writes_and_reads_back(driver):
    payload = invoke_json("advanced", "set", "rsm.diffThresh=0.3", "census.uDiameter=5")
    # the float32 0.3 reads back as 0.3, not 0.30000001192092896
    assert payload == {
        "values": {"rsm.diffThresh": 0.3, "census.uDiameter": 5},
        "advanced_mode_enabled": False,
    }
    assert (
        invoke_json("advanced", "get", "rsm.diffThresh", "census.uDiameter")["values"]
        == (payload["values"])
    )


def test_set_spells_names_as_the_sdk_does(driver):
    values = invoke_json("advanced", "set", "RSM.REMOVETHRESH=50", "Rsm.removethresh=60")
    assert values["values"] == {"rsm.removeThresh": 60}


def test_set_writes_a_group_in_one_read_modify_write(driver, camera, monkeypatch):
    writes = []
    write = camera.advanced_mode.set
    monkeypatch.setattr(
        camera.advanced_mode,
        "set",
        lambda group, values: (writes.append(group), write(group, values)),
    )
    values = invoke_json(
        "advanced", "set", "rsm.diffThresh=2", "census.vDiameter=3", "rsm.removeThresh=100"
    )["values"]
    assert sorted(writes) == ["census", "rsm"]
    assert values == {"rsm.diffThresh": 2.0, "census.vDiameter": 3, "rsm.removeThresh": 100}
    # the fields not named keep their values
    rsm = invoke_json("advanced", "get", "rsm")["values"]
    assert rsm["rsm.sloRauDiffThresh"] == D435_DEFAULT_TUNING["rsm"]["sloRauDiffThresh"]
    assert rsm["rsm.rsmBypass"] == D435_DEFAULT_TUNING["rsm"]["rsmBypass"]


def test_set_moves_the_visual_preset_to_custom(driver):
    driver.set_control_values(Sensor.STEREO_MODULE, {"visual_preset": 1})
    invoke_json("advanced", "set", "rsm.diffThresh=2")
    assert driver.get_control_values(Sensor.STEREO_MODULE, ["visual_preset"]) == {
        "visual_preset": 0
    }


def test_set_depth_units_through_the_depth_table(driver):
    invoke_json("advanced", "set", "depth_table.depthUnits=100")
    units = driver.get_control_values(Sensor.STEREO_MODULE, ["depth_units"])["depth_units"]
    assert units == pytest.approx(0.0001)


def test_set_prints_a_table(driver):
    result = runner.invoke(app, ["advanced", "set", "rsm.diffThresh=0.5", "census.uDiameter=7"])
    assert result.exit_code == 0, result.output
    lines = list(map(str.split, result.stdout.splitlines()))
    assert ["Name", "Value"] in lines
    assert ["rsm.diffThresh", "0.5"] in lines
    assert ["census.uDiameter", "7"] in lines


def _set_error(*args: str, code: int = 7) -> str:
    return json_error(runner.invoke(app, ["--json", "advanced", "set", *args]), code)["message"]


def _unchanged(driver):
    assert invoke_json("advanced", "get", "rsm", "hdad")["values"] == {
        f"{group}.{field}": pytest.approx(value)
        for group in ("rsm", "hdad")
        for field, value in D435_DEFAULT_TUNING[group].items()
    }


def test_set_out_of_range_writes_nothing(driver):
    message = _set_error("rsm.diffThresh=1", "rsm.removeThresh=169")
    assert message == (
        "Advanced control 'rsm.removeThresh' takes an int from 0 to 168, not 169; "
        "--no-validate skips the range check"
    )
    _unchanged(driver)


def test_set_out_of_range_float_gives_the_float_range(driver):
    message = _set_error("color_correction.colorCorrection1=-2.5")
    assert message == (
        "Advanced control 'color_correction.colorCorrection1' takes a float from -2 to "
        "1.9990234, not -2.5; --no-validate skips the range check"
    )


@pytest.mark.parametrize("no_validate", [[], ["--no-validate"]])
def test_set_fraction_for_an_int_field_fails(driver, no_validate):
    message = _set_error("rsm.diffThresh=1", "rsm.removeThresh=2.5", *no_validate)
    assert message == "Advanced control 'rsm.removeThresh' takes an int, not 2.5"
    _unchanged(driver)


def test_set_negative_for_an_unsigned_field_fails_without_validation(driver):
    message = _set_error("rsm.diffThresh=1", "rsm.removeThresh=-1", "--no-validate")
    assert (
        message
        == "Advanced control 'rsm.removeThresh' can't hold -1: the SDK's int field rejects it"
    )
    _unchanged(driver)


def test_set_skips_the_range_check_for_a_field_without_one(driver):
    values = invoke_json("advanced", "set", "hdad.lambdaAD=12345.5", "hdad.ignoreSAD=7")
    assert values["values"] == {"hdad.lambdaAD": 12345.5, "hdad.ignoreSAD": 7}
    # the SDK's struct still can't hold a negative for its unsigned field
    message = _set_error("rsm.diffThresh=1", "hdad.ignoreSAD=-1")
    assert (
        message
        == "Advanced control 'hdad.ignoreSAD' can't hold -1: the SDK's int field rejects it"
    )


def test_no_validate_skips_the_range_check(driver):
    values = invoke_json(
        "advanced",
        "set",
        "rsm.removeThresh=500",
        "depth_table.depthClampMin=-5",
        "--no-validate",
    )
    assert values["values"] == {"rsm.removeThresh": 500, "depth_table.depthClampMin": -5}


@pytest.mark.parametrize(
    "assignment", ["rsm.diffThresh", "rsm.diffThresh=x", "rsm.diffThresh=nan"]
)
def test_set_needs_a_numeric_value(driver, assignment):
    message = _set_error(assignment)
    assert (
        message == f"Failed to parse '{assignment}', expected NAME=VALUE with a numeric VALUE"
    )


def test_set_needs_a_field_not_a_group(driver):
    message = _set_error("RSM=1", code=5)
    assert message == (
        "'RSM' is a group; set one of its fields as group.field. "
        "Valid fields: rsmBypass, diffThresh, sloRauDiffThresh, removeThresh"
    )


@advanced_mode_off
@pytest.mark.parametrize(
    ("assignment", "code"), [("rsm.nope=1", 5), ("rsm=1", 5), ("rsm.diffThresh=x", 7)]
)
def test_set_bad_name_or_value_fails_before_turning_advanced_mode_on(driver, assignment, code):
    _set_error(assignment, "--yes", code=code)
    assert driver.advanced_mode() is False


@advanced_mode_off
def test_set_advanced_mode_off_without_tty_needs_yes(driver):
    _set_error("rsm.diffThresh=1", code=8)
    assert driver.advanced_mode() is False


@advanced_mode_off
def test_set_yes_turns_advanced_mode_on(driver):
    payload = invoke_json("advanced", "set", "rsm.diffThresh=1", "--yes")
    assert payload == {"values": {"rsm.diffThresh": 1.0}, "advanced_mode_enabled": True}


@pytest.mark.parametrize("value", ["1.9990234375", "1.99902344"])
def test_set_takes_a_float_range_bound_as_the_float32_it_is(driver, value):
    # the maximum reads back as 1.9990234, the shortest decimal for the float32 1.9990234375
    values = invoke_json("advanced", "set", f"color_correction.colorCorrection1={value}")
    assert values["values"] == {"color_correction.colorCorrection1": 1.9990234}


def test_set_float_beyond_float32_is_out_of_range(driver):
    message = _set_error("rsm.diffThresh=1e40")
    assert message == (
        "Advanced control 'rsm.diffThresh' takes a float from 0 to 7.96875, not 1e+40; "
        "--no-validate skips the range check"
    )


STEREO = Sensor.STEREO_MODULE


def _preset_row(old: float, new: float = 1.0) -> dict:
    return {"sensor": STEREO, "control": "visual_preset", "old": old, "new": new}


def _default_rsm() -> dict:
    return {f"rsm.{field}": value for field, value in D435_DEFAULT_TUNING["rsm"].items()}


def test_restore_brings_back_the_default_tuning(driver):
    invoke_json("advanced", "set", "rsm.diffThresh=2", "rsm.removeThresh=100")
    driver.set_control_values(STEREO, {"laser_power": 30, "enable_auto_exposure": 0})

    assert invoke_json("advanced", "restore") == {
        "restored": [
            _preset_row(old=0.0),
            {"sensor": STEREO, "control": "enable_auto_exposure", "old": 0.0, "new": 1.0},
            {"sensor": STEREO, "control": "laser_power", "old": 30.0, "new": 150.0},
        ],
        "failed": [],
        "advanced_mode_enabled": False,
    }
    assert invoke_json("advanced", "get", "rsm")["values"] == pytest.approx(_default_rsm())


def test_restore_writes_the_preset_even_when_it_reads_default(driver):
    driver.set_control_values(STEREO, {"visual_preset": 1})
    driver.set_control_values(STEREO, {"laser_power": 30})
    restored = invoke_json("advanced", "restore")["restored"]
    assert restored == [
        _preset_row(old=1.0),
        {"sensor": STEREO, "control": "laser_power", "old": 30.0, "new": 150.0},
    ]


def test_restore_prints_a_table(driver):
    driver.set_control_values(STEREO, {"laser_power": 30})
    result = runner.invoke(app, ["advanced", "restore"])
    assert result.exit_code == 0, result.output
    lines = list(map(str.split, result.stdout.splitlines()))
    assert ["Stereo", "Module", "visual_preset", "0.0", "1.0"] in lines
    assert ["Stereo", "Module", "laser_power", "30.0", "150.0"] in lines


def test_restore_reports_a_failed_write(driver, monkeypatch):
    def refuse(sensor, values):
        raise InvalidValue("Failed to set 'visual_preset'")

    monkeypatch.setattr(driver, "set_control_values", refuse)
    result = runner.invoke(app, ["--json", "advanced", "restore"])
    assert result.exit_code == InvalidValue.exit_code, result.output
    payload = json.loads(result.stdout)
    assert payload["restored"] == []
    assert payload["failed"] == [
        {"sensor": STEREO, "control": "visual_preset", "error": "Failed to set 'visual_preset'"}
    ]


def test_config_restore_leaves_a_loaded_preset_and_advanced_restore_undoes_it(driver, tmp_path):
    """
    `visual_preset`'s default is custom, which a load already set and which writes nothing,
    so only `rs advanced restore` brings the tuning back
    """
    path = tmp_path / "preset.json"
    path.write_text(json.dumps({"param-rsmdiffthreshold": "3.5"}))
    invoke_json("preset", "load", str(path))
    loaded = invoke_json("advanced", "get", "rsm.diffThresh")["values"]
    assert loaded != {"rsm.diffThresh": D435_DEFAULT_TUNING["rsm"]["diffThresh"]}

    invoke_json("config", "restore", "depth")
    assert invoke_json("advanced", "get", "rsm.diffThresh")["values"] == loaded

    invoke_json("advanced", "restore")
    assert invoke_json("advanced", "get", "rsm")["values"] == pytest.approx(_default_rsm())


@pytest.mark.parametrize("preset", [0, 3])
def test_writing_another_preset_keeps_the_tuning(driver, preset):
    """The SDK applies nothing for custom; the fake knows only the Default tuning"""
    invoke_json("advanced", "set", "rsm.diffThresh=2")
    driver.set_control_values(STEREO, {"laser_power": 30, "visual_preset": preset})
    assert invoke_json("advanced", "get", "rsm.diffThresh")["values"] == {"rsm.diffThresh": 2}
    assert driver.get_control_values(STEREO, ["laser_power"]) == {"laser_power": 30}


def test_a_control_written_after_the_preset_keeps_its_value(driver):
    driver.set_control_values(STEREO, {"visual_preset": 1, "laser_power": 30})
    assert driver.get_control_values(STEREO, ["laser_power"]) == {"laser_power": 30}
