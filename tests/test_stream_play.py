import json
import time

import pytest
from typer.testing import CliRunner

from realsense_cli.cli import app
from realsense_cli.errors import NoFrames

runner = CliRunner()


@pytest.fixture
def feed(driver, camera, monkeypatch):
    """
    Push a frame to the fed streams each time `rs stream play` waits for one: the software
    camera produces no frames on its own. Every active stream is fed until `feed` is set to
    a list of stream names
    """
    fed: list[str | None] = [None]
    wait = driver.wait_for_frameset

    def push_then_wait(timeout: float = 3.0):
        camera.push_frames(fed[0])
        return wait(timeout)

    monkeypatch.setattr(driver, "wait_for_frameset", push_then_wait)
    return fed


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


def test_requested_stream_without_frames_fails(feed):
    feed[0] = ["Depth"]
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

    def interrupt_after_20(timeout: float = 3.0):
        nonlocal waits
        waits += 1
        if waits > 20:
            raise KeyboardInterrupt
        return wait(timeout)

    monkeypatch.setattr(driver, "wait_for_frameset", interrupt_after_20)
    result = runner.invoke(app, ["stream", "play", "depth"])
    assert waits == 21
    assert "Frames received" not in result.stdout
    assert "Stopping all streams" in result.stderr


@pytest.mark.parametrize("bound", [["--frames", "0"], ["--duration", "0"]])
def test_non_positive_bound_is_usage_error(driver, bound):
    result = runner.invoke(app, ["stream", "play", *bound])
    assert result.exit_code == 2, result.output
    assert bound[0] in result.stderr
