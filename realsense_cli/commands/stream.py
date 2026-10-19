from typing import Annotated

import typer
from loguru import logger
from rich.live import Live

from realsense_cli.console import console, err_console
from realsense_cli.printer import list_profiles
from realsense_cli.session import require_device
from realsense_cli.stream_view import StreamView
from realsense_cli.types import _STREAM_ALIASES, Profile, resolve_sensor_name

stream_app = typer.Typer(help="Stream options", no_args_is_help=True)

_STREAM_ALIASES_STR = ", ".join(_STREAM_ALIASES.keys())


@stream_app.command(name="list", help="List supported streams for given SENSOR")
def stream_list(
    ctx: typer.Context,
    sensors: Annotated[
        list[str] | None,
        typer.Argument(help="Sensor name or alias (depth, color, motion)", show_default=False),
    ] = None,
) -> None:
    driver = require_device(ctx)
    if sensors:
        rs_sensors = [resolve_sensor_name(s) for s in sensors]
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
                    Stream aliases: {_STREAM_ALIASES_STR}\n
                    """,
)
def stream_play(
    ctx: typer.Context,
    profiles: Annotated[
        list[Profile] | None,
        typer.Argument(help="Profiles to play", show_default=False, parser=Profile.from_string),
    ] = None,
    api: Annotated[
        bool,
        typer.Option(
            "--pipe/--sensor",
            help="Stream method, high-level pipeline API or low-level sensor API",
        ),
    ] = True,
    metadata: Annotated[bool, typer.Option("--md/--no-md", help="Show stream metadata")] = True,
):
    driver = require_device(ctx)
    logger.debug(f"stream {profiles}")
    if not profiles:
        profiles = []

    view = StreamView([profile.stream for profile in profiles], metadata=metadata)
    driver.play(profiles, pipeline=api)

    try:
        with Live(view, console=console, refresh_per_second=30):
            while True:
                frameset = driver.wait_for_frameset()
                if frameset is None:
                    logger.warning("Frames didn't arrive until timeout")
                    continue
                view.update(frameset)
    finally:
        err_console.print("Stopping all streams")
        driver.stop()
