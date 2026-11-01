import shutil
import sqlite3
from contextlib import closing
from importlib.metadata import version
from typing import Any

import pyrealsense2 as rs
import pytest
from typer.testing import CliRunner

from realsense_cli.cli import app
from realsense_cli.driver.software import D435
from realsense_cli.errors import InvalidValue, NoFrames
from tests.conftest import RECORDED, record
from tests.test_json import invoke_json, json_error

runner = CliRunner()

# pyrealsense2 2.58 records intrinsics to 6 significant digits, and plays a recording back with
# each control's last recorded value rather than its first
SDK_2_58 = version("pyrealsense2").startswith("2.58.")


def _significant(value: Any, digits: int = 6) -> Any:
    """VALUE with every float in it rounded to DIGITS significant digits"""
    if isinstance(value, float):
        return float(f"{value:.{digits}g}")
    if isinstance(value, dict):
        return {k: _significant(v, digits) for k, v in value.items()}
    if isinstance(value, list):
        return [_significant(v, digits) for v in value]
    return value


def _stream(sensor: str, stream: str, width: int, fps: int, fmt: str) -> dict:
    height = width * 3 // 4
    return {
        "sensor": sensor,
        "stream": stream,
        "width": width,
        "height": height,
        "fps": fps,
        "format": fmt,
        "index": 0,
        "frames": RECORDED[stream],
    }


def test_info_json(recording, monkeypatch):
    monkeypatch.chdir(recording.parent)
    result = invoke_json("bag", "info", recording.name)
    assert result["duration"] > 0
    assert result["device"]["name"] == D435.name
    assert result["device"]["serial_number"] == D435.serial
    assert result == {
        "path": str(recording),
        "duration": result["duration"],
        "device": result["device"],
        "sensors": D435.sensors,
        "streams": [
            _stream("Stereo Module", "Depth", 640, 30, "Z16"),
            _stream("RGB Camera", "Color", 640, 30, "RGB8"),
            _stream("Motion Module", "Gyro", 0, 200, "MOTION_XYZ32F"),
            _stream("Motion Module", "Accel", 0, 63, "MOTION_XYZ32F"),
        ],
    }


def test_info_table(recording):
    result = runner.invoke(app, ["bag", "info", str(recording)])
    assert result.exit_code == 0, result.output
    assert D435.serial in result.stdout
    assert "Streams" in result.stdout
    assert "Frames" in result.stdout


def test_extension_is_case_insensitive(recording, tmp_path):
    path = shutil.copy(recording, tmp_path / "RUN.DB3")
    assert invoke_json("bag", "info", str(path))["streams"]


def test_stream_without_frames(tmp_path):
    path = record(tmp_path / "depth.db3", ["depth", "color"], [["Depth"], ["Depth"]])
    frames = {
        s["stream"]: s["frames"] for s in invoke_json("bag", "info", str(path))["streams"]
    }
    assert frames == {"Depth": 2, "Color": 0}


def test_recording_without_frames(tmp_path):
    path = record(tmp_path / "empty.db3", ["depth"], [])
    result = runner.invoke(app, ["--json", "bag", "info", str(path)])
    error = json_error(result, NoFrames.exit_code)
    assert "no frames" in error["message"]


def test_bag_extension_is_rejected(tmp_path):
    path = tmp_path / "run.bag"
    path.write_bytes(b"")
    result = runner.invoke(app, ["--json", "bag", "info", str(path)])
    error = json_error(result, InvalidValue.exit_code)
    assert "convert_bag_to_db3" in error["message"]


def test_stock_rosbag2_is_not_a_recording(rosbag2):
    result = runner.invoke(app, ["--json", "bag", "info", str(rosbag2)])
    error = json_error(result, InvalidValue.exit_code)
    assert "not a recording" in error["message"]


def test_other_file_is_not_a_recording(tmp_path):
    path = tmp_path / "notes.db3"
    path.write_text("not a database, but long enough for sqlite to read a header from it")
    result = runner.invoke(app, ["--json", "bag", "info", str(path)])
    error = json_error(result, InvalidValue.exit_code)
    assert "not a recording" in error["message"]


def test_info_touches_no_device(recording, monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("a device was reached")

    monkeypatch.setattr("realsense_cli.session.create_driver", fail)
    monkeypatch.setattr(rs.context, "devices", property(fail))
    assert invoke_json("bag", "info", str(recording))["streams"]


@pytest.mark.parametrize("name", ["missing.db3", "."])
def test_path_must_be_a_file(tmp_path, name):
    result = runner.invoke(app, ["bag", "info", str(tmp_path / name)])
    assert result.exit_code == 2


def test_recording_without_camera_info_is_not_a_recording(recording, tmp_path):
    path = shutil.copy(recording, tmp_path / "run.db3")
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("DELETE FROM topics WHERE name = '/device_0/info'")
    result = runner.invoke(app, ["--json", "bag", "info", str(path)])
    error = json_error(result, InvalidValue.exit_code)
    assert "/device_0/info" in error["message"]


def test_calibration_json_matches_rs_info(recording, driver):
    recorded = ["depth-640x480-30-z16", "color-640x480-30-rgb8"]
    expected = invoke_json("info", *recorded)
    result = invoke_json("bag", "info", "--calibration", str(recording))
    assert _significant(result["intrinsics"]) == _significant(expected["intrinsics"])
    if not SDK_2_58:
        assert result["intrinsics"] == expected["intrinsics"]
    assert result["extrinsics"] == expected["extrinsics"]
    assert "controls" not in result


def test_calibration_holds_recorded_profiles_only(recording):
    result = invoke_json("bag", "info", "--calibration", str(recording))
    assert [(i["stream"], i["width"], i["fps"]) for i in result["intrinsics"]] == [
        ("Depth", 640, [30]),
        ("Color", 640, [30]),
    ]
    # the motion streams have no intrinsics, nor extrinsics in the recording: left out
    assert {(e["from"], e["to"]) for e in result["extrinsics"]} == {
        ("Depth", "Color"),
        ("Color", "Depth"),
    }


def test_controls_json_matches_config_get(recording, driver):
    result = invoke_json("bag", "info", "--controls", str(recording))
    assert "intrinsics" not in result
    expected = [
        {"sensor": sensor, "values": invoke_json("config", "get", sensor, "--all")["values"]}
        for sensor in D435.sensors
    ]
    # the recorder writes the host-side queue size as 0, whatever it was
    for controls in result["controls"]:
        assert controls["values"].pop("frames_queue_size") == 0
    for controls in expected:
        del controls["values"]["frames_queue_size"]
    assert result["controls"] == expected


@pytest.mark.skipif(SDK_2_58, reason="pyrealsense2 2.58 plays back the last recorded value")
def test_controls_show_values_at_the_recording_start(recording, tmp_path):
    path = shutil.copy(recording, tmp_path / "run.db3")
    topic = "/device_0/sensor_0/option/Laser_Power/value"
    with closing(sqlite3.connect(path)) as db, db:
        topic_id, start = db.execute(
            "SELECT topics.id, timestamp FROM messages"
            " JOIN topics ON topics.id = messages.topic_id WHERE topics.name = ?",
            (topic,),
        ).fetchone()
        (end,) = db.execute("SELECT MAX(timestamp) FROM messages").fetchone()
        # a std_msgs/String in CDR: encapsulation header, length, then the NUL-ended text
        text = b"30.000000\0"
        data = b"\0\1\0\0" + len(text).to_bytes(4, "little") + text
        db.execute(
            "INSERT INTO messages (topic_id, timestamp, data) VALUES (?, ?, ?)",
            (topic_id, max(start + 1, end), data),
        )
    controls = invoke_json("bag", "info", "--controls", str(path))["controls"]
    assert controls[0]["values"]["laser_power"] == 150.0


def test_calibration_and_controls_tables(recording):
    result = runner.invoke(app, ["bag", "info", "--calibration", "--controls", str(recording)])
    assert result.exit_code == 0, result.output
    for title in ("Streams", "Intrinsics", "Distortion", "Extrinsics"):
        assert title in result.stdout
    for sensor in D435.sensors:
        assert f"{sensor} Controls" in result.stdout
    assert "laser_power" in result.stdout


def test_tables_leave_out_calibration_and_controls_by_default(recording):
    result = runner.invoke(app, ["bag", "info", str(recording)])
    assert result.exit_code == 0, result.output
    assert "Intrinsics" not in result.stdout
    assert "Controls" not in result.stdout
