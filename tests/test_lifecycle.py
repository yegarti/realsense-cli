import subprocess
import sys

import pyrealsense2 as rs
import pytest
from typer.testing import CliRunner

from realsense_cli.cli import app

runner = CliRunner()


@pytest.fixture
def no_context(monkeypatch):
    """Fail the test if anything creates an `rs.context`."""

    def fail(*args, **kwargs):
        raise AssertionError("rs.context created")

    monkeypatch.setattr(rs, "context", fail)


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


def test_multiple_devices_warns(two_cameras):
    result = runner.invoke(app, ["config", "list", "depth"])
    assert result.exit_code == 0, result.output
    assert "Multiple devices" in result.stderr


def test_multiple_devices_with_serial(two_cameras):
    result = runner.invoke(app, ["-s", "987654321", "config", "list", "depth"])
    assert result.exit_code == 0, result.output
    assert "Multiple devices" not in result.stderr
    assert two_cameras.active_device == "987654321"
