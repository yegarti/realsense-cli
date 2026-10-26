import json
import time
from array import array
from datetime import datetime
from itertools import count
from pathlib import Path

import numpy
import pytest
from PIL import Image
from typer.testing import CliRunner

from realsense_cli.cli import app
from realsense_cli.driver.software import D435, SensorSpec, SoftwareCamera, pixels
from realsense_cli.errors import InvalidProfile, InvalidValue, NoFrames
from realsense_cli.types import Frame, Profile, Resolution, Sensor, Stream
from tests.test_json import invoke_json, json_error

runner = CliRunner()


def test_defaults_capture_depth_and_color_into_timestamped_directory(
    feed, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    result = invoke_json("capture")
    [directory] = tmp_path.iterdir()
    assert directory.name.startswith("rs-capture-")
    assert result["directory"] == str(directory)
    assert sorted(Path(f).name for f in result["files"]) == [
        "capture.json",
        "color-0.png",
        "depth-0-colorized.png",
        "depth-0.png",
    ]
    assert sorted(result["files"]) == sorted(str(p) for p in directory.iterdir())
    assert Image.open(directory / "depth-0.png").mode == "I;16"
    assert Image.open(directory / "depth-0-colorized.png").mode == "RGB"
    assert Image.open(directory / "color-0.png").mode == "RGB"
    assert json.loads((directory / "capture.json").read_text())["device"]["serial"]


def test_raw_depth_png_round_trips_to_the_pushed_values(feed, tmp_path):
    invoke_json("capture", "depth", "--warmup", "0", "-o", str(tmp_path))
    sidecar = json.loads((tmp_path / "capture.json").read_text())
    [[depth]] = [frameset["frames"] for frameset in sidecar["framesets"]]
    pushed = array("H", pixels(640 * 480 * 2, depth["frame_number"]))
    with Image.open(tmp_path / "depth-0.png") as png:
        assert png.size == (640, 480)
        assert list(png.get_flattened_data()) == list(pushed)


def test_profiles_and_frames_save_a_file_per_stream_and_frameset(feed, tmp_path):
    out = tmp_path / "new" / "dir"
    result = invoke_json(
        "capture",
        "infrared",
        "color-640x480-30",
        "--frames",
        "3",
        "--warmup",
        "0",
        "-o",
        str(out),
    )
    assert result["directory"] == str(out)
    assert sorted(p.name for p in out.iterdir()) == [
        "capture.json",
        *(f"color-{i}.png" for i in range(3)),
        *(f"infrared-{i}.png" for i in range(3)),
    ]
    with Image.open(out / "infrared-2.png") as png:
        assert png.mode == "L"
    sidecar = json.loads((out / "capture.json").read_text())
    assert [p["stream"] for p in sidecar["profiles"]] == ["Infrared 1", "Color"]
    assert sidecar["profiles"][1]["fps"] == 30
    # each frameset holds new frames
    for stream in ("Infrared 1", "Color"):
        numbers = [
            frame["frame_number"]
            for frameset in sidecar["framesets"]
            for frame in frameset["frames"]
            if frame["stream"] == stream
        ]
        assert len(numbers) == 3
        assert numbers == sorted(set(numbers))


def test_sidecar_holds_profiles_frame_metadata_depth_scale_and_serial(feed, tmp_path):
    invoke_json(
        "capture", "depth-640x480-30", "--frames", "2", "--warmup", "0", "-o", str(tmp_path)
    )
    sidecar = json.loads((tmp_path / "capture.json").read_text())
    assert sidecar == {
        "device": {"name": "Intel RealSense D435", "serial": "012345678"},
        "depth_scale": 0.001,
        "profiles": [
            {
                "stream": "Depth",
                "width": 640,
                "height": 480,
                "fps": 30,
                "format": "Z16",
                "index": 0,
            }
        ],
        "framesets": [
            {
                "frames": [
                    {
                        "stream": "Depth",
                        "frame_number": 0,
                        "timestamp": 0.0,
                        # the SDK works out the actual FPS from the frames before
                        "metadata": {},
                        "files": ["depth-0.png", "depth-0-colorized.png"],
                    }
                ]
            },
            {
                "frames": [
                    {
                        "stream": "Depth",
                        "frame_number": 1,
                        "timestamp": 1000 / 30,
                        "metadata": {"actual_fps": pytest.approx(30000, abs=1)},
                        "files": ["depth-1.png", "depth-1-colorized.png"],
                    }
                ]
            },
        ],
    }


def test_warmup_discards_the_first_frames(feed, tmp_path):
    started = time.monotonic()
    invoke_json("capture", "depth", "--warmup", "0.2", "-o", str(tmp_path))
    assert time.monotonic() - started >= 0.2
    sidecar = json.loads((tmp_path / "capture.json").read_text())
    [[depth]] = [frameset["frames"] for frameset in sidecar["framesets"]]
    assert depth["frame_number"] > 0


def test_requested_stream_without_frames_fails_and_writes_nothing(feed, tmp_path, monkeypatch):
    monkeypatch.setattr("realsense_cli.commands.capture.FRAME_TIMEOUT", 0.1)
    feed.streams = ["Depth"]
    out = tmp_path / "out"
    result = runner.invoke(
        app, ["--json", "capture", "depth", "color", "--warmup", "0", "-o", str(out)]
    )
    assert result.exit_code == NoFrames.exit_code, result.output
    assert result.stdout == ""
    error = json.loads(result.stderr.splitlines()[-1])["error"]
    assert "No frames arrived from Color within 0.1s" in error["message"]
    assert not out.exists()


def test_non_empty_output_directory_fails_without_force(feed, tmp_path):
    (tmp_path / "old.png").write_bytes(b"old")
    result = runner.invoke(app, ["--json", "capture", "depth", "-o", str(tmp_path)])
    error = json_error(result, InvalidValue.exit_code)
    assert "--force" in error["message"]
    assert [p.name for p in tmp_path.iterdir()] == ["old.png"]


def test_force_writes_into_non_empty_directory(feed, tmp_path):
    (tmp_path / "depth-0.png").write_bytes(b"old")
    (tmp_path / "notes.txt").write_text("keep")
    invoke_json("capture", "depth", "--warmup", "0", "--force", "-o", str(tmp_path))
    with Image.open(tmp_path / "depth-0.png") as png:
        assert png.mode == "I;16"
    assert (tmp_path / "notes.txt").read_text() == "keep"


def test_prints_the_written_paths(feed, tmp_path):
    result = runner.invoke(app, ["capture", "depth", "--warmup", "0", "-o", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines() == [
        str(tmp_path / name)
        for name in ("depth-0.png", "depth-0-colorized.png", "capture.json")
    ]


@pytest.mark.parametrize(
    "profile, hint",
    [
        ("gyro", "video streams"),
        ("color-640x480-30-yuyv", "formats"),
    ],
)
def test_profile_capture_cannot_save_fails(driver, tmp_path, profile, hint):
    result = runner.invoke(app, ["--json", "capture", profile, "-o", str(tmp_path / "out")])
    error = json_error(result, InvalidProfile.exit_code)
    assert hint in error["message"]


def test_negative_warmup_is_usage_error(driver, tmp_path):
    result = runner.invoke(app, ["--json", "capture", "--warmup", "-1", "-o", str(tmp_path)])
    assert result.exit_code == 2, result.output
    assert "--warmup" in json.loads(result.stderr)["error"]["message"]


def _bgr_camera() -> SoftwareCamera:
    color = Profile(Stream.COLOR, Resolution(4, 2), 30, "bgr8", 0)
    return SoftwareCamera(D435, [SensorSpec(Sensor.RGB_CAMERA, [color])])


@pytest.mark.parametrize("camera", [_bgr_camera], indirect=True)
def test_bgr_color_is_saved_as_rgb(feed, tmp_path):
    invoke_json("capture", "color-0x0-0-bgr8", "--warmup", "0", "-o", str(tmp_path))
    with Image.open(tmp_path / "color-0.png") as png:
        # frame 0 is pushed as the bytes 0, 1, 2, ...: blue 0, green 1, red 2 in the first pixel
        assert png.mode == "RGB"
        assert png.getpixel((0, 0)) == (2, 1, 0)
        assert png.getpixel((1, 0)) == (5, 4, 3)


def test_frame_repeated_from_warmup_is_not_captured(driver, monkeypatch, tmp_path):
    """The pipeline can hand out a slower stream's last frame again in later framesets"""
    depth = Profile(Stream.DEPTH, Resolution(640, 480), 30, "z16", 0)
    captured = count(1)

    def repeats_warmup_frame_once(timeout: float = 3.0, images: bool = False):
        # every warmup wait, and the first wait after it, hands out frame 0
        index = next(captured) - 1 if images else 0
        return {Stream.DEPTH: Frame(depth, timestamp=index, index=index, metadata={})}

    monkeypatch.setattr(driver, "wait_for_frameset", repeats_warmup_frame_once)
    invoke_json("capture", "depth", "--warmup", "0.05", "-o", str(tmp_path))
    sidecar = json.loads((tmp_path / "capture.json").read_text())
    [[frame]] = [frameset["frames"] for frameset in sidecar["framesets"]]
    assert frame["frame_number"] == 1


class _FixedNow(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 10, 21, 14, 30, 5)


def test_default_directory_of_a_capture_in_the_same_second_gets_a_suffix(
    feed, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("realsense_cli.commands.capture.datetime", _FixedNow)
    first = invoke_json("capture", "depth", "--warmup", "0")["directory"]
    second = invoke_json("capture", "depth", "--warmup", "0")["directory"]
    assert Path(first).name == "rs-capture-20261021-143005"
    assert Path(second).name == "rs-capture-20261021-143005-2"


def test_npy_alone_writes_arrays_of_the_pushed_values_and_no_png(feed, tmp_path):
    result = invoke_json(
        "capture",
        "depth",
        "infrared",
        "color",
        "--format",
        "npy",
        "--warmup",
        "0",
        "-o",
        str(tmp_path),
    )
    assert [Path(f).name for f in result["files"]] == [
        "depth-0.npy",
        "infrared-0.npy",
        "color-0.npy",
        "capture.json",
    ]
    sidecar = json.loads((tmp_path / "capture.json").read_text())
    [frames] = [frameset["frames"] for frameset in sidecar["framesets"]]
    numbers = {frame["stream"]: frame["frame_number"] for frame in frames}
    assert [frame["files"] for frame in frames] == [
        ["depth-0.npy"],
        ["infrared-0.npy"],
        ["color-0.npy"],
    ]

    depth = numpy.load(tmp_path / "depth-0.npy")
    assert (depth.dtype, depth.shape) == (numpy.uint16, (480, 640))
    pushed = array("H", pixels(640 * 480 * 2, numbers["Depth"]))
    assert depth.ravel().tolist() == list(pushed)

    infrared = numpy.load(tmp_path / "infrared-0.npy")
    assert (infrared.dtype, infrared.shape) == (numpy.uint8, (480, 640))
    assert infrared.tobytes() == pixels(640 * 480, numbers["Infrared 1"])

    color = numpy.load(tmp_path / "color-0.npy")
    assert (color.dtype, color.shape) == (numpy.uint8, (480, 640, 3))
    assert color.tobytes() == pixels(640 * 480 * 3, numbers["Color"])


def test_several_file_formats_write_each_once_per_frame(feed, tmp_path):
    result = invoke_json(
        "capture",
        "depth",
        "--format",
        "npy",
        "--format",
        "png",
        "--format",
        "npy",
        "--frames",
        "2",
        "--warmup",
        "0",
        "-o",
        str(tmp_path),
    )
    expected = [
        f"depth-{i}{suffix}" for i in range(2) for suffix in (".npy", ".png", "-colorized.png")
    ]
    assert [Path(f).name for f in result["files"]] == [*expected, "capture.json"]
    sidecar = json.loads((tmp_path / "capture.json").read_text())
    assert [frameset["frames"][0]["files"] for frameset in sidecar["framesets"]] == [
        expected[:3],
        expected[3:],
    ]
    with Image.open(tmp_path / "depth-1.png") as png:
        assert (
            list(png.get_flattened_data())
            == numpy.load(tmp_path / "depth-1.npy").ravel().tolist()
        )


@pytest.mark.parametrize("camera", [_bgr_camera], indirect=True)
def test_bgr_color_stays_bgr_in_npy(feed, tmp_path):
    invoke_json(
        "capture", "color-0x0-0-bgr8", "--format", "npy", "--warmup", "0", "-o", str(tmp_path)
    )
    color = numpy.load(tmp_path / "color-0.npy")
    assert (color.dtype, color.shape) == (numpy.uint8, (2, 4, 3))
    # frame 0 is pushed as the bytes 0, 1, 2, ...: blue 0, green 1, red 2 in the first pixel
    assert color[0, 0].tolist() == [0, 1, 2]
    assert color[0, 1].tolist() == [3, 4, 5]


def test_yuyv_is_saved_as_sent_in_npy(feed, tmp_path):
    invoke_json(
        "capture",
        "color-640x480-30-yuyv",
        "--format",
        "npy",
        "--warmup",
        "0",
        "-o",
        str(tmp_path),
    )
    sidecar = json.loads((tmp_path / "capture.json").read_text())
    [[color]] = [frameset["frames"] for frameset in sidecar["framesets"]]
    assert sidecar["profiles"][0]["format"] == "YUYV"
    assert color["files"] == ["color-0.npy"]
    yuyv = numpy.load(tmp_path / "color-0.npy")
    assert (yuyv.dtype, yuyv.shape) == (numpy.uint8, (480, 640, 2))
    assert yuyv.tobytes() == pixels(640 * 480 * 2, color["frame_number"])


def test_profile_a_file_format_cannot_hold_fails_naming_it(driver, tmp_path):
    result = runner.invoke(
        app,
        [
            "--json",
            "capture",
            "color-640x480-30-yuyv",
            "--format",
            "npy",
            "--format",
            "png",
            "-o",
            str(tmp_path / "out"),
        ],
    )
    error = json_error(result, InvalidProfile.exit_code)
    assert "as PNG" in error["message"]
    assert not (tmp_path / "out").exists()


def test_unknown_file_format_is_usage_error(driver, tmp_path):
    result = runner.invoke(app, ["--json", "capture", "--format", "z16", "-o", str(tmp_path)])
    assert result.exit_code == 2, result.output
    assert "--format" in json.loads(result.stderr)["error"]["message"]
