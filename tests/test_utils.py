import pytest

from realsense_cli.errors import InvalidProfile
from realsense_cli.types import Profile, Resolution
from realsense_cli.utils import find_origin_sensor, group_profiles, wait_for_reconnect


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
    with pytest.raises(InvalidProfile):
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


def _scripted(*states: set[str]):
    """Connected serials per call, repeating the last state once the script runs out."""
    calls = iter(states)
    last = states[-1]

    def connected() -> set[str]:
        nonlocal last
        last = next(calls, last)
        return last

    return connected


def test_wait_for_reconnect_after_device_drops_and_returns():
    connected = _scripted({"1", "2"}, {"2"}, {"2"}, {"1", "2"})
    assert wait_for_reconnect("1", connected, timeout=1, poll=0.001)


def test_wait_for_reconnect_keeps_waiting_while_device_is_still_listed():
    """Right after a reset the device is often still listed; that isn't a reconnect yet."""
    connected = _scripted({"1"})
    assert not wait_for_reconnect("1", connected, timeout=0.05, poll=0.001, drop_grace=1)


def test_wait_for_reconnect_accepts_a_device_that_never_seemed_to_drop():
    """A drop and return between two polls is missed; a device still there later is back."""
    connected = _scripted({"1"})
    assert wait_for_reconnect("1", connected, timeout=1, poll=0.001, drop_grace=0.01)


def test_wait_for_reconnect_times_out_when_device_stays_gone():
    connected = _scripted({"1"}, set())
    assert not wait_for_reconnect("1", connected, timeout=0.05, poll=0.001, drop_grace=0.01)
