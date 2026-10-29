from pathlib import Path
from typing import Annotated, Any

import typer

from realsense_cli.commands.capture import profile_payload
from realsense_cli.commands.config import read_available
from realsense_cli.commands.info import calibration_payload
from realsense_cli.driver import open_recording
from realsense_cli.printer import emit, recording_details
from realsense_cli.recording import check_recording

bag_app = typer.Typer(help="Inspect recordings", no_args_is_help=True)


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
