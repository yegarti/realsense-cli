from typing import Annotated, Optional

import typer
from rich.live import Live

from realsense_cli.driver import get_driver
from realsense_cli.stream_view import StreamView
from realsense_cli.model import CliSensor, CliStream, Profile
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
        Optional[list[CliStream]],
        typer.Argument(
            help="Steams to play, default would stream all possible streams", show_default=False
        ),
    ] = None,
):
    driver = get_driver()
    if not streams:
        streams = []

    if len(set(streams)) < len(streams):
        print("Duplicated streams are not allowed")
        raise typer.Abort()

    rs_streams = [stream.rs_enum for stream in streams]
    profiles = [Profile.new(stream) for stream in rs_streams]

    view = StreamView(rs_streams)
    driver.play(profiles)
    try:
        with Live(view, refresh_per_second=30) as live:
            while True:
                frameset = driver.wait_for_frameset()
                view.update(frameset)
    finally:
        print("Stopping all streams")
        driver.stop()
