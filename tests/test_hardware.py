"""
Smoke tests against a connected camera, for what the software device cannot cover.
Run with `just test -m hardware`.
"""

import pytest

from realsense_cli.driver.realsense import Realsense

pytestmark = pytest.mark.hardware


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
