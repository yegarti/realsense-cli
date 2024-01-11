import pytest

from realsense_cli.types import (
    Profile,
    SafetyInterfaceConfig,
    SafetyMaskingZone,
    SafetyPin,
    SafetyPreset,
    SafetyZone,
    Stream,
    Resolution,
    Sensor,
)
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


def test_preset_convert():
    preset = SafetyPreset(
        safety_zones=[
            SafetyZone(
                points=[(0.0, 0.2), (2.5, 0.2), (2.4, -0.1), (0.0, -0.1)], trigger_confidence=0
            ),
            SafetyZone(
                points=[(0.0, 0.2), (2.4, 0.2), (2.4, -0.1), (0.0, -0.1)], trigger_confidence=0
            ),
        ],
        masking_zones=[
            SafetyMaskingZone(
                attributes=0, pixels=[(0, 0), (0, 0), (0, 0), (0, 0)], minimal_range=0.0
            ),
            SafetyMaskingZone(
                attributes=0, pixels=[(0, 0), (0, 0), (0, 0), (0, 0)], minimal_range=0.0
            ),
            SafetyMaskingZone(
                attributes=0, pixels=[(0, 0), (0, 0), (0, 0), (0, 0)], minimal_range=0.0
            ),
            SafetyMaskingZone(
                attributes=0, pixels=[(0, 0), (0, 0), (0, 0), (0, 0)], minimal_range=0.0
            ),
            SafetyMaskingZone(
                attributes=0, pixels=[(0, 0), (0, 0), (0, 0), (0, 0)], minimal_range=0.0
            ),
            SafetyMaskingZone(
                attributes=0, pixels=[(0, 0), (0, 0), (0, 0), (0, 0)], minimal_range=0.0
            ),
            SafetyMaskingZone(
                attributes=0, pixels=[(0, 0), (0, 0), (0, 0), (0, 0)], minimal_range=0.0
            ),
            SafetyMaskingZone(
                attributes=0, pixels=[(0, 0), (0, 0), (0, 0), (0, 0)], minimal_range=0.0
            ),
        ],
        rotation=[[0.0, 0.0, 1.0], [-1.0, 0.0, 0.0], [0.0, -1.0, 0.0]],
        translation=[0.0, 0.0, 0.18],
        robot_height=0.2,
        grid_cell_size=0.02,
        surface_height=0.1,
        surface_inclination=15.0,
    )
    assert preset == SafetyPreset.from_json(preset.to_json())


def test_interface_convert():
    interface = SafetyInterfaceConfig(
        input_delay=150,
        pins={
            'gpio_0': SafetyPin(name='preset_select5_a', direction='input'),
            'gpio_1': SafetyPin(name='preset_select5_b', direction='input'),
            'gpio_2': SafetyPin(name='device_ready', direction='output'),
            'gpio_3': SafetyPin(name='maintenance', direction='output'),
            'gpio_4': SafetyPin(name='restart_interlock', direction='input'),
            'ground': SafetyPin(name='gnd', direction='input'),
            'ossd1_a': SafetyPin(name='ossd1_a', direction='output'),
            'ossd1_b': SafetyPin(name='ossd1_b', direction='output'),
            'power': SafetyPin(name='p24vdc', direction='input'),
            'preset1_a': SafetyPin(name='preset_select1_a', direction='input'),
            'preset1_b': SafetyPin(name='preset_select1_b', direction='input'),
            'preset2_a': SafetyPin(name='preset_select2_a', direction='input'),
            'preset2_b': SafetyPin(name='preset_select2_b', direction='input'),
            'preset3_a': SafetyPin(name='preset_select3_a', direction='input'),
            'preset3_b': SafetyPin(name='preset_select3_b', direction='input'),
            'preset4_a': SafetyPin(name='preset_select4_a', direction='input'),
            'preset4_b': SafetyPin(name='preset_select4_b', direction='input')
        }
    )
    assert interface == SafetyInterfaceConfig.from_json(interface.to_json())
