import json

import pytest
from typer.testing import CliRunner

from realsense_cli.cli import app
from realsense_cli.errors import InvalidProfile

runner = CliRunner()


def invoke_json(*args: str) -> dict:
    result = runner.invoke(app, ["--json", *args])
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def test_info_lists_camera_info_and_sensors_without_calibration(driver):
    assert invoke_json("info") == {
        "device": {
            "name": "Intel RealSense D435",
            "serial_number": "012345678",
            "firmware_version": "5.15.0.0",
            "recommended_firmware_version": "5.16.0.1",
            "physical_port": "/sys/devices/pci0000:00/usb2/2-1",
            "product_id": "0B07",
            "camera_locked": "YES",
            "usb_type_descriptor": "3.2",
            "product_line": "D400",
            "asic_serial_number": "123456789012",
        },
        "sensors": ["Stereo Module", "RGB Camera", "Motion Module"],
    }


IDENTITY = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]

DEPTH_INTRINSICS = {
    "stream": "Depth",
    "index": 0,
    "width": 640,
    "height": 480,
    "formats": ["Z16"],
    "fps": [6, 15, 30],
    "ppx": 320.5,
    "ppy": 240.25,
    "fx": 385.5,
    "fy": 385.75,
    "model": "brown_conrady",
    "coeffs": [0.0, 0.0, 0.0, 0.0, 0.0],
}

COLOR_INTRINSICS = {
    "stream": "Color",
    "index": 0,
    "width": 640,
    "height": 480,
    "formats": ["RGB8"],
    "fps": [6, 15, 30],
    "ppx": 321.75,
    "ppy": 243.5,
    "fx": 615.25,
    "fy": 615.5,
    "model": "inverse_brown_conrady",
    "coeffs": [0.125, -0.25, 0.001, -0.0005, 0.0625],
}


def test_info_with_profiles_adds_intrinsics_and_extrinsics(driver):
    result = invoke_json("info", "depth", "color")
    assert result["intrinsics"] == [DEPTH_INTRINSICS, COLOR_INTRINSICS]
    assert result["extrinsics"] == [
        {
            "from": "Depth",
            "to": "Color",
            "rotation": IDENTITY,
            "translation": [0.0147, 0.0001, 0.0004],
        },
        {
            "from": "Color",
            "to": "Depth",
            "rotation": IDENTITY,
            "translation": [-0.0147, -0.0001, -0.0004],
        },
    ]


def test_all_profiles_covers_every_video_profile(driver):
    result = invoke_json("info", "--all-profiles")
    infrared = {**DEPTH_INTRINSICS, "formats": ["Y8"]}
    assert result["intrinsics"] == [
        DEPTH_INTRINSICS,
        {**infrared, "stream": "Infrared 1", "index": 1, "fps": [15, 30]},
        {**infrared, "stream": "Infrared 2", "index": 2, "fps": [30]},
        COLOR_INTRINSICS,
    ]
    pairs = {(e["from"], e["to"]): e for e in result["extrinsics"]}
    streams = ["Depth", "Infrared 1", "Infrared 2", "Color"]
    assert set(pairs) == {(a, b) for a in streams for b in streams if a != b}
    assert pairs["Infrared 2", "Color"]["translation"] == [0.0647, 0.0001, 0.0004]


def json_error(result, exit_code: int) -> dict:
    assert result.exit_code == exit_code, result.output
    assert result.stdout == ""
    return json.loads(result.stderr.splitlines()[-1])["error"]


@pytest.mark.parametrize(
    ("profile", "message"),
    [
        ("depth-big", "Failed to parse profile 'depth-big'"),
        ("bogus", "Unknown stream 'bogus'"),
        ("depth-1280x720", "No video profile matches"),
        ("gyro", "No video profile matches"),
    ],
)
def test_invalid_profile_fails(driver, profile, message):
    result = runner.invoke(app, ["--json", "info", "depth", profile])
    error = json_error(result, InvalidProfile.exit_code)
    assert error["type"] == "InvalidProfile"
    assert message in error["message"]


def test_profiles_and_all_profiles_together_is_a_usage_error(driver):
    result = runner.invoke(app, ["--json", "info", "depth", "--all-profiles"])
    error = json_error(result, 2)
    assert error["type"] == "UsageError"
    assert "--all-profiles" in error["message"]


def test_table_shows_device_details_without_calibration(driver):
    result = runner.invoke(app, ["info"])
    assert result.exit_code == 0, result.output
    assert "Recommended Firmware Version" in result.stdout
    assert "5.16.0.1" in result.stdout
    assert "Stereo Module (depth)" in result.stdout
    assert "Intrinsics" not in result.stdout


def test_table_shows_calibration_for_profiles(driver):
    result = runner.invoke(app, ["info", "depth", "color"])
    assert result.exit_code == 0, result.output
    assert "Intrinsics of Color 640x480 RGB8 @ 6/15/30 fps" in result.stdout
    assert "inverse_brown_conrady" in result.stdout
    assert "0.0147, 0.0001, 0.0004" in result.stdout
