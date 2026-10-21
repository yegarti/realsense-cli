import time
from contextlib import nullcontext
from typing import Annotated

import typer
from loguru import logger
from rich.live import Live

from realsense_cli.console import console, err_console
from realsense_cli.driver.base import DriverProtocol
from realsense_cli.errors import NoFrames
from realsense_cli.printer import emit, list_frame_counts, list_profiles
from realsense_cli.session import json_output, require_device
from realsense_cli.stream_view import StreamView
from realsense_cli.types import _STREAM_ALIASES, Profile, resolve_sensor_name

stream_app = typer.Typer(help="Stream options", no_args_is_help=True)

# Seconds a bounded run waits for the next frameset before failing
FRAME_TIMEOUT = 3.0

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

    sensor_profiles = [(s, p) for s in rs_sensors for p in driver.list_streams(s)]
    payload = [
        {
            "sensor": sensor,
            "stream": p.stream,
            "width": p.resolution.width,
            "height": p.resolution.height,
            "fps": p.fps,
            "format": p.format,
            "index": p.index,
        }
        for sensor, p in sensor_profiles
    ]
    emit(ctx, {"profiles": payload}, lambda: list_profiles([p for _, p in sensor_profiles]))


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
                    Runs until Ctrl-C, or with --frames/--duration stops on its own and
                    prints the frames received per stream. A requested stream that
                    received no frames fails the run.\n
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
    frames: Annotated[
        int | None,
        typer.Option(
            "--frames",
            min=1,
            help="Stop after N framesets (with --sensor, each frame counts as one)",
            show_default=False,
        ),
    ] = None,
    duration: Annotated[
        float | None,
        typer.Option("--duration", help="Stop after S seconds", show_default=False),
    ] = None,
):
    if duration is not None and duration <= 0:
        raise typer.BadParameter("must be more than 0 seconds", param_hint="'--duration'")
    bounded = frames is not None or duration is not None
    if json_output(ctx) and not bounded:
        raise typer.BadParameter(
            "needs --frames or --duration: without them stream play runs until interrupted",
            param_hint="'--json'",
        )
    driver = require_device(ctx)
    logger.debug(f"stream {profiles}")
    if not profiles:
        profiles = []

    view = StreamView([profile.stream for profile in profiles], metadata=metadata)
    driver.play(profiles, pipeline=api)

    # the live view would corrupt the JSON on stdout
    live = (
        nullcontext()
        if json_output(ctx)
        else Live(view, console=console, refresh_per_second=30)
    )
    try:
        with live:
            if not bounded:
                while True:
                    frameset = driver.wait_for_frameset()
                    if frameset is None:
                        logger.warning("Frames didn't arrive until timeout")
                        continue
                    view.update(frameset)
            requested = [profile.stream for profile in profiles]
            counts = _count_frames(driver, view, requested, frames, duration)
    finally:
        err_console.print("Stopping all streams")
        driver.stop()

    if not counts:
        raise NoFrames("No frames arrived")
    missing = [stream for stream, n in counts.items() if n == 0]
    if missing:
        raise NoFrames(f"No frames arrived from {', '.join(missing)}. {_received(counts)}")
    payload = {"streams": [{"stream": s, "frames": n} for s, n in counts.items()]}
    emit(ctx, payload, lambda: list_frame_counts(counts))


def _received(counts: dict[str, int]) -> str:
    received = ", ".join(f"{stream} {n}" for stream, n in counts.items()) or "none"
    return f"Frames received: {received}"


def _count_frames(
    driver: DriverProtocol,
    view: StreamView,
    streams: list[str],
    frames: int | None,
    duration: float | None,
) -> dict[str, int]:
    """
    Frames received per stream until FRAMES framesets arrived or DURATION seconds passed.
    STREAMS start at 0, so a requested stream that got nothing still shows up
    """
    counts = dict.fromkeys(streams, 0)
    deadline = None if duration is None else time.monotonic() + duration
    framesets = 0
    while frames is None or framesets < frames:
        timeout = FRAME_TIMEOUT
        if deadline is not None:
            timeout = min(timeout, deadline - time.monotonic())
            if timeout <= 0:
                break
        frameset = driver.wait_for_frameset(timeout)
        if frameset is None:
            if timeout < FRAME_TIMEOUT:
                break  # the deadline cut the wait short: the run is over, not stalled
            raise NoFrames(f"No frames arrived within {FRAME_TIMEOUT:g}s. {_received(counts)}")
        framesets += 1
        for stream in frameset:
            counts[stream] = counts.get(stream, 0) + 1
        view.update(frameset)
    return counts
