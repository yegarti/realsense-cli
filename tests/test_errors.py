import pytest
from typer.testing import CliRunner

from realsense_cli.cli import app
from realsense_cli.driver.realsense import Realsense
from realsense_cli.driver.software import D435
from realsense_cli.errors import (
    DeviceNotFound,
    InvalidProfile,
    InvalidValue,
    RsCliError,
    UnknownControl,
    UnknownSensor,
)

runner = CliRunner()


def assert_error(result, error: type[RsCliError], *expected: str) -> None:
    """A handled error: one line on stderr, nothing on stdout, the error's exit code."""
    assert result.exit_code == error.exit_code, result.output
    assert "Traceback" not in result.output
    assert result.stdout == ""
    lines = result.stderr.strip().splitlines()
    assert len(lines) == 1, lines
    for text in expected:
        assert text in lines[0]


def test_exit_codes_are_distinct():
    errors = [
        RsCliError,
        DeviceNotFound,
        UnknownSensor,
        UnknownControl,
        InvalidProfile,
        InvalidValue,
    ]
    codes = [e.exit_code for e in errors]
    assert len(set(codes)) == len(codes)
    # 2 is click's usage error
    assert 0 not in codes and 2 not in codes


def test_unknown_driver(monkeypatch):
    monkeypatch.setenv("RSCLI_DRIVER", "bogus")
    result = runner.invoke(app, ["list"])
    assert_error(result, RsCliError, "bogus", "mock")


def test_config_get_unknown_control(driver):
    result = runner.invoke(app, ["config", "get", "depth", "bogus"])
    assert_error(result, UnknownControl, "bogus", "exposure", "enable_auto_exposure")


def test_config_set_unknown_control(driver):
    result = runner.invoke(app, ["config", "set", "depth", "bogus=1"])
    assert_error(result, UnknownControl, "bogus", "exposure")


def test_config_restore_unknown_control(driver):
    result = runner.invoke(app, ["config", "restore", "depth", "bogus"])
    assert_error(result, UnknownControl, "bogus", "exposure", "asic_temperature")


@pytest.mark.parametrize(
    "command", [["config", "list"], ["config", "restore"], ["stream", "list"]]
)
def test_unknown_sensor(driver, command):
    result = runner.invoke(app, [*command, "bogus"])
    assert_error(
        result,
        UnknownSensor,
        "bogus",
        "Stereo Module (depth)",
        "RGB Camera (color)",
        "Motion Module (motion)",
    )


def test_unknown_serial(driver):
    result = runner.invoke(app, ["-s", "000", "config", "list", "depth"])
    assert_error(result, DeviceNotFound, "000", D435.serial)


def test_no_device(inject_driver):
    inject_driver(Realsense(devices=[]))
    result = runner.invoke(app, ["config", "list", "depth"])
    assert_error(result, DeviceNotFound, "No devices")


@pytest.mark.parametrize(
    "setting, expected",
    [
        ("exposure", "CONTROL=VALUE"),
        ("exposure=abc", "abc"),
        ("exposure=1e9", "exposure"),
    ],
    ids=["no-equals", "not-a-number", "out-of-range"],
)
def test_config_set_invalid_value(driver, setting, expected):
    result = runner.invoke(app, ["config", "set", "depth", setting])
    assert_error(result, InvalidValue, expected)


@pytest.mark.parametrize(
    "profile, expected",
    [
        ("depth-axb", "depth-axb"),
        ("depth-640x480-30-bogus", "z16"),
        ("bogus", "Depth"),
        ("depth-1x1-30-z16", "rs stream list"),
    ],
    ids=["unparsable", "unknown-format", "unknown-stream", "no-match"],
)
def test_stream_play_invalid_profile(driver, profile, expected):
    result = runner.invoke(app, ["stream", "play", "--sensor", profile])
    assert_error(result, InvalidProfile, expected)


def test_unexpected_error_hides_traceback(driver, monkeypatch):
    def boom(sensor):
        raise RuntimeError("boom")

    monkeypatch.setattr(driver, "list_controls", boom)
    result = runner.invoke(app, ["config", "list", "depth"])
    assert result.exit_code == 1
    assert "boom" in result.stderr
    assert "--verbose" in result.stderr
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_unexpected_error_raises_with_verbose(driver, monkeypatch):
    def boom(sensor):
        raise RuntimeError("boom")

    monkeypatch.setattr(driver, "list_controls", boom)
    result = runner.invoke(app, ["-v", "config", "list", "depth"])
    assert result.exit_code == 1
    assert isinstance(result.exception, RuntimeError)
