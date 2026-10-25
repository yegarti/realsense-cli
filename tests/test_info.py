import pyrealsense2 as rs
import pytest
from typer.testing import CliRunner

from realsense_cli.cli import app
from realsense_cli.driver.software import D435, D435_SENSORS, SoftwareCamera
from realsense_cli.errors import InvalidProfile
from tests.test_json import invoke_json, json_error

runner = CliRunner()

# pyrealsense2 2.56 has no imu_type camera info
HAS_IMU_TYPE = "imu_type" in rs.camera_info.__members__


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
            "connection_type": "USB",
            "usb_type_descriptor": "3.2",
            "product_line": "D400",
            "asic_serial_number": "123456789012",
            **({"imu_type": "BMI055"} if HAS_IMU_TYPE else {}),
        },
        "sensors": ["Stereo Module", "RGB Camera", "Motion Module"],
    }


def test_connection_type_comes_right_before_usb_type(driver):
    fields = list(invoke_json("info")["device"])
    assert fields.index("connection_type") + 1 == fields.index("usb_type_descriptor")


@pytest.mark.skipif(not HAS_IMU_TYPE, reason="pyrealsense2 has no imu_type camera info")
def test_unknown_camera_info_is_left_out(make_driver):
    # a D415 has no IMU, and reports its IMU type as "unknown"
    make_driver(SoftwareCamera(D435, D435_SENSORS, {"imu_type": "unknown"}))
    assert "imu_type" not in invoke_json("info")["device"]


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
    # float32 holds 385.12345 as 385.1234436...: 385.12344 is its shortest round-trip form
    "fy": 385.12344,
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


@pytest.mark.parametrize(
    ("profile", "message"),
    [
        ("depth-big", "Failed to parse profile 'depth-big'"),
        ("bogus", "Unknown stream 'bogus'"),
        ("depth-1280x720", "No video profile matches"),
        ("gyro", "Video streams: Depth, Infrared 1, Infrared 2, Color"),
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


def table_row(output: str, *cells: str) -> list[str]:
    """The cells of the one row in OUTPUT that holds all of CELLS"""
    [row] = [line for line in output.splitlines() if all(cell in line for cell in cells)]
    return row.split()


def test_table_shows_intrinsics_with_their_attributes(driver):
    result = runner.invoke(app, ["info", "depth", "color"])
    assert result.exit_code == 0, result.output
    assert table_row(result.stdout, "ppx", "fy") == [
        "Stream", "Resolution", "ppx", "ppy", "fx", "fy", "Formats"
    ]  # fmt: skip
    assert table_row(result.stdout, "Depth", "640x480") == [
        "Depth", "640x480", "320.5", "240.25", "385.5", "385.12344", "Z16"
    ]  # fmt: skip


def test_table_shows_distortion_once_per_stream(driver):
    result = runner.invoke(app, ["info", "--all-profiles"])
    assert result.exit_code == 0, result.output
    assert table_row(result.stdout, "Color", "inverse_brown_conrady") == [
        "Color", "inverse_brown_conrady", "0.125,", "-0.25,", "0.001,", "-0.0005,", "0.0625"
    ]  # fmt: skip
    assert len([line for line in result.stdout.splitlines() if "brown_conrady" in line]) == 4


def test_table_shows_extrinsics(driver):
    result = runner.invoke(app, ["info", "depth", "color"])
    assert result.exit_code == 0, result.output
    rows = [line.split() for line in result.stdout.splitlines()]
    # the rotation matrix, and the translation as a column beside it
    assert ["Depth", "Color", "1", "0", "0", "0.0147"] in rows
    assert ["0", "1", "0", "0.0001"] in rows
    assert ["0", "0", "1", "0.0004"] in rows
