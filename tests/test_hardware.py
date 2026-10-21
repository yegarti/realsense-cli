"""
Smoke tests against a connected camera, for what the software device cannot cover.
Run with `just test -m hardware`.
"""

import json

import pytest
from typer.testing import CliRunner

from realsense_cli.cli import app
from realsense_cli.driver.realsense import Realsense

pytestmark = pytest.mark.hardware

runner = CliRunner()


@pytest.fixture
def camera_driver():
    driver = Realsense()
    if not driver.query_devices():
        pytest.skip("no RealSense camera connected")
    return driver


def test_pipeline_streams_defaults(camera_driver):
    camera_driver.play(pipeline=True)
    try:
        assert camera_driver.wait_for_frameset(timeout=5) is not None
    finally:
        camera_driver.stop()


def test_reset_waits_for_reconnect(camera_driver):
    assert camera_driver.reset(timeout=45)


def test_info_all_profiles(camera_driver):
    """
    A real device keeps extrinsics per stream, which the software device only imitates, and
    has profiles without intrinsics (the infrared Y16 profiles), which it can't
    """
    result = runner.invoke(app, ["--json", "info", "--all-profiles"])
    assert result.exit_code == 0, result.output
    info = json.loads(result.stdout)
    assert info["device"]["serial_number"]
    assert info["intrinsics"]
    assert any(group["fx"] for group in info["intrinsics"])
    streams = {group["stream"] for group in info["intrinsics"]}
    pairs = {(ext["from"], ext["to"]) for ext in info["extrinsics"]}
    assert pairs == {(a, b) for a in streams for b in streams if a != b}
