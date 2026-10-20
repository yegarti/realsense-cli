import json

import pytest
from typer.testing import CliRunner

from realsense_cli.cli import app
from realsense_cli.driver.realsense import Realsense
from realsense_cli.driver.software import D435, d435_sensor
from realsense_cli.errors import InvalidValue, UnknownSensor

runner = CliRunner()

STEREO = d435_sensor("Stereo Module")


def invoke_json(*args: str) -> dict:
    result = runner.invoke(app, ["--json", *args])
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def json_error(result, exit_code: int) -> dict:
    """A JSON error: nothing on stdout, one JSON object on stderr, the matching exit code."""
    assert result.exit_code == exit_code, result.output
    assert result.stdout == ""
    error = json.loads(result.stderr)["error"]
    assert error["exit_code"] == exit_code
    return error


def test_list(driver):
    assert invoke_json("list") == {
        "devices": [
            {
                "name": D435.name,
                "serial": D435.serial,
                "fw": D435.fw,
                "connection": D435.connection,
                "sensors": D435.sensors,
            }
        ]
    }


def test_list_no_device(inject_driver):
    inject_driver(Realsense(devices=[]))
    assert invoke_json("list") == {"devices": []}


def test_config_list(driver):
    result = invoke_json("config", "list", "depth")
    assert result["sensor"] == "Stereo Module"
    controls = {c["name"]: c for c in result["controls"]}
    assert controls["exposure"] == {
        "name": "exposure",
        "description": controls["exposure"]["description"],
        "min_value": 1.0,
        "max_value": 200000.0,
        "step": 1.0,
        "default_value": 8500.0,
        "vtype": "int",
        "read_only": False,
    }
    assert controls["depth_units"]["vtype"] == "float"
    assert controls["asic_temperature"]["read_only"] is True


def test_config_get(driver):
    result = invoke_json("config", "get", "depth", "exposure", "laser_power")
    assert result == {
        "sensor": "Stereo Module",
        "values": {"exposure": 8500.0, "laser_power": 150.0},
    }


def test_config_get_all(driver):
    result = invoke_json("config", "get", "depth", "--all")
    for option in STEREO.options:
        assert result["values"][option.name] == pytest.approx(option.default_value)


def test_config_set_reads_back(driver):
    result = invoke_json("config", "set", "depth", "exposure=1000")
    assert result == {"sensor": "Stereo Module", "values": {"exposure": 1000.0}}
    assert driver.get_control_values("Stereo Module", ["exposure"]) == {"exposure": 1000.0}


def test_stream_list(driver):
    result = invoke_json("stream", "list", "depth")
    assert {
        "sensor": "Stereo Module",
        "stream": "Depth",
        "width": 640,
        "height": 480,
        "fps": 30,
        "format": "Z16",
        "index": 0,
    } in result["profiles"]
    assert len(result["profiles"]) == len(STEREO.profiles)


def test_stream_list_all_sensors(driver):
    result = invoke_json("stream", "list")
    sensors = {p["sensor"] for p in result["profiles"]}
    assert sensors == set(D435.sensors)


def test_bag_info(bag):
    result = invoke_json("bag", "info", str(bag))
    assert result == {
        "path": str(bag.absolute()),
        "duration": pytest.approx(2.0),
        "topics": [{"name": "/device_0/info", "messages": 2, "type": "std_msgs/msg/String"}],
    }


def test_reset(driver, monkeypatch):
    calls = []
    monkeypatch.setattr(driver, "reset", lambda timeout=None: calls.append(True))
    assert invoke_json("reset") == {"reset": D435.serial}
    assert calls == [True]


def test_output_is_not_wrapped(driver, monkeypatch):
    """Rich wraps printed text at the console width, which would break long JSON strings."""
    monkeypatch.setenv("COLUMNS", "20")
    result = invoke_json("config", "list", "depth")
    assert max(len(c["description"]) for c in result["controls"]) > 20


def test_rs_cli_error(driver):
    result = runner.invoke(app, ["--json", "config", "list", "bogus"])
    error = json_error(result, UnknownSensor.exit_code)
    assert error["type"] == "UnknownSensor"
    assert "bogus" in error["message"]


def test_read_only_error(driver):
    result = runner.invoke(app, ["--json", "config", "set", "depth", "asic_temperature=1"])
    error = json_error(result, InvalidValue.exit_code)
    assert error["type"] == "InvalidValue"


@pytest.mark.parametrize(
    "args",
    [
        ["config", "get", "depth"],
        ["config", "list"],
        ["stream", "play"],
    ],
)
def test_usage_error(driver, args):
    result = runner.invoke(app, ["--json", *args])
    error = json_error(result, 2)
    assert error["type"] == "UsageError"
    assert error["message"]


def test_stream_play_rejected_before_streaming(driver):
    result = runner.invoke(app, ["--json", "stream", "play", "depth"])
    error = json_error(result, 2)
    assert "--json" in error["message"]


def test_unexpected_error(driver, monkeypatch):
    def boom():
        raise RuntimeError("usb went away")

    monkeypatch.setattr(driver, "query_devices", boom)
    result = runner.invoke(app, ["--json", "list"])
    error = json_error(result, 1)
    assert error == {"type": "RuntimeError", "message": "usb went away", "exit_code": 1}


def test_group_without_command_shows_help(driver):
    result = runner.invoke(app, ["--json", "config"])
    assert result.exit_code == 2
    assert "Usage" in result.stdout
    assert '"error"' not in result.stderr


def test_non_finite_floats_are_null(driver, monkeypatch):
    monkeypatch.setattr(driver, "get_control_values", lambda s, c: {"exposure": float("inf")})
    result = invoke_json("config", "get", "depth", "exposure")
    assert result["values"] == {"exposure": None}


def test_multiple_devices_error_is_last_stderr_line(two_cameras):
    result = runner.invoke(app, ["--json", "config", "list", "bogus"])
    assert result.exit_code == UnknownSensor.exit_code
    assert "Multiple devices" in result.stderr
    error = json.loads(result.stderr.strip().splitlines()[-1])["error"]
    assert error["type"] == "UnknownSensor"
