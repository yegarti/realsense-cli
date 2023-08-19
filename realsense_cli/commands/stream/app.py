from typing import Annotated, Optional

import typer
from rich.progress import Progress, SpinnerColumn, TextColumn

from realsense_cli.driver import get_driver
from realsense_cli.model import CliSensor, CliStream
from realsense_cli.utils.driver import prepare_profiles
from realsense_cli.utils.rich import list_profiles

stream_app = typer.Typer(help="Stream options", no_args_is_help=True)


@stream_app.command(name="list", help="List supported streams for given SENSOR")
def stream_list(
    sensor: Annotated[
        CliSensor, typer.Argument(help="Sensor to query for streams", show_default=False)
    ],
) -> None:
    driver = get_driver()
    profiles = driver.list_streams(sensor.rs_enum)
    list_profiles(profiles, sensor.rs_enum)


@stream_app.command(name="play", help="Play streams")
def stream_play(
    streams: Annotated[
        list[CliStream], typer.Argument(help="steams to play", show_default=False)
    ],
    fps: Annotated[
        Optional[int],
        typer.Option("-f", "--fps", help="use specific FPS for all video streams"),
    ] = None,
    res: Annotated[
        Optional[str],
        typer.Option(
            "-r", "--resolution", help="use specific resolution for all video streams"
        ),
    ] = None,
):
    driver = get_driver()
    if len(set(streams)) < len(streams):
        print("Duplicated streams are not allowed")
        raise typer.Abort()

    rs_streams = [stream.rs_enum for stream in streams]

    profiles = prepare_profiles(rs_streams)
    print(f"Streaming profiles: {[str(p) for p in profiles]}")

    driver.play(profiles)
    try:
        import time

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            transient=False,
        ) as progress:
            progress.add_task(description="Streaming...", total=None)
            while True:
                time.sleep(1)
    finally:
        driver.stop()
