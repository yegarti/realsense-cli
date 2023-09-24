import random

import pyrealsense2 as rs
import pytest

from realsense_cli.driver import MockDriver
from realsense_cli.types import Profile, FrameSet, Frame
from tests.utils import build_software_device, MOCK_DEVICE, MOCK_SENSORS


@pytest.fixture
def mock_context(monkeypatch):
    ctx = rs.context()
    dev = build_software_device(MOCK_DEVICE, MOCK_SENSORS["profiles"], MOCK_SENSORS["options"])
    dev.add_to(ctx)
    monkeypatch.setattr(rs, "context", lambda: ctx)
    yield


@pytest.fixture
def driver():
    yield MockDriver()


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
            )
            frameset[profile.stream] = frame
        result.append(frameset)

    return result
