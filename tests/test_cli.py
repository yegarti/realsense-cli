import pytest
from typer.testing import CliRunner

from realsense_cli.cli import app
from realsense_cli.driver import get_driver
from realsense_cli.driver.realsense import Realsense
from realsense_cli.driver.software import D435, D435_SENSORS, SensorSpec, SoftwareCamera
from realsense_cli.types import DeviceInfo, Option, Profile, Resolution

runner = CliRunner()


def _spec(sensor: str) -> SensorSpec:
    return next(s for s in D435_SENSORS if s.name == sensor)


def test_list(driver):
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert D435.serial in result.stdout
    for sensor in D435.sensors:
        assert sensor in result.stdout


@pytest.mark.parametrize(
    "sensor_alias, sensor_name",
    [("depth", "Stereo Module"), ("color", "RGB Camera")],
    ids=["depth", "color"],
)
def test_config_list(driver, sensor_alias, sensor_name):
    result = runner.invoke(app, ["config", "list", sensor_alias])
    assert result.exit_code == 0
    stdout = result.stdout
    for option in _spec(sensor_name).options:
        assert option.name in stdout
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
    defaults = {opt.name: opt.default_value for opt in _spec(sensor_name).options}

    assert result.exit_code == 0
    for control in controls:
        assert control in result.stdout
        assert str(defaults[control]) in result.stdout


@pytest.mark.parametrize(
    "sensor_alias, sensor_name, controls, vals",
    [
        ("depth", "Stereo Module", ["exposure"], ["22"]),
        ("color", "RGB Camera", ["brightness"], ["34"]),
        ("depth", "Stereo Module", ["exposure", "enable_auto_exposure"], ["53", "1"]),
    ],
)
def test_config_set(driver, sensor_alias, sensor_name, controls, vals):
    setstrs = [f"{c}={v}" for c, v in zip(controls, vals, strict=True)]
    result = runner.invoke(app, ["config", "set", sensor_alias, *setstrs])

    assert result.exit_code == 0
    expected = {c: float(v) for c, v in zip(controls, vals, strict=True)}
    for control, value in expected.items():
        assert control in result.stdout
        assert str(value) in result.stdout
    assert driver.get_control_values(sensor_name, controls) == expected


def test_stream_play(driver, camera):
    profiles = [Profile("Depth", Resolution(640, 480), 30, "z16")]
    driver.play(profiles, pipeline=False)
    try:
        camera.push_frames()
        frameset = driver.wait_for_frameset()
        assert frameset is not None
        assert frameset["Depth"].index == 0
        camera.push_frames()
        second = driver.wait_for_frameset()
        assert second is not None
        assert second["Depth"].index == 1
    finally:
        driver.stop()


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
def future_driver(monkeypatch):
    """A device whose sensor and stream names the CLI has no aliases or mappings for."""
    info = DeviceInfo(
        name="Intel RealSense D999",
        serial="9999999999",
        fw="9.0.0.0",
        connection="3.2",
        sensors=["Future Sensor"],
    )
    camera = SoftwareCamera(
        info,
        [
            SensorSpec(
                name="Future Sensor",
                profiles=[Profile("Confidence", Resolution(1280, 720), 60, "y8", 0)],
                options=[Option("gain", "", 0.0, 100.0, 1.0, 50.0, int)],
            )
        ],
    )
    drv = Realsense(devices=[camera.device])
    monkeypatch.setattr("realsense_cli.driver._driver", drv)
    return drv


def test_list_devices_unknown_sensor(future_driver):
    devices = future_driver.query_devices()
    assert devices[0].sensors == ["Future Sensor"]
    assert devices[0].name == "Intel RealSense D999"


def test_list_streams_unknown_sensor(future_driver):
    profiles = future_driver.list_streams("Future Sensor")
    assert len(profiles) == 1
    assert profiles[0].stream == "Confidence"


def test_list_controls_unknown_sensor(future_driver):
    controls = future_driver.list_controls("Future Sensor")
    assert "gain" in [c.name for c in controls]


def test_rs_list_future_device(future_driver):
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "D999" in result.output
    assert "Future Sensor" in result.output


def test_stream_list_future_sensor(future_driver):
    result = runner.invoke(app, ["stream", "list", "Future Sensor"])
    assert result.exit_code == 0
    assert "Confidence" in result.output


def test_config_list_future_sensor(future_driver):
    result = runner.invoke(app, ["config", "list", "Future Sensor"])
    assert result.exit_code == 0
    assert "gain" in result.output


def test_config_list_full_sensor_name(driver):
    """Full sensor name (e.g. 'Stereo Module') accepted in addition to alias 'depth'."""
    result = runner.invoke(app, ["config", "list", "Stereo Module"])
    assert result.exit_code == 0
    assert "exposure" in result.output


def test_stream_list_full_sensor_name(driver):
    """Full sensor name (e.g. 'RGB Camera') accepted in addition to alias 'color'."""
    result = runner.invoke(app, ["stream", "list", "RGB Camera"])
    assert result.exit_code == 0
    assert "Color" in result.output


def test_mock_driver_env_var(monkeypatch):
    monkeypatch.setenv("RSCLI_DRIVER", "mock")
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert D435.serial in result.stdout


def test_mock_driver_streams_on_its_own(monkeypatch):
    monkeypatch.setenv("RSCLI_DRIVER", "mock")
    driver = get_driver()
    driver.play([Profile("Depth", Resolution(640, 480), 30, "z16")])
    try:
        first = driver.wait_for_frameset()
        second = driver.wait_for_frameset()
        assert first is not None and second is not None
        assert second["Depth"].index > first["Depth"].index
    finally:
        driver.stop()


def test_unknown_driver_env_var(monkeypatch):
    monkeypatch.setenv("RSCLI_DRIVER", "bogus")
    with pytest.raises(ValueError, match="bogus"):
        get_driver()
