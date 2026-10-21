import json
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

import typer

from realsense_cli import png
from realsense_cli.console import err_console
from realsense_cli.driver.base import DriverProtocol
from realsense_cli.errors import InvalidProfile, InvalidValue, NoFrames
from realsense_cli.printer import emit, list_paths
from realsense_cli.session import require_device
from realsense_cli.types import _STREAM_ALIASES, FrameSet, Profile, Stream

# The format a stream is captured in when its profile leaves the format unset
_DEFAULT_FORMATS: dict[str, str] = {
    Stream.DEPTH: "z16",
    Stream.INFRARED: "y8",
    Stream.INFRARED2: "y8",
    Stream.COLOR: "rgb8",
}

_FILE_STEMS: dict[str, str] = {stream: alias for alias, stream in _STREAM_ALIASES.items()}

# Seconds a capture waits for a stream's next frame before failing, as a bounded stream play
FRAME_TIMEOUT = 3.0


def rs_capture(
    ctx: typer.Context,
    profiles: Annotated[
        list[Profile] | None,
        typer.Argument(
            help=(
                "Profiles to capture, in the `stream play` syntax (default: depth and color). "
                "Stream aliases: " + ", ".join(_FILE_STEMS[s] for s in _DEFAULT_FORMATS)
            ),
            show_default=False,
            parser=Profile.from_string,
        ),
    ] = None,
    frames: Annotated[int, typer.Option("--frames", min=1, help="Framesets to save")] = 1,
    warmup: Annotated[
        float,
        typer.Option(
            "--warmup",
            min=0,
            help="Seconds of frames to discard first, while auto-exposure settles",
        ),
    ] = 1.0,
    output: Annotated[
        Path | None,
        typer.Option(
            "-o",
            "--output",
            help="Directory to write into (default: ./rs-capture-<timestamp>)",
            show_default=False,
        ),
    ] = None,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            "-f",
            help="Write into a directory that holds files, overwriting any of them",
        ),
    ] = False,
) -> None:
    """
    Capture framesets to files, to open afterwards

    Discards the frames of the first --warmup seconds, then saves --frames framesets.

    Color and infrared are saved as 8-bit PNGs, depth as raw 16-bit and colorized PNGs.

    A capture.json sidecar holds the profiles, frame metadata and depth scale.
    """
    if output is None:
        output = _new_directory(f"rs-capture-{datetime.now():%Y%m%d-%H%M%S}")
    output = output.absolute()
    if output.exists() and not output.is_dir():
        raise InvalidValue(f"Output '{output}' is not a directory")
    if output.is_dir() and any(output.iterdir()) and not force:
        raise InvalidValue(
            f"Output directory '{output}' is not empty; pass --force to write into it anyway"
        )
    driver = require_device(ctx)
    profiles = [
        _with_format(p) for p in profiles or [Profile(Stream.DEPTH), Profile(Stream.COLOR)]
    ]

    started = driver.play(profiles)
    try:
        framesets = _collect(driver, [p.stream for p in started], frames, warmup)
    finally:
        err_console.print("Stopping all streams")
        driver.stop()

    output.mkdir(parents=True, exist_ok=True)
    files, frames_meta = _write(output, framesets)
    camera_info = driver.camera_info()
    sidecar = {
        "device": {"name": camera_info["name"], "serial": camera_info["serial_number"]},
        "depth_scale": driver.depth_scale(),
        "profiles": [
            {
                "stream": p.stream,
                "width": p.resolution.width,
                "height": p.resolution.height,
                "fps": p.fps,
                "format": p.format.upper(),
                "index": p.index,
            }
            for p in started
        ],
        "framesets": frames_meta,
    }
    (output / "capture.json").write_text(json.dumps(sidecar, indent=2) + "\n")
    paths = [str(output / name) for name in [*files, "capture.json"]]
    emit(ctx, {"directory": str(output), "files": paths}, lambda: list_paths(paths))


def _new_directory(name: str) -> Path:
    """
    ./NAME, or ./NAME-2, ./NAME-3 ... when it is taken, e.g. by a capture in the same second
    """
    path, n = Path(name), 1
    while path.exists():
        n += 1
        path = Path(f"{name}-{n}")
    return path


def _with_format(profile: Profile) -> Profile:
    """
    PROFILE, in the stream's default capture format when it leaves the format unset
    """
    if profile.format != "any":
        if profile.format.lower() not in png.FORMATS:
            raise InvalidProfile(
                f"Can't capture '{profile}': capture saves formats "
                f"{', '.join(f.upper() for f in png.FORMATS)}"
            )
        return profile
    if profile.stream not in _DEFAULT_FORMATS:
        streams = ", ".join(_FILE_STEMS[s] for s in _DEFAULT_FORMATS)
        raise InvalidProfile(
            f"Can't capture '{profile.stream}': capture saves video streams: {streams}"
        )
    return replace(profile, format=_DEFAULT_FORMATS[profile.stream])


def _collect(
    driver: DriverProtocol, streams: list[str], frames: int, warmup: float
) -> list[FrameSet]:
    """
    FRAMES framesets holding a new frame of each of STREAMS, after discarding the frames of
    the first WARMUP seconds. A stream the next frameset still waits for that sends nothing for
    FRAME_TIMEOUT seconds fails the capture
    """
    last_index: dict[str, int] = {}
    warm = time.monotonic() + warmup
    while (now := time.monotonic()) < warm:
        # the frame numbers seen, so a warmup frame handed out again later is not captured
        for stream, frame in (driver.wait_for_frameset(warm - now) or {}).items():
            last_index[stream] = frame.index

    framesets: list[FrameSet] = []
    pending: FrameSet = {}
    last_frame = dict.fromkeys(streams, time.monotonic())
    while len(framesets) < frames:
        now = time.monotonic()
        waiting = [s for s in streams if s not in pending]
        stalled = [s for s in waiting if now - last_frame[s] >= FRAME_TIMEOUT]
        if stalled:
            raise NoFrames(
                f"No frames arrived from {', '.join(stalled)} within {FRAME_TIMEOUT:g}s. "
                f"Framesets captured: {len(framesets)} of {frames}"
            )
        # wake up in time to notice the first stall
        timeout = min(last_frame[s] for s in waiting) + FRAME_TIMEOUT - now
        frameset = driver.wait_for_frameset(timeout, images=True)
        if frameset is None:
            continue
        now = time.monotonic()
        for stream, frame in frameset.items():
            # the pipeline can hand out a slower stream's last frame again in later framesets
            if last_index.get(stream) == frame.index:
                continue
            last_index[stream] = frame.index
            last_frame[stream] = now
            pending[stream] = frame
        if all(stream in pending for stream in streams):
            framesets.append({stream: pending[stream] for stream in streams})
            pending = {}
    return framesets


def _write(output: Path, framesets: list[FrameSet]) -> tuple[list[str], list[dict[str, Any]]]:
    """
    Write FRAMESETS into OUTPUT; the file names written, and each frameset's sidecar entry
    """
    # numbers padded to one width, so the files sort in frameset order
    width = len(str(len(framesets) - 1))
    files: list[str] = []
    entries = []
    for i, frameset in enumerate(framesets):
        frame_entries = []
        for stream, frame in frameset.items():
            stem = f"{_file_stem(stream)}-{i:0{width}d}"
            written = []
            for name, image in ((stem, frame.image), (f"{stem}-colorized", frame.colorized)):
                if image is None:
                    continue
                (output / f"{name}.png").write_bytes(png.encode(image))
                written.append(f"{name}.png")
            files += written
            frame_entries.append(
                {
                    "stream": stream,
                    "frame_number": frame.index,
                    "timestamp": frame.timestamp,
                    "metadata": frame.metadata,
                    "files": written,
                }
            )
        entries.append({"frames": frame_entries})
    return files, entries


def _file_stem(stream: str) -> str:
    return _FILE_STEMS.get(stream, stream.lower().replace(" ", "-"))
