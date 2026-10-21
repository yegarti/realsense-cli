import random
from dataclasses import replace

import pytest
from loguru import logger
from rosbags.rosbag1 import Writer
from rosbags.typesys import Stores, get_typestore

from realsense_cli.driver.realsense import Realsense
from realsense_cli.driver.software import D435, D435_SENSORS, SoftwareCamera, d435
from realsense_cli.types import Frame, FrameSet, Profile


@pytest.fixture(autouse=True)
def _wide_console(monkeypatch):
    """Rich falls back to 80 columns without a terminal, which truncates the tables."""
    monkeypatch.setenv("COLUMNS", "120")


@pytest.fixture(autouse=True)
def _drop_log_handlers():
    """`-v` adds a handler on CliRunner's stderr, which is closed once the test ends."""
    yield
    logger.remove()


@pytest.fixture
def camera(request) -> SoftwareCamera:
    """
    The simulated D435, or the camera a test builds with
    `@pytest.mark.parametrize("camera", [factory], indirect=True)`
    """
    return getattr(request, "param", d435)()


@pytest.fixture
def inject_driver(monkeypatch):
    """Serve DRIVER to CLI commands in place of the one `create_driver()` builds."""

    def inject(driver: Realsense) -> Realsense:
        monkeypatch.setattr("realsense_cli.session.create_driver", lambda: driver)
        return driver

    return inject


@pytest.fixture
def make_driver(inject_driver):
    """Build the real driver over a software camera, also served to CLI commands."""

    def make(camera: SoftwareCamera) -> Realsense:
        return inject_driver(Realsense(devices=[camera.device]))

    return make


@pytest.fixture
def two_cameras(inject_driver):
    second = SoftwareCamera(replace(D435, serial="987654321"), D435_SENSORS)
    return inject_driver(Realsense(devices=[d435().device, second.device]))


@pytest.fixture
def driver(camera, make_driver) -> Realsense:
    return make_driver(camera)


class Feed:
    """Streams the software camera pushes a frame to; None for every active stream."""

    streams: list[str] | None = None


@pytest.fixture
def feed(driver, camera, monkeypatch) -> Feed:
    """
    Push a frame to the fed streams each time a command waits for one and none is queued: the
    software camera produces no frames on its own. Pushing while frames are queued would fill
    the queue, which then drops the frames of every sensor but the first to deliver
    """
    fed = Feed()
    wait = driver.wait_for_frameset

    def push_then_wait(timeout: float = 3.0, **kwargs):
        frameset = wait(0, **kwargs)
        if frameset is None:
            camera.push_frames(fed.streams)
            frameset = wait(timeout, **kwargs)
        return frameset

    monkeypatch.setattr(driver, "wait_for_frameset", push_then_wait)
    return fed


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


@pytest.fixture
def frames(request):
    print(request.param)
    amount, profiles = request.param
    return generate_frames(amount, profiles)


def generate_frames(amount: int, profiles: list[Profile]) -> list[FrameSet]:
    result = []
    for i in range(amount):
        frameset: FrameSet = {}
        for profile in profiles:
            delta = 1000 / profile.fps
            noise = random.normalvariate(0, 1e-2)
            ts = i * delta + noise
            frame = Frame(
                profile=profile,
                index=i,
                timestamp=round(ts, 4),
                metadata={},
            )
            frameset[profile.stream] = frame
        result.append(frameset)

    return result
