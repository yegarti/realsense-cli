import os
import random

import pytest

from realsense_cli.driver import get_driver, reset_driver
from realsense_cli.types import Profile, FrameSet, Frame


@pytest.fixture(autouse=True)
def _reset_driver():
    """Ensure each test gets a fresh driver instance."""
    reset_driver()
    yield
    reset_driver()


@pytest.fixture(autouse=True)
def set_mock_envar():
    os.environ["RSCLI_DRIVER"] = "mock"


@pytest.fixture
def mock_context(monkeypatch):
    import pyrealsense2 as rs
    from tests.utils import build_software_device, MOCK_DEVICE, MOCK_SENSORS

    ctx = rs.context()
    dev = build_software_device(MOCK_DEVICE, MOCK_SENSORS["profiles"], MOCK_SENSORS["options"])
    dev.add_to(ctx)
    monkeypatch.setattr(rs, "context", lambda: ctx)
    yield


@pytest.fixture
def driver():
    yield get_driver()


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
