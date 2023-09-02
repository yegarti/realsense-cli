import os
import random

import pytest

from realsense_cli.driver import MockDriver
from realsense_cli.types import Profile, FrameSet, Frame


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
