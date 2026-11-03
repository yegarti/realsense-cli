import json
import time
from itertools import count

import pytest
from typer.testing import CliRunner

from realsense_cli.cli import app
from realsense_cli.errors import InvalidValue, NoFrames
from realsense_cli.types import Frame, Profile, Resolution

runner = CliRunner()


def test_frames_bound_emits_frame_counts(feed):
    result = runner.invoke(app, ["--json", "stream", "play", "depth", "--frames", "5"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {"streams": [{"stream": "Depth", "frames": 5}]}


def test_duration_bound_stops_on_its_own(feed):
    started = time.monotonic()
    result = runner.invoke(app, ["--json", "stream", "play", "depth", "--duration", "0.2"])
    assert result.exit_code == 0, result.output
    assert time.monotonic() - started >= 0.2
    [depth] = json.loads(result.stdout)["streams"]
    assert depth["stream"] == "Depth"
    assert depth["frames"] > 0


def test_requested_stream_without_frames_fails(feed, monkeypatch):
    monkeypatch.setattr("realsense_cli.commands.stream.FRAME_TIMEOUT", 0.1)
    feed.streams = ["Depth"]
    result = runner.invoke(app, ["--json", "stream", "play", "depth", "color", "--frames", "4"])
    assert result.exit_code == NoFrames.exit_code, result.output
    assert result.stdout == ""
    error = json.loads(result.stderr.splitlines()[-1])["error"]
    assert error["type"] == "NoFrames"
    assert "Color" in error["message"]


def test_frame_timeout_fails_bounded_run(driver, monkeypatch):
    monkeypatch.setattr("realsense_cli.commands.stream.FRAME_TIMEOUT", 0.05)
    result = runner.invoke(app, ["stream", "play", "--frames", "3"])
    assert result.exit_code == NoFrames.exit_code, result.output
    assert "0.05s" in result.stderr


def test_duration_without_any_frames_fails(driver):
    result = runner.invoke(app, ["stream", "play", "--duration", "0.1"])
    assert result.exit_code == NoFrames.exit_code, result.output


def test_bounded_run_prints_summary_table(feed):
    result = runner.invoke(app, ["stream", "play", "depth", "--frames", "3"])
    assert result.exit_code == 0, result.output
    summary = result.stdout[result.stdout.index("Frames received") :]
    line = next(line for line in summary.splitlines() if "Depth" in line)
    assert line.split() == ["Depth", "3"]


def test_unbounded_run_streams_until_interrupted(feed, driver, monkeypatch):
    waits = 0
    wait = driver.wait_for_frameset

    def interrupt_after_20(*args, **kwargs):
        nonlocal waits
        waits += 1
        if waits > 20:
            raise KeyboardInterrupt
        return wait(*args, **kwargs)

    monkeypatch.setattr(driver, "wait_for_frameset", interrupt_after_20)
    result = runner.invoke(app, ["stream", "play", "depth"])
    assert waits == 21
    assert "Frames received" not in result.stdout
    assert "Stopping all streams" in result.stderr


@pytest.mark.parametrize("bound", [["--frames", "0"], ["--duration", "0"]])
def test_non_positive_bound_is_usage_error(driver, bound):
    # under --json: Rich colours the plain usage message, which splits the option name
    result = runner.invoke(app, ["--json", "stream", "play", *bound])
    assert result.exit_code == 2, result.output
    assert bound[0] in json.loads(result.stderr)["error"]["message"]


def test_default_stream_without_frames_fails(feed, monkeypatch):
    monkeypatch.setattr("realsense_cli.commands.stream.FRAME_TIMEOUT", 0.1)
    feed.streams = ["Depth", "Infrared 1", "Infrared 2", "Color", "Gyro"]
    result = runner.invoke(app, ["stream", "play", "--frames", "2"])
    assert result.exit_code == NoFrames.exit_code, result.output
    assert "Accel" in result.stderr


def test_frames_bound_counts_per_stream(feed):
    result = runner.invoke(app, ["--json", "stream", "play", "depth", "color", "--frames", "3"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["streams"] == [
        {"stream": "Depth", "frames": 3},
        {"stream": "Color", "frames": 3},
    ]


def test_silent_stream_fails_duration_run_early(feed, monkeypatch):
    monkeypatch.setattr("realsense_cli.commands.stream.FRAME_TIMEOUT", 0.1)
    feed.streams = ["Depth"]
    started = time.monotonic()
    result = runner.invoke(app, ["stream", "play", "depth", "color", "--duration", "5"])
    assert result.exit_code == NoFrames.exit_code, result.output
    assert "Color" in result.stderr
    assert time.monotonic() - started < 1


def test_repeated_frame_counts_once(driver, monkeypatch):
    """The pipeline can hand out a slower stream's last frame again in later framesets"""
    monkeypatch.setattr("realsense_cli.commands.stream.FRAME_TIMEOUT", 0.1)
    depth = Profile("Depth", Resolution(640, 480), 30, "z16", 0)
    color = Profile("Color", Resolution(640, 480), 30, "rgb8", 0)
    indexes = count()

    def color_stuck_on_first_frame(*args, **kwargs):
        index = next(indexes)
        return {
            "Depth": Frame(depth, timestamp=index, index=index, metadata={}),
            "Color": Frame(color, timestamp=0, index=0, metadata={}),
        }

    monkeypatch.setattr(driver, "wait_for_frameset", color_stuck_on_first_frame)
    result = runner.invoke(app, ["stream", "play", "depth", "color", "--frames", "3"])
    assert result.exit_code == NoFrames.exit_code, result.output
    assert "No frames arrived from Color" in result.stderr
    assert "Color 1" in result.stderr


def test_preview_draws_colorized_depth(feed):
    result = runner.invoke(
        app, ["stream", "play", "depth", "--preview-mode", "halfblock", "--frames", "3"]
    )
    assert result.exit_code == 0, result.output
    assert "▀" in result.stdout
    assert "\x1b[38;2;" in result.stdout
    assert "Depth (0)" in result.stdout
    summary = result.stdout[result.stdout.index("Frames received") :]
    assert next(line for line in summary.splitlines() if "Depth" in line).split() == [
        "Depth",
        "3",
    ]


def test_preview_draws_yuyv_color(feed):
    result = runner.invoke(
        app,
        [
            "stream",
            "play",
            "depth",
            "color-640x480-30-yuyv",
            "--preview-stream",
            "color",
            "--preview-mode",
            "halfblock",
            "--frames",
            "2",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "▀" in result.stdout
    assert "no preview" not in result.stdout


def test_preview_falls_back_to_ascii_without_color(feed):
    # CliRunner's stdout is no terminal: Rich detects no color
    result = runner.invoke(app, ["stream", "play", "depth", "--preview", "--frames", "2"])
    assert result.exit_code == 0, result.output
    assert "▀" not in result.stdout
    assert "\x1b[" not in result.stdout
    assert any(char in result.stdout for char in "@%#*")


@pytest.mark.parametrize("option", [["--preview"], ["--preview-mode", "ascii"]])
def test_preview_with_json_is_usage_error(driver, option):
    result = runner.invoke(app, ["--json", "stream", "play", "--frames", "1", *option])
    assert result.exit_code == 2, result.output
    assert "--preview" in json.loads(result.stderr)["error"]["message"]


def test_preview_stream_must_be_a_playing_video_stream(feed):
    result = runner.invoke(
        app, ["stream", "play", "depth", "gyro", "--preview-stream", "gyro", "--frames", "1"]
    )
    assert result.exit_code == InvalidValue.exit_code, result.output
    assert "Can't preview 'gyro'" in result.stderr
    assert "Video streams playing: Depth" in result.stderr
    assert "Stopping all streams" in result.stderr


def test_preview_needs_a_video_stream(feed):
    result = runner.invoke(app, ["stream", "play", "gyro", "--preview", "--frames", "1"])
    assert result.exit_code == InvalidValue.exit_code, result.output
    assert "No video stream to preview" in result.stderr


def test_preview_stream_takes_alias_in_any_case(feed):
    result = runner.invoke(
        app,
        [
            "stream",
            "play",
            "depth",
            "infrared",
            "--preview-stream",
            "INFRARED",
            "--frames",
            "1",
        ],
    )
    assert result.exit_code == 0, result.output


@pytest.mark.parametrize(("args", "images"), [([], False), (["--preview"], True)])
def test_frames_carry_images_only_with_preview(feed, driver, monkeypatch, args, images):
    asked = set()
    wait = driver.wait_for_frameset

    def record(*a, **kwargs):
        asked.add(kwargs.get("images", False))
        return wait(*a, **kwargs)

    monkeypatch.setattr(driver, "wait_for_frameset", record)
    result = runner.invoke(app, ["stream", "play", "depth", "--frames", "2", *args])
    assert result.exit_code == 0, result.output
    assert asked == {images}
