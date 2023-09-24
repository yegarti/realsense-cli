from realsense_cli.types import Profile, Stream, Resolution
from realsense_cli.utils import group_profiles


def test_group_profiles():
    profiles = [
        Profile(Stream.DEPTH, Resolution(640, 480), 15, "z16"),
        Profile(Stream.DEPTH, Resolution(640, 480), 30, "z16"),
        Profile(Stream.INFRARED, Resolution(1280, 720), 5, "z16"),
        Profile(Stream.DEPTH, Resolution(640, 480), 5, "y16"),
    ]
    result = group_profiles(profiles)
    assert result == {
        Profile(Stream.DEPTH, Resolution(640, 480), 0, "z16"): [15, 30],
        Profile(Stream.INFRARED, Resolution(1280, 720), 0, "z16"): [5],
        Profile(Stream.DEPTH, Resolution(640, 480), 0, "y16"): [5],
    }
