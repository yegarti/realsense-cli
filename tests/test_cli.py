import os

from typer.testing import CliRunner

from realsense_cli.cli import app

import pytest

from realsense_cli.types import CliSensor

runner = CliRunner()


@pytest.fixture(autouse=True)
def set_mock_envar():
    os.environ["RSCLI_DRIVER"] = "mock"


def test_list(driver):
    result = runner.invoke(app, ["list"])
    device = driver.query_devices()[0]
    assert device.serial in result.stdout
    for sensor in device.sensors:
        assert sensor in result.stdout
    assert result.exit_code == 0


@pytest.mark.parametrize("sensor", (CliSensor.DEPTH, CliSensor.COLOR), ids=["depth", "color"])
def test_config_list(driver, sensor):
    result = runner.invoke(app, ["config", "list", sensor.value])
    controls = driver.list_controls(sensor.rs_enum)
    assert result.exit_code == 0
    stdout = result.stdout
    for option in controls:
        assert option.name in stdout
        assert option.description in stdout
        assert str(option.min_value) in stdout
        assert str(option.max_value) in stdout
        assert str(option.step) in stdout


@pytest.mark.parametrize(
    "sensor, controls",
    [
        (CliSensor.DEPTH, ["exposure"]),
        (CliSensor.COLOR, ["brightness"]),
        (CliSensor.DEPTH, ["exposure", "enable_auto_exposure"]),
    ],
)
def test_config_get(driver, sensor, controls):
    result = runner.invoke(app, ["config", "get", sensor.value, *controls])
    opts = {}
    for option in driver.list_controls(sensor.rs_enum):
        for ctrl in controls:
            if ctrl == option.name:
                opts[ctrl] = option

    assert result.exit_code == 0
    stdout = result.stdout
    for control in controls:
        assert opts[control].name in stdout
        assert str(opts[control].default_value) in stdout


@pytest.mark.parametrize(
    "sensor, controls, vals",
    [
        (CliSensor.DEPTH, ["exposure"], ["22"]),
        (CliSensor.COLOR, ["brightness"], ["34"]),
        (CliSensor.DEPTH, ["exposure", "enable_auto_exposure"], ["53", "1"]),
    ],
)
def test_config_set(driver, sensor, controls, vals):
    setstrs = [f"{c}={v}" for c, v in zip(controls, vals)]
    result = runner.invoke(app, ["config", "set", sensor.value, *setstrs])
    opts = {}
    for option in driver.list_controls(sensor.rs_enum):
        for ctrl in controls:
            if ctrl == option.name:
                opts[ctrl] = option

    assert result.exit_code == 0
    stdout = result.stdout
    for control in controls:
        assert opts[control].name in stdout
        # default_value used in mock driver as current value
        assert str(opts[control].default_value) in stdout


@pytest.mark.parametrize("sensor", (CliSensor.DEPTH, CliSensor.COLOR))
def test_stream_list(driver, sensor):
    result = runner.invoke(app, ["stream", "list", sensor.value])
    profiles = driver.list_streams(sensor.rs_enum)
    assert result.exit_code == 0
    stdout = result.stdout
    for profile in profiles:
        matches = 0
        for line in stdout.split("\n"):
            if (
                profile.stream.value in line
                and f" {profile.fps} " in line
                and profile.format in line
                and str(profile.resolution) in line
            ):
                matches += 1
        assert matches == 1
