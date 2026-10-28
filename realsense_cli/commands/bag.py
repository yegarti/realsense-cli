from pathlib import Path
from typing import Annotated

import typer

from realsense_cli.commands.capture import profile_payload
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
    payload = {
        "path": str(path),
        "duration": duration,
        "device": driver.camera_info(),
        "sensors": sensors,
        "streams": streams,
    }
    emit(ctx, payload, lambda: recording_details(payload))
