import json
from dataclasses import replace

import pytest
from typer.testing import CliRunner

from realsense_cli.cli import app
from realsense_cli.driver.software import D435, SoftwareCamera, d435_sensor
from realsense_cli.errors import InvalidValue, UnknownControl
from realsense_cli.types import Option, Sensor

runner = CliRunner()

STEREO = Sensor.STEREO_MODULE
RGB = Sensor.RGB_CAMERA


def restore_json(*args: str) -> list[dict]:
    result = runner.invoke(app, ["--json", "config", "restore", *args])
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)["restored"]


def test_restores_every_sensor(driver):
    # A manual exposure turns auto exposure off on a real camera
    driver.set_control_values(
        STEREO, {"enable_auto_exposure": 0, "exposure": 1000, "laser_power": 30}
    )
    driver.set_control_values(RGB, {"brightness": 10})

    restored = restore_json()

    assert restored == [
        {"sensor": STEREO, "control": "exposure", "old": 1000.0, "new": 8500.0},
        {"sensor": STEREO, "control": "enable_auto_exposure", "old": 0.0, "new": 1.0},
        {"sensor": STEREO, "control": "laser_power", "old": 30.0, "new": 150.0},
        {"sensor": RGB, "control": "brightness", "old": 10.0, "new": 0.0},
    ]
    assert driver.get_control_values(
        STEREO, ["enable_auto_exposure", "exposure", "laser_power"]
    ) == {"enable_auto_exposure": 1.0, "exposure": 8500.0, "laser_power": 150.0}
    assert driver.get_control_values(RGB, ["brightness"]) == {"brightness": 0.0}


def test_sensor_narrows_restore(driver):
    driver.set_control_values(STEREO, {"laser_power": 30})
    driver.set_control_values(RGB, {"brightness": 10})

    restored = restore_json("depth")

    assert [r["control"] for r in restored] == ["laser_power"]
    assert driver.get_control_values(RGB, ["brightness"]) == {"brightness": 10.0}


def test_controls_narrow_restore(driver):
    driver.set_control_values(
        STEREO, {"exposure": 1000, "laser_power": 30, "enable_auto_exposure": 0}
    )

    restored = restore_json("depth", "exposure", "enable_auto_exposure")

    assert [r["control"] for r in restored] == ["exposure", "enable_auto_exposure"]
    assert driver.get_control_values(STEREO, ["laser_power"]) == {"laser_power": 30.0}


def test_unknown_control_writes_nothing(driver):
    driver.set_control_values(STEREO, {"exposure": 1000})

    result = runner.invoke(app, ["config", "restore", "depth", "exposure", "bogus"])

    assert result.exit_code == UnknownControl.exit_code, result.output
    assert driver.get_control_values(STEREO, ["exposure"]) == {"exposure": 1000.0}


def test_auto_driven_control_is_left_alone(driver):
    # Auto exposure is on and stays on, so the camera drives exposure: writing it would turn
    # auto exposure off on a real camera
    driver.set_control_values(STEREO, {"exposure": 1000})

    assert restore_json("depth") == []
    assert driver.get_control_values(STEREO, ["exposure"]) == {"exposure": 1000.0}


def test_read_only_control_is_skipped(driver):
    assert restore_json("depth", "asic_temperature") == []


def test_table_lists_old_and_new(driver):
    driver.set_control_values(STEREO, {"laser_power": 30})

    result = runner.invoke(app, ["config", "restore"])

    assert result.exit_code == 0, result.output
    line = next(line for line in result.stdout.splitlines() if "laser_power" in line)
    assert "Stereo Module" in line
    assert "30.0" in line
    assert "150.0" in line
    assert "exposure" not in result.stdout


def test_table_says_when_nothing_changed(driver):
    result = runner.invoke(app, ["config", "restore"])

    assert result.exit_code == 0, result.output
    assert "Nothing changed" in result.stdout


@pytest.fixture
def preset_driver(make_driver, monkeypatch):
    """A depth sensor with a visual preset, recording every control written in `.writes`."""
    spec = replace(
        d435_sensor(STEREO),
        options=[
            *d435_sensor(STEREO).options,
            Option("visual_preset", "", 0.0, 5.0, 1.0, 0.0, int),
        ],
    )
    driver = make_driver(SoftwareCamera(D435, [spec]))
    driver.writes = []
    set_control_values = driver.set_control_values

    def record(sensor, values):
        driver.writes += list(values)
        set_control_values(sensor, values)

    monkeypatch.setattr(driver, "set_control_values", record)
    return driver


def test_preset_first_and_auto_modes_last(preset_driver):
    preset_driver.set_control_values(
        STEREO,
        {"enable_auto_exposure": 0, "laser_power": 30, "exposure": 1000, "visual_preset": 3},
    )
    preset_driver.writes.clear()

    restore_json("depth")

    assert preset_driver.writes[0] == "visual_preset"
    assert preset_driver.writes[-1] == "enable_auto_exposure"
    assert set(preset_driver.writes) == {
        "visual_preset",
        "laser_power",
        "exposure",
        "enable_auto_exposure",
    }


@pytest.fixture
def laser_fails(driver, monkeypatch):
    """Laser power and brightness changed on the D435, then every laser_power write fails."""
    driver.set_control_values(STEREO, {"laser_power": 30})
    driver.set_control_values(RGB, {"brightness": 10})
    set_control_values = driver.set_control_values

    def fail_laser(sensor, values):
        if "laser_power" in values:
            raise InvalidValue("Failed to set 'laser_power'")
        set_control_values(sensor, values)

    monkeypatch.setattr(driver, "set_control_values", fail_laser)
    return driver


def test_failed_write_stops_restore(laser_fails):
    result = runner.invoke(app, ["config", "restore"])

    assert result.exit_code == InvalidValue.exit_code, result.output
    assert "laser_power" in result.stderr
    assert laser_fails.get_control_values(RGB, ["brightness"]) == {"brightness": 10.0}


def test_keep_going_reports_failures(laser_fails):
    result = runner.invoke(app, ["--json", "config", "restore", "--keep-going"])

    assert result.exit_code == InvalidValue.exit_code, result.output
    payload = json.loads(result.stdout)
    assert payload["restored"] == [
        {"sensor": RGB, "control": "brightness", "old": 10.0, "new": 0.0}
    ]
    assert payload["failed"] == [
        {"sensor": STEREO, "control": "laser_power", "error": "Failed to set 'laser_power'"}
    ]


def test_keep_going_table_lists_failures(laser_fails):
    result = runner.invoke(app, ["config", "restore", "--keep-going"])

    assert result.exit_code == InvalidValue.exit_code, result.output
    line = next(line for line in result.stdout.splitlines() if "laser_power" in line)
    assert "Failed to set" in line
    assert "brightness" in result.stdout
