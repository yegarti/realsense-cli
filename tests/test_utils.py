import pytest

from realsense_cli.types import Profile, Resolution
from realsense_cli.utils import group_profiles, find_origin_sensor


def test_group_profiles():
    profiles = [
        Profile("Depth", Resolution(640, 480), 15, "z16"),
        Profile("Depth", Resolution(640, 480), 30, "z16"),
        Profile("Infrared 1", Resolution(1280, 720), 5, "z16"),
        Profile("Depth", Resolution(640, 480), 5, "y16"),
    ]
    result = group_profiles(profiles)
    assert result == {
        Profile("Depth", Resolution(640, 480), 0, "z16"): [15, 30],
        Profile("Infrared 1", Resolution(1280, 720), 0, "z16"): [5],
        Profile("Depth", Resolution(640, 480), 0, "y16"): [5],
    }


@pytest.mark.parametrize(
    "profile, expected",
    [
        ("depth", Profile("Depth", Resolution(0, 0), 0, "any")),
        ("depth-640x480", Profile("Depth", Resolution(640, 480), 0, "any")),
        ("depth-640x480-30", Profile("Depth", Resolution(640, 480), 30, "any")),
        ("depth-640x480-30-z16", Profile("Depth", Resolution(640, 480), 30, "z16")),
        ("infrared", Profile("Infrared 1", Resolution(0, 0), 0, "any")),
        ("infrared2-0x0-15", Profile("Infrared 2", Resolution(0, 0), 15, "any")),
    ],
)
def test_profile_from_string(profile, expected):
    assert Profile.from_string(profile) == expected


def test_profile_from_string_error():
    with pytest.raises(ValueError):
        Profile.from_string("depth-30")


@pytest.mark.parametrize(
    "profiles, expected",
    [
        ({"Stereo Module": [Profile("Depth")]}, {"Depth": "Stereo Module"}),
        (
            {"Stereo Module": [Profile("Depth"), Profile("Infrared 1")]},
            {"Depth": "Stereo Module", "Infrared 1": "Stereo Module"},
        ),
        (
            {
                "Stereo Module": [Profile("Depth"), Profile("Infrared 2")],
                "RGB Camera": [Profile("Color")],
            },
            {
                "Depth": "Stereo Module",
                "Infrared 2": "Stereo Module",
                "Color": "RGB Camera",
            },
        ),
    ],
)
def test_find_origin_sensor(profiles, expected):
    assert expected == find_origin_sensor(profiles)


# --- Robustness: unknown streams and sensors don't crash ---

def test_group_profiles_unknown_stream():
    profiles = [Profile("Future Stream", Resolution(640, 480), 30, "rgb8")]
    result = group_profiles(profiles)
    assert len(result) == 1


def test_find_origin_sensor_unknown():
    result = find_origin_sensor({"Future Sensor": [Profile("Future Stream")]})
    assert result == {"Future Stream": "Future Sensor"}


@pytest.mark.parametrize(
    "alias, expected_stream",
    [
        ("depth", "Depth"),
        ("infrared", "Infrared 1"),
        ("infrared2", "Infrared 2"),
        ("color", "Color"),
        ("gyro", "Gyro"),
        ("accel", "Accel"),
    ],
)
def test_profile_from_string_aliases(alias, expected_stream):
    p = Profile.from_string(alias)
    assert p.stream == expected_stream
