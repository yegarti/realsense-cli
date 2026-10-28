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
