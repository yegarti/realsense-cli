import re
from collections.abc import Collection

import pytest
from typer.testing import CliRunner

from realsense_cli.cli import app
from realsense_cli.errors import InvalidProfile, InvalidValue, NoFrames
from tests.test_json import invoke_json, json_error

runner = CliRunner()


@pytest.fixture
def interrupt_after(driver, camera, monkeypatch):
    """
    Push one frame to the streams each of PUSHES names, each time the recording waits for one
    and none is queued, then press Ctrl-C
    """

    def script(pushes: list[Collection[str]]) -> None:
        wait = driver.wait_for_frameset
        pending = iter(pushes)

        def push_then_wait(timeout: float = 3.0, **kwargs):
            frameset = wait(0, **kwargs)
            if frameset is None:
                streams = next(pending, None)
                if streams is None:
                    raise KeyboardInterrupt
                camera.push_frames(streams)
                frameset = wait(timeout, **kwargs)
            return frameset

        monkeypatch.setattr(driver, "wait_for_frameset", push_then_wait)

    return script


def _frames(payload: dict) -> dict[str, int]:
    return {stream["stream"]: stream["frames"] for stream in payload["streams"]}


def test_frames_bound_records_n_frames_per_stream(feed, tmp_path):
    path = tmp_path / "run.db3"
    result = invoke_json(
        "bag", "record", "depth-640x480-30-z16", "color-640x480-30-rgb8", "--frames", "4",
        "-o", str(path),
    )  # fmt: skip
    assert result == {
        "path": str(path),
        "duration": result["duration"],
        "size": path.stat().st_size,
        "streams": [
            {
                "sensor": "Stereo Module",
                "stream": "Depth",
                "width": 640,
                "height": 480,
                "fps": 30,
                "format": "Z16",
                "index": 0,
                "frames": 4,
            },
            {
                "sensor": "RGB Camera",
                "stream": "Color",
                "width": 640,
                "height": 480,
                "fps": 30,
                "format": "RGB8",
                "index": 0,
                "frames": 4,
            },
        ],
    }
    assert result["duration"] >= 0
    assert _frames(invoke_json("bag", "info", str(path))) == {"Depth": 4, "Color": 4}


def test_ctrl_c_keeps_the_recording(interrupt_after, tmp_path):
    path = tmp_path / "run.db3"
    interrupt_after([["Depth", "Color"]] * 2 + [["Depth"]] * 3)
    result = invoke_json("bag", "record", "depth", "color", "-o", str(path), "--duration", "60")
    assert _frames(result) == {"Depth": 5, "Color": 2}
    assert _frames(invoke_json("bag", "info", str(path))) == {"Depth": 5, "Color": 2}


def test_no_profiles_records_every_default_stream(feed, tmp_path):
    path = tmp_path / "run.db3"
    result = invoke_json("bag", "record", "--frames", "2", "-o", str(path))
    streams = ["Depth", "Infrared 1", "Infrared 2", "Color", "Gyro", "Accel"]
    assert _frames(result) == dict.fromkeys(streams, 2)
    assert _frames(invoke_json("bag", "info", str(path))) == dict.fromkeys(streams, 2)


def test_ctrl_c_before_the_first_frame_fails(interrupt_after, tmp_path):
    path = tmp_path / "run.db3"
    interrupt_after([])
    result = runner.invoke(
        app, ["--json", "bag", "record", "depth", "-o", str(path), "--duration", "60"]
    )
    error = json_error(result, NoFrames.exit_code)
    assert "first frame" in error["message"]
    assert not path.exists()


def test_stalled_stream_fails_and_deletes_the_file(feed, tmp_path, monkeypatch):
    monkeypatch.setattr("realsense_cli.commands.stream.FRAME_TIMEOUT", 0.1)
    feed.streams = ["Depth"]
    path = tmp_path / "run.db3"
    result = runner.invoke(
        app, ["--json", "bag", "record", "depth", "color", "--frames", "5", "-o", str(path)]
    )
    error = json_error(result, NoFrames.exit_code)
    assert "Color" in error["message"]
    assert not path.exists()


def test_existing_file_is_refused(driver, tmp_path):
    path = tmp_path / "run.db3"
    path.write_text("keep me")
    result = runner.invoke(app, ["--json", "bag", "record", "--frames", "1", "-o", str(path)])
    error = json_error(result, InvalidValue.exit_code)
    assert "--force" in error["message"]
    assert path.read_text() == "keep me"


def test_force_replaces_an_existing_file(feed, tmp_path):
    path = tmp_path / "run.db3"
    path.write_text("replace me")
    result = invoke_json("bag", "record", "depth", "--frames", "1", "-o", str(path), "--force")
    assert _frames(result) == {"Depth": 1}
    assert _frames(invoke_json("bag", "info", str(path))) == {"Depth": 1}


def test_invalid_profile_leaves_an_existing_file_alone(driver, tmp_path):
    path = tmp_path / "run.db3"
    path.write_text("keep me")
    result = runner.invoke(
        app, ["--json", "bag", "record", "depth-1x1", "--frames", "1", "-o", str(path), "-f"]
    )
    json_error(result, InvalidProfile.exit_code)
    assert path.read_text() == "keep me"


@pytest.mark.parametrize("name", ["run.bag", "run.db3.tmp", "run"])
def test_other_extension_is_refused_before_the_device(tmp_path, monkeypatch, name):
    def fail():
        raise AssertionError("a device was reached")

    monkeypatch.setattr("realsense_cli.session.create_driver", fail)
    path = tmp_path / name
    result = runner.invoke(app, ["--json", "bag", "record", "--frames", "1", "-o", str(path)])
    error = json_error(result, InvalidValue.exit_code)
    assert ".db3" in error["message"]
    assert not path.exists()


def test_extension_is_case_insensitive(feed, tmp_path):
    path = tmp_path / "new" / "dirs" / "RUN.DB3"
    result = invoke_json("bag", "record", "depth", "--frames", "2", "-o", str(path))
    assert result["path"] == str(path)
    # recorded under a temporary `.db3` name, then renamed
    assert [p.name for p in path.parent.iterdir()] == ["RUN.DB3"]
    assert _frames(invoke_json("bag", "info", str(path))) == {"Depth": 2}


def test_default_output_is_a_new_file_in_the_working_directory(feed, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    first = invoke_json("bag", "record", "depth", "--frames", "1")["path"]
    second = invoke_json("bag", "record", "depth", "--frames", "1")["path"]
    assert re.fullmatch(rf"{re.escape(str(tmp_path))}/rs-recording-\d{{8}}-\d{{6}}\.db3", first)
    assert second != first
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(
        p.rsplit("/", 1)[1] for p in (first, second)
    )


def test_json_needs_a_bound(driver):
    result = runner.invoke(app, ["--json", "bag", "record", "depth"])
    error = json_error(result, 2)
    assert "--frames or --duration" in error["message"]


@pytest.mark.parametrize("bound", ["0", "-1"])
def test_non_positive_duration_is_usage_error(driver, bound):
    result = runner.invoke(app, ["bag", "record", "--duration", bound])
    assert result.exit_code == 2


def test_summary_table(feed, tmp_path):
    path = tmp_path / "run.db3"
    result = runner.invoke(app, ["bag", "record", "depth", "--frames", "3", "-o", str(path)])
    assert result.exit_code == 0, result.output
    assert f"Recording to {path} (Ctrl-C to stop)" in result.stderr
    for text in ("Recording", "Duration", "Size", "Streams", "Stereo Module", "Depth"):
        assert text in result.stdout


def test_needs_a_device(inject_driver, tmp_path):
    from realsense_cli.driver.realsense import Realsense

    inject_driver(Realsense(devices=[]))
    result = runner.invoke(
        app, ["--json", "bag", "record", "--frames", "1", "-o", str(tmp_path / "run.db3")]
    )
    json_error(result, 3)
    assert not any(tmp_path.iterdir())


def test_device_that_fails_to_start_leaves_no_file(driver, tmp_path, monkeypatch):
    def fail(rs_profiles):
        raise RuntimeError("failed to start")

    monkeypatch.setattr(driver, "_start_sensors", fail)
    path = tmp_path / "run.db3"
    result = runner.invoke(app, ["--json", "bag", "record", "--frames", "1", "-o", str(path)])
    json_error(result, 1)
    assert not path.exists()
