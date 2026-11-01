import json
import re
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from realsense_cli.cli import app
from realsense_cli.driver.software import (
    D435,
    D435_SENSORS,
    SoftwareCamera,
    d435,
    software_driver,
)
from realsense_cli.preset import valid_value
from realsense_cli.types import Sensor
from tests.test_json import invoke_json, json_error

runner = CliRunner()

# The advanced-control keys librealsense writes, and the controls the simulated D435 has
ADVANCED_KEYS = 70
CONTROL_KEYS = {
    "controls-laserpower": "150",
    "controls-autoexposure-manual": "8500",
    "controls-autoexposure-auto": "True",
    "controls-color-brightness": "0",
}


def _advanced_mode_off():
    return d435(advanced_mode=False)


advanced_mode_off = pytest.mark.parametrize("camera", [_advanced_mode_off], indirect=True)


def _depth_controls() -> dict[str, dict]:
    controls = invoke_json("config", "list", "depth")["controls"]
    return {control["name"]: control for control in controls}


def test_save_writes_the_preset_file(driver, tmp_path):
    path = tmp_path / "preset.json"
    assert invoke_json("preset", "save", str(path)) == {
        "saved": str(path),
        "keys": ADVANCED_KEYS + len(CONTROL_KEYS),
        "advanced_mode_enabled": False,
    }
    preset = json.loads(path.read_text())
    assert preset["schema version"] == 1
    assert preset["device"] == {
        "name": D435.name,
        "product line": "D400",
        "fw version": D435.fw,
    }
    parameters = preset["parameters"]
    assert len(parameters) == ADVANCED_KEYS + len(CONTROL_KEYS)
    assert {k: v for k, v in parameters.items() if k.startswith("controls-")} == CONTROL_KEYS


def test_save_writes_keys_as_librealsense_does(driver, tmp_path):
    """Values are strings, scaled and inverted where librealsense scales or inverts them"""
    path = tmp_path / "preset.json"
    invoke_json("preset", "save", str(path))
    text = path.read_text()
    assert text.startswith('{\n    "device": {\n        "fw version"')
    parameters = json.loads(text)["parameters"]
    assert parameters["param-robbinsmonroincrement"] == "10"
    assert parameters["param-rsmremovethreshold"] == "0.375"  # 63 / 168
    assert parameters["param-usersm"] == "1"  # rsmBypass 0
    assert parameters["param-regioncolorthresholdr"] == "0.0499022"  # 51 / 1022
    assert parameters["aux-param-colorcorrection1"] == "0.298828"
    assert parameters["param-depthclampmax"] == "65536"
    assert parameters["param-depthunits"] == parameters["param-zunits"] == "1000"
    # read-only duplicates of aux-param-colorcorrection*, which librealsense doesn't write
    assert "param-colorcorrection1" not in parameters


def test_save_holds_the_current_controls(driver, tmp_path):
    driver.set_control_values(
        Sensor.STEREO_MODULE,
        {"laser_power": 30, "enable_auto_exposure": 0, "depth_units": 0.0001},
    )
    path = tmp_path / "preset.json"
    invoke_json("preset", "save", str(path))
    parameters = json.loads(path.read_text())["parameters"]
    assert parameters["controls-laserpower"] == "30"
    assert parameters["controls-autoexposure-auto"] == "False"
    assert parameters["param-depthunits"] == "100"


def test_save_prints_the_key_count(driver, tmp_path):
    path = tmp_path / "preset.json"
    result = runner.invoke(app, ["preset", "save", str(path)])
    assert result.exit_code == 0, result.output
    assert f"Saved {ADVANCED_KEYS + len(CONTROL_KEYS)} keys to {path}" in result.stdout


def test_existing_file_is_refused(driver, tmp_path):
    path = tmp_path / "preset.json"
    path.write_text("keep")
    error = json_error(runner.invoke(app, ["--json", "preset", "save", str(path)]), 7)
    assert "--force" in error["message"]
    assert path.read_text() == "keep"


def test_force_overwrites(driver, tmp_path):
    path = tmp_path / "preset.json"
    path.write_text("old")
    invoke_json("preset", "save", str(path), "--force")
    assert json.loads(path.read_text())["schema version"] == 1


def test_default_file_is_named_by_timestamp(driver, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    saved = Path(invoke_json("preset", "save")["saved"])
    assert saved.parent == tmp_path
    assert re.fullmatch(r"rs-preset-\d{8}-\d{6}\.json", saved.name)
    assert json.loads(saved.read_text())["schema version"] == 1


def test_default_file_never_overwrites(driver, tmp_path, monkeypatch):
    """A save in the same second gets -2, -3 ... appended"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "realsense_cli.commands.preset.datetime",
        Mock(now=lambda: datetime(2026, 1, 2, 3, 4, 5)),
    )
    names = [Path(invoke_json("preset", "save")["saved"]).name for _ in range(3)]
    assert names == [
        "rs-preset-20260102-030405.json",
        "rs-preset-20260102-030405-2.json",
        "rs-preset-20260102-030405-3.json",
    ]


@advanced_mode_off
def test_advanced_mode_off_hides_its_controls(driver):
    controls = _depth_controls()
    assert "visual_preset" not in controls
    assert controls["depth_units"]["read_only"]
    assert invoke_json("info")["device"]["advanced_mode"] == "NO"


def test_advanced_mode_on_has_its_controls(driver):
    controls = _depth_controls()
    assert controls["visual_preset"]["default_value"] == 0
    assert not controls["depth_units"]["read_only"]
    assert invoke_json("info")["device"]["advanced_mode"] == "YES"


@advanced_mode_off
def test_advanced_mode_off_without_tty_needs_yes(driver, tmp_path):
    path = tmp_path / "preset.json"
    result = runner.invoke(app, ["preset", "save", str(path)])
    assert result.exit_code == 8, result.output
    assert "--yes" in result.stderr
    assert not path.exists()
    assert driver.advanced_mode() is False


@advanced_mode_off
def test_advanced_mode_off_under_json_needs_yes_even_on_tty(driver, tty, tmp_path):
    path = tmp_path / "preset.json"
    error = json_error(runner.invoke(app, ["--json", "preset", "save", str(path)]), 8)
    assert error["type"] == "ConfirmationRequired"
    assert not path.exists()
    assert driver.advanced_mode() is False


@advanced_mode_off
def test_yes_turns_advanced_mode_on(driver, tmp_path):
    path = tmp_path / "preset.json"
    payload = invoke_json("preset", "save", str(path), "--yes")
    assert payload["advanced_mode_enabled"] is True
    assert driver.advanced_mode() is True
    assert json.loads(path.read_text())["parameters"]
    controls = _depth_controls()
    assert "visual_preset" in controls
    assert not controls["depth_units"]["read_only"]
    assert invoke_json("info")["device"]["advanced_mode"] == "YES"


@advanced_mode_off
def test_confirmed_prompt_turns_advanced_mode_on(driver, tty, tmp_path):
    path = tmp_path / "preset.json"
    result = runner.invoke(app, ["preset", "save", str(path)], input="y\n")
    assert result.exit_code == 0, result.output
    assert f"Advanced mode is off on {D435.name} ({D435.serial}). Turn it on?" in (
        result.stderr
    )
    assert driver.advanced_mode() is True
    assert path.exists()


@advanced_mode_off
def test_declined_prompt_aborts(driver, tty, tmp_path):
    path = tmp_path / "preset.json"
    result = runner.invoke(app, ["preset", "save", str(path)], input="n\n")
    assert result.exit_code == 1, result.output
    assert driver.advanced_mode() is False
    assert not path.exists()


@advanced_mode_off
def test_device_that_does_not_reconnect_fails(driver, monkeypatch, tmp_path):
    monkeypatch.setattr(driver, "enable_advanced_mode", lambda timeout: False)
    path = tmp_path / "preset.json"
    error = json_error(runner.invoke(app, ["--json", "preset", "save", str(path), "-y"]), 3)
    assert "did not reconnect within 30s" in error["message"]
    assert not path.exists()


@pytest.mark.parametrize("camera", [lambda: SoftwareCamera(D435, D435_SENSORS)], indirect=True)
def test_device_without_advanced_mode_fails(driver, tmp_path):
    path = tmp_path / "preset.json"
    error = json_error(runner.invoke(app, ["--json", "preset", "save", str(path)]), 1)
    assert error["message"] == f"{D435.name} ({D435.serial}) has no advanced mode"
    assert not path.exists()


def test_several_devices_use_the_first_with_a_warning(inject_driver, tmp_path):
    second = SoftwareCamera(replace(D435, serial="987654321"), D435_SENSORS)
    inject_driver(software_driver(d435(), second))
    path = tmp_path / "preset.json"
    result = runner.invoke(app, ["preset", "save", str(path)])
    assert result.exit_code == 0, result.output
    assert f"using device: '{D435.serial}'" in result.stderr
    assert path.exists()


def _write(path: Path, preset) -> Path:
    path.write_text(preset if isinstance(preset, str) else json.dumps(preset))
    return path


def _laser_power(driver) -> float:
    return driver.get_control_values(Sensor.STEREO_MODULE, ["laser_power"])["laser_power"]


def test_load_restores_a_saved_preset(driver, camera, tmp_path):
    path = tmp_path / "preset.json"
    invoke_json("preset", "save", str(path))
    saved = driver.serialize_preset()
    driver.set_control_values(
        Sensor.STEREO_MODULE, {"laser_power": 30, "depth_units": 0.0001, "visual_preset": 3}
    )
    camera.advanced_mode.groups["rsm"].diffThresh = 2.5
    camera.advanced_mode.groups["census"].uDiameter = 5
    assert driver.serialize_preset() != saved

    assert invoke_json("preset", "load", str(path)) == {
        "loaded": str(path),
        "advanced_mode_enabled": False,
    }
    assert driver.serialize_preset() == saved
    values = driver.get_control_values(
        Sensor.STEREO_MODULE, ["laser_power", "depth_units", "visual_preset"]
    )
    assert values["laser_power"] == 150
    assert values["depth_units"] == pytest.approx(0.001)
    assert values["visual_preset"] == 0  # custom


def test_load_prints_the_file_and_device(driver, tmp_path):
    path = _write(tmp_path / "preset.json", {"controls-laserpower": "60"})
    result = runner.invoke(app, ["preset", "load", str(path)])
    assert result.exit_code == 0, result.output
    assert f"Loaded preset {path} onto {D435.name} ({D435.serial})" in result.stdout


def test_load_reports_a_relative_file_as_absolute(driver, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write(tmp_path / "preset.json", {"controls-laserpower": "60"})
    assert invoke_json("preset", "load", "preset.json")["loaded"] == str(
        tmp_path / "preset.json"
    )


def test_load_overlays_a_partial_legacy_file(driver, camera, tmp_path):
    """The legacy flat format; keys the file leaves out keep their values"""
    path = _write(
        tmp_path / "flat.json",
        {"controls-laserpower": 60, "param-rsmdiffthreshold": "3.5"},
    )
    groups = camera.advanced_mode.groups
    invoke_json("preset", "load", str(path))
    assert _laser_power(driver) == 60
    assert groups["rsm"].diffThresh == 3.5
    assert groups["depth_control"].plusIncrement == 10


def test_load_scales_and_inverts_keys_as_librealsense_does(driver, camera, tmp_path):
    path = _write(
        tmp_path / "preset.json",
        {
            "schema version": 1,
            "parameters": {
                "param-rsmremovethreshold": "0.5",  # x 168
                "param-regioncolorthresholdr": "0.1",  # x 1022, rounded
                "param-usersm": "0",  # rsmBypass 1
                "param-zunits": "100",
            },
        },
    )
    invoke_json("preset", "load", str(path))
    groups = camera.advanced_mode.groups
    assert groups["rsm"].removeThresh == 84
    assert groups["rau_thresholds_control"].rauDiffThresholdRed == 102
    assert groups["rsm"].rsmBypass == 1
    depth_units = driver.get_control_values(Sensor.STEREO_MODULE, ["depth_units"])
    assert depth_units["depth_units"] == pytest.approx(0.0001)


def test_load_skips_exposure_while_auto_exposure_is_on(driver, tmp_path):
    """As librealsense writes a manual exposure only with auto exposure off"""
    stereo = Sensor.STEREO_MODULE
    path = _write(
        tmp_path / "preset.json",
        {"controls-autoexposure-auto": "True", "controls-autoexposure-manual": "100"},
    )
    invoke_json("preset", "load", str(path))
    assert driver.get_control_values(stereo, ["exposure"])["exposure"] == 8500

    _write(path, {"controls-autoexposure-auto": "False", "controls-autoexposure-manual": "100"})
    invoke_json("preset", "load", str(path))
    values = driver.get_control_values(stereo, ["exposure", "enable_auto_exposure"])
    assert values == {"exposure": 100, "enable_auto_exposure": 0}


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("{not json", "is not valid JSON"),
        ("[1, 2]", "is not a preset file"),
        (json.dumps({"parameters": {}}), "is not a preset file"),
        (json.dumps({"schema version": 1}), "is not a preset file"),
        (json.dumps({"schema version": 1, "parameters": []}), "is not a preset file"),
        (json.dumps({"schema version": 2, "parameters": {}}), "has schema version 2"),
    ],
)
def test_load_refuses_a_file_that_is_not_a_preset(driver, tmp_path, content, message):
    path = _write(tmp_path / "preset.json", content)
    error = json_error(runner.invoke(app, ["--json", "preset", "load", str(path)]), 7)
    assert message in error["message"]
    assert _laser_power(driver) == 150


def test_load_refuses_a_file_that_is_not_text(driver, tmp_path):
    path = tmp_path / "preset.json"
    path.write_bytes(b"\xff\xfe\x00")
    error = json_error(runner.invoke(app, ["--json", "preset", "load", str(path)]), 7)
    assert "is not valid JSON" in error["message"]


def test_load_lists_every_invalid_value(driver, tmp_path):
    path = _write(
        tmp_path / "preset.json",
        {
            "schema version": 1,
            "parameters": {
                "controls-laserpower": "60",
                "param-rsmdiffthreshold": "abc",
                "controls-autoexposure-auto": "yes",
                "param-usersm": True,
            },
        },
    )
    error = json_error(runner.invoke(app, ["--json", "preset", "load", str(path)]), 7)
    assert error["type"] == "InvalidValue"
    message = error["message"]
    assert 'param-rsmdiffthreshold ("abc")' in message
    assert 'controls-autoexposure-auto ("yes")' in message
    assert "param-usersm (true)" in message
    assert "controls-laserpower" not in message
    assert "off, on, auto, True, False" in message
    assert _laser_power(driver) == 150


@pytest.mark.parametrize(
    "value", ["10", "-1.5", ".5", "1e3", "2.", 3, 2.5, "off", "on", "auto", "True", "False"]
)
def test_valid_preset_values(value):
    assert valid_value(value)


@pytest.mark.parametrize(
    "value", ["abc", "", " 1", "1,5", "nan", "inf", "ON", "true", True, None, [1], {}]
)
def test_invalid_preset_values(value):
    assert not valid_value(value)


def test_no_validate_hands_bad_values_to_the_sdk(driver, camera, tmp_path):
    """The SDK loads a value it can't read as 0"""
    path = _write(
        tmp_path / "preset.json",
        {"param-rsmdiffthreshold": "abc", "controls-autoexposure-auto": "maybe"},
    )
    invoke_json("preset", "load", str(path), "--no-validate")
    assert camera.advanced_mode.groups["rsm"].diffThresh == 0
    values = driver.get_control_values(Sensor.STEREO_MODULE, ["enable_auto_exposure"])
    assert values["enable_auto_exposure"] == 0


def test_no_validate_still_needs_a_preset_file(driver, tmp_path):
    path = _write(tmp_path / "preset.json", "{not json")
    cmd = ["--json", "preset", "load", str(path), "--no-validate"]
    assert "is not valid JSON" in json_error(runner.invoke(app, cmd), 7)["message"]


@pytest.mark.parametrize(
    ("preset", "message"),
    [
        (
            {"controls-laserpower": "60", "param-bogus": "1"},
            "param-bogus key is not supported by the connected device!",
        ),
        (
            # the simulated D435 has no emitter_enabled control
            {"controls-laserpower": "60", "controls-laserstate": "on"},
            "controls-laserstate key is not supported by the connected device!",
        ),
        (
            {
                "schema version": 1,
                "device": {"product line": "D500"},
                "parameters": {"controls-laserpower": "60"},
            },
            "preset product line does not match the connected device",
        ),
    ],
)
@pytest.mark.parametrize("no_validate", [[], ["--no-validate"]])
def test_load_passes_sdk_errors_through(driver, tmp_path, preset, message, no_validate):
    path = _write(tmp_path / "preset.json", preset)
    error = json_error(
        runner.invoke(app, ["--json", "preset", "load", str(path), *no_validate]), 7
    )
    assert error["message"] == f"The device refused the preset: {message}"
    assert _laser_power(driver) == 150


def test_load_accepts_another_device_of_the_product_line(driver, tmp_path):
    """librealsense checks only the product line, so a D415 preset loads on a D435"""
    path = _write(
        tmp_path / "preset.json",
        {
            "schema version": 1,
            "device": {"name": "Intel RealSense D415", "product line": "D400"},
            "parameters": {"controls-laserpower": "60"},
        },
    )
    invoke_json("preset", "load", str(path))
    assert _laser_power(driver) == 60


def test_load_of_a_missing_file_is_a_usage_error(driver, tmp_path):
    path = tmp_path / "missing.json"
    error = json_error(runner.invoke(app, ["--json", "preset", "load", str(path)]), 2)
    assert error["type"] == "UsageError"


@advanced_mode_off
def test_load_turns_advanced_mode_on_with_yes(driver, tmp_path):
    path = _write(tmp_path / "preset.json", {"controls-laserpower": "60"})
    payload = invoke_json("preset", "load", str(path), "--yes")
    assert payload["advanced_mode_enabled"] is True
    assert driver.advanced_mode() is True
    assert _laser_power(driver) == 60


@advanced_mode_off
def test_load_without_tty_needs_yes(driver, tmp_path):
    path = _write(tmp_path / "preset.json", {"controls-laserpower": "60"})
    error = json_error(runner.invoke(app, ["--json", "preset", "load", str(path)]), 8)
    assert error["type"] == "ConfirmationRequired"
    assert driver.advanced_mode() is False
    assert _laser_power(driver) == 150


@advanced_mode_off
def test_load_checks_the_file_before_turning_advanced_mode_on(driver, tmp_path):
    path = _write(tmp_path / "preset.json", {"controls-laserpower": "lots"})
    json_error(runner.invoke(app, ["--json", "preset", "load", str(path), "--yes"]), 7)
    assert driver.advanced_mode() is False


@pytest.mark.parametrize("camera", [lambda: SoftwareCamera(D435, D435_SENSORS)], indirect=True)
def test_load_on_a_device_without_advanced_mode_fails(driver, tmp_path):
    path = _write(tmp_path / "preset.json", {"controls-laserpower": "60"})
    error = json_error(runner.invoke(app, ["--json", "preset", "load", str(path)]), 1)
    assert error["message"] == f"{D435.name} ({D435.serial}) has no advanced mode"
