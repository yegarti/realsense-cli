import pytest
from typer.testing import CliRunner

from realsense_cli.cli import app
from realsense_cli.driver.mock import MockDriver
from realsense_cli.types import DeviceInfo, Option, Profile, Resolution, resolve_sensor_name

runner = CliRunner()


def test_list(driver):
    result = runner.invoke(app, ["list"])
    device = driver.query_devices()[0]
    assert device.serial in result.stdout
    for sensor in device.sensors:
        assert sensor in result.stdout
    assert result.exit_code == 0


@pytest.mark.parametrize(
    "sensor_alias, sensor_name",
    [("depth", "Stereo Module"), ("color", "RGB Camera")],
    ids=["depth", "color"],
)
def test_config_list(driver, sensor_alias, sensor_name):
    result = runner.invoke(app, ["config", "list", sensor_alias])
    controls = driver.list_controls(sensor_name)
    assert result.exit_code == 0
    stdout = result.stdout
    for option in controls:
        assert option.name in stdout
        assert option.description in stdout
        assert str(option.vtype(option.min_value)) in stdout
        assert str(option.vtype(option.max_value)) in stdout
        assert str(option.vtype(option.step)) in stdout


@pytest.mark.parametrize(
    "sensor_alias, sensor_name, controls",
    [
        ("depth", "Stereo Module", ["exposure"]),
        ("color", "RGB Camera", ["brightness"]),
        ("depth", "Stereo Module", ["exposure", "enable_auto_exposure"]),
    ],
)
def test_config_get(driver, sensor_alias, sensor_name, controls):
    result = runner.invoke(app, ["config", "get", sensor_alias, *controls])
    opts = {}
    for option in driver.list_controls(sensor_name):
        for ctrl in controls:
            if ctrl == option.name:
                opts[ctrl] = option

    assert result.exit_code == 0
    stdout = result.stdout
    for control in controls:
        assert opts[control].name in stdout
        assert str(opts[control].default_value) in stdout


@pytest.mark.parametrize(
    "sensor_alias, sensor_name, controls, vals",
    [
        ("depth", "Stereo Module", ["exposure"], ["22"]),
        ("color", "RGB Camera", ["brightness"], ["34"]),
        ("depth", "Stereo Module", ["exposure", "enable_auto_exposure"], ["53", "1"]),
    ],
)
def test_config_set(driver, sensor_alias, sensor_name, controls, vals):
    setstrs = [f"{c}={v}" for c, v in zip(controls, vals)]
    result = runner.invoke(app, ["config", "set", sensor_alias, *setstrs])
    opts = {}
    for option in driver.list_controls(sensor_name):
        for ctrl in controls:
            if ctrl == option.name:
                opts[ctrl] = option

    assert result.exit_code == 0
    stdout = result.stdout
    for control in controls:
        assert opts[control].name in stdout
        assert str(opts[control].default_value) in stdout


def test_stream_play(driver):
    profiles = [Profile("Depth", Resolution(640, 480), 30, "z16")]
    driver.play(profiles)
    frameset = driver.wait_for_frameset()
    assert frameset is not None
    assert "Depth" in frameset
    assert frameset["Depth"].index == 0
    second = driver.wait_for_frameset()
    assert second["Depth"].index == 1


@pytest.mark.parametrize(
    "sensor_alias, sensor_name",
    [("depth", "Stereo Module"), ("color", "RGB Camera")],
)
def test_stream_list(driver, sensor_alias, sensor_name):
    result = runner.invoke(app, ["stream", "list", sensor_alias])
    profiles = driver.list_streams(sensor_name)
    assert result.exit_code == 0
    stdout = result.stdout
    for profile in profiles:
        matches = 0
        for line in stdout.split("\n"):
            if (
                profile.stream in line
                and profile.format in line
                and str(profile.resolution) in line
            ):
                matches += 1
        assert matches == 1


# --- Robustness tests: new/unknown sensors and streams ---

@pytest.fixture
def future_driver():
    config = {
        "devices": [
            DeviceInfo(
                name="Intel RealSense D999",
                serial="9999999999",
                fw="9.0.0.0",
                connection="3.2",
                sensors=["Future Sensor"],
            )
        ],
        "sensors": {
            "Future Sensor": {
                "options": [Option("gain", "Gain", 0, 100, 1, 50, int)],
                "profiles": [Profile("Future Stream", Resolution(1280, 720), 60, "rgb8")],
            }
        },
    }
    return MockDriver(config)


def test_list_devices_unknown_sensor(future_driver):
    devices = future_driver.query_devices()
    assert devices[0].sensors == ["Future Sensor"]
    assert devices[0].name == "Intel RealSense D999"


def test_list_streams_unknown_sensor(future_driver):
    profiles = future_driver.list_streams("Future Sensor")
    assert len(profiles) == 1
    assert profiles[0].stream == "Future Stream"


def test_list_controls_unknown_sensor(future_driver):
    controls = future_driver.list_controls("Future Sensor")
    assert len(controls) == 1
    assert controls[0].name == "gain"


def test_rs_list_future_device(future_driver, monkeypatch):
    monkeypatch.setattr("realsense_cli.driver._driver", future_driver)
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "D999" in result.output
    assert "Future Sensor" in result.output


def test_stream_list_future_sensor(future_driver, monkeypatch):
    monkeypatch.setattr("realsense_cli.driver._driver", future_driver)
    result = runner.invoke(app, ["stream", "list", "Future Sensor"])
    assert result.exit_code == 0
    assert "Future Stream" in result.output


def test_config_list_future_sensor(future_driver, monkeypatch):
    monkeypatch.setattr("realsense_cli.driver._driver", future_driver)
    result = runner.invoke(app, ["config", "list", "Future Sensor"])
    assert result.exit_code == 0
    assert "gain" in result.output


def test_config_list_full_sensor_name(driver, monkeypatch):
    """Full sensor name (e.g. 'Stereo Module') accepted in addition to alias 'depth'."""
    result = runner.invoke(app, ["config", "list", "Stereo Module"])
    assert result.exit_code == 0
    assert "exposure" in result.output


def test_stream_list_full_sensor_name(driver, monkeypatch):
    """Full sensor name (e.g. 'RGB Camera') accepted in addition to alias 'color'."""
    result = runner.invoke(app, ["stream", "list", "RGB Camera"])
    assert result.exit_code == 0
    assert "Color" in result.output
