import pytest

from realsense_cli.types import Profile, Stream, Resolution, Sensor
from realsense_cli.utils import group_profiles, find_origin_sensor


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


@pytest.mark.parametrize(
    "profile, expected",
    [
        ("depth", Profile(Stream.DEPTH, Resolution(0, 0), 0, "any")),
        ("depth-640x480", Profile(Stream.DEPTH, Resolution(640, 480), 0, "any")),
        ("depth-640x480-30", Profile(Stream.DEPTH, Resolution(640, 480), 30, "any")),
        ("depth-640x480-30-z16", Profile(Stream.DEPTH, Resolution(640, 480), 30, "z16")),
        ("infrared", Profile(Stream.INFRARED, Resolution(0, 0), 0, "any")),
        ("infrared2-0x0-15", Profile(Stream.INFRARED2, Resolution(0, 0), 15, "any")),
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
        ({Sensor.STEREO_MODULE: [Profile(Stream.DEPTH)]}, {Stream.DEPTH: Sensor.STEREO_MODULE}),
        (
            {Sensor.STEREO_MODULE: [Profile(Stream.DEPTH), Profile(Stream.INFRARED)]},
            {Stream.DEPTH: Sensor.STEREO_MODULE, Stream.INFRARED: Sensor.STEREO_MODULE},
        ),
        (
            {
                Sensor.STEREO_MODULE: [Profile(Stream.DEPTH), Profile(Stream.INFRARED2)],
                Sensor.RGB_CAMERA: [Profile(Stream.COLOR)],
            },
            {
                Stream.DEPTH: Sensor.STEREO_MODULE,
                Stream.INFRARED2: Sensor.STEREO_MODULE,
                Stream.COLOR: Sensor.RGB_CAMERA,
            },
        ),
    ],
)
def test_find_origin_sensor(profiles, expected):
    assert expected == find_origin_sensor(profiles)
