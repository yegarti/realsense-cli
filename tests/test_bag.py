import shutil
import sqlite3
from contextlib import closing

import pyrealsense2 as rs
import pytest
from typer.testing import CliRunner

from realsense_cli.cli import app
from realsense_cli.driver.software import D435
from realsense_cli.errors import InvalidValue, NoFrames
from tests.conftest import RECORDED, record
from tests.test_json import invoke_json, json_error

runner = CliRunner()


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
