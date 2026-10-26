import json
from array import array

import pytest
from typer.testing import CliRunner

from realsense_cli.cli import app
from realsense_cli.depth import Region, median, region_stats
from realsense_cli.driver.software import (
    D435,
    DEPTH_BACKGROUND,
    DEPTH_FLICKER,
    DEPTH_NEAR,
    FLICKER_PATCH,
    HOLE,
    NEAR_BLOCK,
    SoftwareCamera,
    d435_sensor,
)
from realsense_cli.errors import InvalidProfile, InvalidValue, NoFrames
from realsense_cli.types import Image, Sensor
from tests.test_json import invoke_json, json_error

runner = CliRunner()

WIDTH, HEIGHT = 640, 480


def depth(*args: str) -> dict:
    return invoke_json("depth", "--warmup", "0", *args)


def test_pixel_reports_its_depth_and_samples(feed):
    result = depth(str(NEAR_BLOCK.x), str(NEAR_BLOCK.y), "--frames", "3")
    assert result == {
        "profiles": [
            {
                "stream": "Depth",
                "width": WIDTH,
                "height": HEIGHT,
                "fps": result["profiles"][0]["fps"],
                "format": "Z16",
                "index": 0,
            }
        ],
        "frames": 3,
        "depth_scale": 0.001,
        "depth": DEPTH_NEAR / 1000,
        "pixel": {"x": NEAR_BLOCK.x, "y": NEAR_BLOCK.y, "samples": 3},
    }


def test_pixel_with_depth_in_alternate_frames_counts_only_those(feed):
    result = depth(str(FLICKER_PATCH.x), str(FLICKER_PATCH.y), "--frames", "4")
    assert result["depth"] == DEPTH_FLICKER / 1000
    assert result["pixel"]["samples"] == 2


def test_pixel_without_depth_is_an_answer(feed):
    result = depth(str(HOLE.x), str(HOLE.y), "--frames", "2")
    assert result["depth"] is None
    assert result["pixel"]["samples"] == 0


def test_depth_follows_the_depth_units(driver, feed):
    driver.set_control_values(Sensor.STEREO_MODULE, {"depth_units": 0.0001})
    result = depth("0", "0", "--frames", "1")
    assert result["depth_scale"] == 0.0001
    assert result["depth"] == DEPTH_BACKGROUND / 10000


def test_region_reports_statistics_over_its_valid_pixels(feed):
    # half background, half the near block
    region = Region(NEAR_BLOCK.x - 10, NEAR_BLOCK.y, 20, 10)
    result = depth("--roi", str(region), "--frames", "2")
    assert result["depth"] == 1.5
    assert result["region"] == {
        "x": region.x,
        "y": region.y,
        "width": 20,
        "height": 10,
        "pixels": 200,
        "valid_pixels": 200,
        "fill_rate": 1.0,
        "min": DEPTH_NEAR / 1000,
        "max": DEPTH_BACKGROUND / 1000,
        "mean": 1.5,
        "median": 1.5,
        "stddev": 0.5,
    }


def test_whole_image_by_default(feed):
    result = depth("--frames", "2")
    region = result["region"]
    near = NEAR_BLOCK.width * NEAR_BLOCK.height
    flicker = FLICKER_PATCH.width * FLICKER_PATCH.height
    valid = WIDTH * HEIGHT - HOLE.width * HOLE.height
    background = valid - near - flicker
    mean = (near * DEPTH_NEAR + flicker * DEPTH_FLICKER + background * DEPTH_BACKGROUND) / valid
    assert (region["x"], region["y"], region["width"], region["height"]) == (0, 0, 640, 480)
    assert (region["pixels"], region["valid_pixels"]) == (WIDTH * HEIGHT, valid)
    assert region["fill_rate"] == round(valid / (WIDTH * HEIGHT), 4)
    assert region["mean"] == round(mean / 1000, 4)
    assert result["depth"] == region["median"] == DEPTH_BACKGROUND / 1000


def test_region_without_depth_has_null_statistics(feed):
    result = depth("--roi", str(Region(HOLE.x, HOLE.y, 4, 4)), "--frames", "1")
    assert result["depth"] is None
    assert result["region"] == {
        "x": HOLE.x,
        "y": HOLE.y,
        "width": 4,
        "height": 4,
        "pixels": 16,
        "valid_pixels": 0,
        "fill_rate": 0.0,
        **dict.fromkeys(("min", "max", "mean", "median", "stddev")),
    }


def test_table_leads_with_the_depth(feed):
    result = runner.invoke(app, ["depth", "--warmup", "0", "--frames", "1"])
    assert result.exit_code == 0, result.output
    rows = [line.split() for line in result.stdout.splitlines() if line.strip()]
    assert rows[1] == ["Depth", "2.000", "m"]
    assert ["Fill", "rate", "98.4%"] in rows
    assert "Warming up" in result.stderr
    assert "Stopping all streams" in result.stderr


def test_pixel_table_shows_samples(feed):
    result = runner.invoke(app, ["depth", "0", "0", "--warmup", "0", "--frames", "2"])
    assert result.exit_code == 0, result.output
    assert "2 of 2 frames" in result.stdout


@pytest.mark.parametrize(
    "args",
    [["640", "0"], ["0", "480"], ["--roi", "600,0,41,10"], ["--roi", "-1,0,10,10"]],
)
def test_outside_the_depth_image_fails(feed, args):
    result = runner.invoke(app, ["--json", "depth", "--warmup", "0", *args])
    assert result.exit_code == InvalidValue.exit_code, result.output
    assert result.stdout == ""
    # after "Stopping all streams": the image size is known once the depth stream started
    error = json.loads(result.stderr.splitlines()[-1])["error"]
    assert "640x480 depth image" in error["message"]


@pytest.mark.parametrize(
    "args",
    [
        ["--roi", "1,2,3"],
        ["--roi", "a,b,c,d"],
        ["--roi", "0,0,0,10"],
        ["5"],
        ["1", "2", "--roi", "0,0,1,1"],
    ],
)
def test_usage_errors(driver, args):
    result = runner.invoke(app, ["--json", "depth", *args])
    assert json_error(result, 2)["type"] == "UsageError"


def test_no_frames_fails(driver, monkeypatch):
    monkeypatch.setattr("realsense_cli.commands.capture.FRAME_TIMEOUT", 0.1)
    result = runner.invoke(app, ["--json", "depth", "--warmup", "0"])
    assert result.exit_code == NoFrames.exit_code, result.output
    error = json.loads(result.stderr.splitlines()[-1])["error"]
    assert "No frames arrived from Depth" in error["message"]


def z16(*depths: int) -> Image:
    """A one-row Z16 image"""
    return Image(len(depths), 1, "z16", array("H", depths).tobytes())


def test_median_of_an_even_count_is_the_mean_of_the_middle_two():
    assert median([1, 2, 4, 10]) == 3.0
    assert median([1, 2, 4]) == 2.0


def test_region_stats_combine_each_pixels_non_zero_samples():
    frames = [z16(10, 0, 0, 7), z16(20, 0, 5, 7), z16(60, 0, 0, 7)]
    stats = region_stats(frames, Region(0, 0, 4, 1))
    # pixels: median(10, 20, 60) = 20, none, 5, 7
    assert stats.valid_pixels == 3
    assert stats.fill_rate == 0.75
    assert (stats.min, stats.max, stats.median) == (5, 20, 7)
    assert stats.mean == pytest.approx(32 / 3)


def test_device_without_depth_sensor_fails(make_driver):
    make_driver(SoftwareCamera(D435, [d435_sensor(Sensor.RGB_CAMERA)]))
    result = runner.invoke(app, ["--json", "depth"])
    assert json_error(result, InvalidProfile.exit_code)["message"] == (
        "The device has no depth sensor"
    )
