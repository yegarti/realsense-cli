import random

import pytest

from realsense_cli.driver.realsense import Realsense
from realsense_cli.driver.software import SoftwareCamera, d435
from realsense_cli.types import Frame, FrameSet, Profile


@pytest.fixture(autouse=True)
def _wide_console(monkeypatch):
    """Rich falls back to 80 columns without a terminal, which truncates the tables."""
    monkeypatch.setenv("COLUMNS", "120")


@pytest.fixture
def camera() -> SoftwareCamera:
    return d435()


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
def driver(camera, make_driver) -> Realsense:
    return make_driver(camera)


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
