import os
import time
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

import typer
from loguru import logger

from realsense_cli.commands.capture import profile_payload
from realsense_cli.commands.info import calibration_payload
from realsense_cli.commands.stream import _STREAM_ALIASES_STR, count_frames
from realsense_cli.console import err_console
from realsense_cli.driver import open_recording
from realsense_cli.errors import InvalidValue, NoFrames, with_bandwidth_hint
from realsense_cli.printer import emit, recording_details, recording_summary
from realsense_cli.recording import check_recording
from realsense_cli.restore import read_available
from realsense_cli.session import json_output, require_device
from realsense_cli.types import FrameSet, Profile
from realsense_cli.utils import find_origin_sensor, new_path

bag_app = typer.Typer(help="Record and inspect recordings", no_args_is_help=True)


@bag_app.command(
    name="info", help="Show what a recording holds: camera info, streams and frame counts"
)
def bag_info(
    ctx: typer.Context,
    recording: Annotated[
        Path,
        typer.Argument(metavar="RECORDING", exists=True, dir_okay=False, show_default=False),
    ],
    show_calibration: Annotated[
        bool,
        typer.Option(
            "--calibration/", help="Also show the recorded streams' intrinsics and extrinsics"
        ),
    ] = False,
    show_controls: Annotated[
        bool,
        typer.Option(
            "--controls/", help="Also show each sensor's control values at the recording start"
        ),
    ] = False,
):
    path = recording.absolute()
    # before the SDK opens the file: its playback hangs on a recording with no frames
    frames = check_recording(path)
    driver, duration = open_recording(path)
    sensors = driver.sensors
    streams = [
        {"sensor": sensor}
        | profile_payload(profile)
        | {"frames": frames.get((profile.stream, profile.index), 0)}
        for sensor in sensors
        for profile in driver.list_streams(sensor)
    ]
    payload: dict[str, Any] = {
        "path": str(path),
        "duration": duration,
        "device": driver.camera_info(),
        "sensors": sensors,
        "streams": streams,
    }
    calibration = None
    if show_calibration:
        # a playback device offers only the recorded profiles
        calibration = driver.calibration()
        payload |= calibration_payload(calibration)
    if show_controls:
        # the playback device holds each control's first recorded value until it plays, and
        # it never does here: later changes stay unseen
        payload["controls"] = []
        for sensor in sensors:
            controls = [opt.name for opt in driver.list_controls(sensor)]
            values, _ = read_available(driver, sensor, controls)
            if values:
                payload["controls"].append({"sensor": sensor, "values": values})
    emit(ctx, payload, lambda: recording_details(payload, calibration))


@bag_app.command(
    name="record",
    short_help="Record a run to a .db3 recording",
    help=f"""
    Record streams to a recording, a rosbag2 .db3 file that `rs bag info` and librealsense
    play back\n
    \n
    Profiles use the `stream play` syntax (e.g. depth-640x480-30-z16); without any, every
    stream the device starts by default is recorded. Stream aliases: {_STREAM_ALIASES_STR}\n
    \n
    Runs until Ctrl-C, or with --frames/--duration stops on its own. Ctrl-C ends any
    recording normally, keeping the file. A stream that sends no frames for 3 seconds fails
    the run, and a failed run deletes its file.\n
    """,
)
def bag_record(
    ctx: typer.Context,
    profiles: Annotated[
        list[Profile] | None,
        typer.Argument(
            help="Profiles to record", show_default=False, parser=Profile.from_string
        ),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option(
            "-o",
            "--output",
            help="The .db3 file to write (default: ./rs-recording-<timestamp>.db3)",
            show_default=False,
        ),
    ] = None,
    force: Annotated[
        bool, typer.Option("--force", "-f", help="Overwrite the output file if it exists")
    ] = False,
    frames: Annotated[
        int | None,
        typer.Option(
            "--frames",
            min=1,
            help="Stop once every stream has N frames",
            show_default=False,
        ),
    ] = None,
    duration: Annotated[
        float | None,
        typer.Option("--duration", help="Stop after S seconds", show_default=False),
    ] = None,
) -> None:
    if duration is not None and duration <= 0:
        raise typer.BadParameter("must be more than 0 seconds", param_hint="'--duration'")
    if json_output(ctx) and frames is None and duration is None:
        raise typer.BadParameter(
            "needs --frames or --duration: without them bag record runs until interrupted",
            param_hint="'--json'",
        )
    path = _output_path(output, force)
    driver = require_device(ctx)
    path.parent.mkdir(parents=True, exist_ok=True)
    # the SDK takes only a lowercase `.db3`: another case is written under a temporary name
    writing = (
        path if path.suffix == ".db3" else path.with_name(f".{path.name}.{os.getpid()}.db3")
    )

    started = driver.record(writing, profiles or [])
    counts = dict.fromkeys((profile.stream for profile in started), 0)
    first_frame: list[float] = []
    interrupted = False

    def on_frameset(_: FrameSet) -> None:
        if not first_frame:
            first_frame.append(time.monotonic())

    try:
        try:
            if not json_output(ctx):
                err_console.print(f"Recording to {path} (Ctrl-C to stop)", soft_wrap=True)
            count_frames(driver, counts, frames, duration, on_frameset)
        except KeyboardInterrupt:
            logger.info("recording interrupted")
            interrupted = True
        finally:
            stopped = time.monotonic()
            # releases the recorder, which closes the file
            driver.stop()
        if not any(counts.values()):
            message = "The recording stopped before the first frame arrived"
            # stopped with Ctrl-C, the run may just have been short
            raise NoFrames(message if interrupted else with_bandwidth_hint(message, counts))
        recorded = check_recording(writing)
    except BaseException:
        # a failed run leaves no file; one without frames would hang librealsense's playback
        writing.unlink(missing_ok=True)
        raise
    if writing != path:
        writing.replace(path)

    origins = find_origin_sensor(
        {sensor: driver.list_streams(sensor) for sensor in driver.sensors}
    )
    payload = {
        "path": str(path),
        "duration": round(stopped - first_frame[0], 3) if first_frame else 0.0,
        "size": path.stat().st_size,
        "streams": [
            {"sensor": origins.get(profile.stream, "")}
            | profile_payload(profile)
            | {"frames": recorded.get((profile.stream, profile.index), 0)}
            for profile in started
        ],
    }
    emit(ctx, payload, lambda: recording_summary(payload))


def _output_path(output: Path | None, force: bool) -> Path:
    """
    The absolute path to record to: OUTPUT, or a new `rs-recording-<timestamp>.db3`. Raises
    `InvalidValue` for a name that isn't `.db3`, and for an existing file without FORCE
    """
    if output is None:
        output = new_path(f"rs-recording-{datetime.now():%Y%m%d-%H%M%S}", ".db3")
    path = output.absolute()
    if path.suffix.lower() != ".db3":
        raise InvalidValue(f"Recordings are .db3 files: '{path}' doesn't end in .db3")
    if path.is_dir():
        raise InvalidValue(f"Output '{path}' is a directory")
    if path.exists() and not force:
        raise InvalidValue(f"'{path}' already exists; pass --force to overwrite it")
    return path
