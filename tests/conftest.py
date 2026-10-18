import random

import pytest

from realsense_cli.driver import reset_driver
from realsense_cli.driver.realsense import Realsense
from realsense_cli.driver.software import SoftwareCamera, d435
from realsense_cli.types import Frame, FrameSet, Profile


@pytest.fixture(autouse=True)
def _reset_driver():
    """Ensure each test gets a fresh driver instance."""
    reset_driver()
    yield
    reset_driver()


@pytest.fixture
def camera() -> SoftwareCamera:
    return d435()


@pytest.fixture
def driver(camera, monkeypatch):
    """Real driver over a simulated D435, also served to CLI commands by `get_driver()`."""
    drv = Realsense(devices=[camera.device])
    monkeypatch.setattr("realsense_cli.driver._driver", drv)
    yield drv


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
