import subprocess
import sys
from dataclasses import replace

import pyrealsense2 as rs
import pytest
from rosbags.rosbag1 import Writer
from rosbags.typesys import Stores, get_typestore
from typer.testing import CliRunner

from realsense_cli.cli import app
from realsense_cli.driver.realsense import Realsense
from realsense_cli.driver.software import D435, D435_SENSORS, SoftwareCamera, d435

runner = CliRunner()


@pytest.fixture
def no_context(monkeypatch):
    """Fail the test if anything creates an `rs.context`."""

    def fail(*args, **kwargs):
        raise AssertionError("rs.context created")

    monkeypatch.setattr(rs, "context", fail)


@pytest.fixture
def bag(tmp_path):
    typestore = get_typestore(Stores.ROS1_NOETIC)
    string = typestore.types["std_msgs/msg/String"]
    path = tmp_path / "test.bag"
    with Writer(path) as writer:
        conn = writer.add_connection("/device_0/info", string.__msgtype__, typestore=typestore)
        for t in (1, 3):
            data = typestore.serialize_ros1(string(data="x"), string.__msgtype__)
            writer.write(conn, t * 1_000_000_000, data)
    return path


@pytest.mark.parametrize(
    "args",
    [
        ["--help"],
        ["config", "--help"],
        ["config", "list", "--help"],
        ["stream", "play", "-h"],
        ["-s", "123", "config", "get", "--help"],
    ],
)
def test_help_creates_no_context(no_context, args):
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    assert "Usage" in result.output


def test_bag_info_creates_no_context(no_context, bag):
    result = runner.invoke(app, ["bag", "info", str(bag)])
    assert result.exit_code == 0, result.output
    assert "/device_0/info" in result.stdout


def test_cli_import_skips_pyrealsense2():
    code = "import sys, realsense_cli.cli; assert 'pyrealsense2' not in sys.modules"
    subprocess.run([sys.executable, "-c", code], check=True)


@pytest.fixture
def two_cameras(inject_driver):
    second = SoftwareCamera(replace(D435, serial="987654321"), D435_SENSORS)
    return inject_driver(Realsense(devices=[d435().device, second.device]))


def test_multiple_devices_warns(two_cameras):
    result = runner.invoke(app, ["config", "list", "depth"])
    assert result.exit_code == 0, result.output
    assert "Multiple devices" in result.stderr


def test_multiple_devices_with_serial(two_cameras):
    result = runner.invoke(app, ["-s", "987654321", "config", "list", "depth"])
    assert result.exit_code == 0, result.output
    assert "Multiple devices" not in result.stderr
    assert two_cameras.active_device == "987654321"
