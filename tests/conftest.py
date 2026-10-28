import os
import random
import sqlite3
import time
from collections.abc import Collection
from contextlib import closing
from dataclasses import replace
from pathlib import Path

import pyrealsense2 as rs
import pytest
from loguru import logger

from realsense_cli.driver.realsense import Realsense
from realsense_cli.driver.software import (
    D435,
    D435_SENSORS,
    SoftwareCamera,
    d435,
    software_driver,
)
from realsense_cli.types import Frame, FrameSet, Profile


@pytest.fixture(autouse=True)
def _wide_console(monkeypatch):
    """Rich falls back to 80 columns without a terminal, which truncates the tables."""
    monkeypatch.setenv("COLUMNS", "120")


def pytest_configure(config):
    """
    Rich colors CliRunner's output, which breaks text asserts, when the shell forces color or
    pytest runs in a terminal: `-s` leaves the real stdout and stderr in place when
    `realsense_cli.console` creates its consoles, and Rich picks colors then. This runs before
    the test modules import the CLI; nothing conftest imports may pull in that module.
    TTY_COMPATIBLE=0 makes Rich treat every console as a non-terminal, overriding FORCE_COLOR.
    """
    os.environ["TTY_COMPATIBLE"] = "0"


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
def tty(monkeypatch):
    """Commands see a terminal they can prompt on; CliRunner's stdin isn't one."""
    monkeypatch.setattr("realsense_cli.session._stdin_is_tty", lambda: True)


@pytest.fixture
def make_driver(inject_driver):
    """Build the real driver over a software camera, also served to CLI commands."""

    def make(camera: SoftwareCamera) -> Realsense:
        return inject_driver(software_driver(camera))

    return make


class _UnreadableOptions:
    """
    An `rs.sensor` that lists OPTIONS but can't read them, as a real camera does with its
    temperatures while idle: `supports()` is false and `get_option()` raises
    """

    def __init__(self, sensor: rs.sensor, options: set[str]):
        self._sensor = sensor
        self._options = options

    def supports(self, option) -> bool:
        return option.name not in self._options and self._sensor.supports(option)

    def get_option(self, option: rs.option) -> float:
        if option.name in self._options:
            raise RuntimeError(f"object doesn't support option {option}")
        return self._sensor.get_option(option)

    def __getattr__(self, name: str):
        return getattr(self._sensor, name)


class _DeviceWithUnreadableOptions:
    """An `rs.device` whose sensors can't read OPTIONS, which they still list"""

    def __init__(self, device: rs.device, options: set[str]):
        self._device = device
        self.sensors = [_UnreadableOptions(s, options) for s in device.sensors]

    def __getattr__(self, name: str):
        return getattr(self._device, name)


@pytest.fixture
def idle_driver(camera, inject_driver) -> Realsense:
    """
    The driver over the simulated camera, which lists `asic_temperature` but can't read it, as
    a real camera does while idle
    """
    device = _DeviceWithUnreadableOptions(camera.device, {"asic_temperature"})
    return inject_driver(Realsense(devices=[device]))


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


# The streams `recording` holds and the frames pushed to each: color is pushed fewer
RECORDED: dict[str, int] = {"Depth": 5, "Color": 3, "Gyro": 3, "Accel": 3}


def record(path: Path, profiles: list[str], pushes: list[Collection[str]]) -> Path:
    """
    Record the simulated D435 streaming PROFILES to PATH with `rs.recorder`, pushing one frame
    to the streams each of PUSHES names
    """
    camera = d435()
    recorder = rs.recorder(str(path), camera.device)
    driver = Realsense(devices=[camera.device])
    driver.play([Profile.from_string(p) for p in profiles], pipeline=False)
    for streams in pushes:
        camera.push_frames(streams)
        # message times are wall-clock: spread them out so the recording has a duration
        time.sleep(0.01)
    driver.stop()
    # releasing the recorder flushes its queue to the file
    del recorder
    return path


@pytest.fixture(scope="session")
def recording(tmp_path_factory) -> Path:
    """A recording of depth, color, gyro and accel, with `RECORDED` frames per stream"""
    pushes = [[s for s, n in RECORDED.items() if n > i] for i in range(max(RECORDED.values()))]
    return record(
        tmp_path_factory.mktemp("recording") / "run.db3",
        ["depth-640x480-30-z16", "color-640x480-30-rgb8", "gyro", "accel"],
        pushes,
    )


@pytest.fixture
def rosbag2(tmp_path) -> Path:
    """A stock rosbag2 `.db3` with one message, which no RealSense device recorded"""
    path = tmp_path / "chatter.db3"
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript(
            """
            CREATE TABLE topics (id INTEGER PRIMARY KEY, name TEXT NOT NULL,
                type TEXT NOT NULL, serialization_format TEXT NOT NULL,
                offered_qos_profiles TEXT NOT NULL);
            CREATE TABLE messages (id INTEGER PRIMARY KEY, topic_id INTEGER NOT NULL,
                timestamp INTEGER NOT NULL, data BLOB NOT NULL);
            INSERT INTO topics VALUES (1, '/chatter', 'std_msgs/msg/String', 'cdr', '');
            INSERT INTO messages VALUES (1, 1, 1000000000, x'00');
            """
        )
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
