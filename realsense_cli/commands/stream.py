from typing import Annotated, Optional

import typer
from loguru import logger
from rich.live import Live

from realsense_cli.driver import get_driver
from realsense_cli.stream_view import StreamView
from realsense_cli.types import CliSensor, CliStream, Profile, Resolution
from realsense_cli.utils.rich import list_profiles

stream_app = typer.Typer(help="Stream options", no_args_is_help=True)


@stream_app.command(name="list", help="List supported streams for given SENSOR")
def stream_list(
    sensors: Annotated[
        Optional[list[CliSensor]],
        typer.Argument(help="Sensor to query for streams", show_default=False),
    ] = None,
) -> None:
    driver = get_driver()
    if sensors:
        rs_sensors = [sensor.rs_enum for sensor in sensors]
    else:
        rs_sensors = driver.sensors

    profiles = []
    for sensor in rs_sensors:
        profiles.extend(driver.list_streams(sensor))
    list_profiles(profiles)


@stream_app.command(name="play", help="Play streams")
def stream_play(
    streams: Annotated[
        Optional[list[CliStream]],
        typer.Argument(
            help="Steams to play, no argument would stream all possible streams at pre-configured settings",
            show_default=False,
        ),
    ] = None,
    fps: Annotated[
        int, typer.Option("--fps", "-f", help="FPS to use for streams selected")
    ] = 0,
    resolution: Annotated[
        Resolution,
        typer.Option(
        "--res",
            "-r",
            help="Resolution to use for streams selected, example: 640x480",
            parser=Resolution.from_string,
        ),
    ] = "0x0",
):
    driver = get_driver()
    if not streams:
        streams = []

    if len(set(streams)) < len(streams):
        print("Duplicated streams are not allowed")
        raise typer.Abort()

    profiles = []
    for stream in streams:
        profile = Profile(
            stream=stream.rs_enum,
            resolution=resolution,
            fps=fps,
        )
        profiles.append(profile)

    view = StreamView([stream.rs_enum for stream in streams])
    driver.play(profiles)
    try:
        with Live(view, refresh_per_second=30) as live:
            while True:
                try:
                    frameset = driver.wait_for_frameset()
                    view.update(frameset)
                except RuntimeError:
                    logger.warning("Frames didn't arrive until timeout")
    finally:
        print("Stopping all streams")
        driver.stop()
