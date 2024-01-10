from typing import Annotated, Optional

import typer
from loguru import logger
from rich.live import Live

from realsense_cli.driver import get_driver
from realsense_cli.stream_view import StreamView
from realsense_cli.types import CliSensor, CliStream, Profile, Resolution
from realsense_cli.printer import list_profiles

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


@stream_app.command(
    name="play",
    short_help="Play streams",
    help=f"""
                    Stream camera and show live view of basic data\n
                    If no profiles are provided will start all streams at default settings\n
                    \n
                    Profiles must be provided in the following syntax:\n
                    STREAM-RESOLUTION-FPS-FORMAT\n
                    the STREAM is mandatory, other parts can be omitted\n
                    \n
                    For example:\n
                    'depth' - stream depth stream at any FPS and resolution\n
                    'depth-0x0-30' - stream depth at any resolution, 30 fps\n
                    'color-640x480-0-rgb' - stream color at 640x480, any FPS, RGB format\n
                    \n
                    Stream names: {','.join([str(s.value) for s in CliStream])}\n
                    """,
)
def stream_play(
    profiles: Annotated[
        Optional[list[Profile]],
        typer.Argument(help="Profiles to play", show_default=False, parser=Profile.from_string),
    ] = None,
    api: Annotated[
        bool,
        typer.Option(
            "--pipe/--sensor",
            help="Stream method, high-level pipeline API or low-level sensor API",
        ),
    ] = True,
):
    driver = get_driver()
    logger.debug(f"stream {profiles}")
    if not profiles:
        profiles = []

    view = StreamView([profile.stream for profile in profiles])
    try:
        driver.play(profiles, pipeline=api)
    except RuntimeError as e:
        print(str(e))
        print("Requested profiles:")
        for profile in profiles:
            print(f"\t{profile}")
        raise typer.Exit(1)

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
