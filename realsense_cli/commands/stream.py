import time
from collections.abc import Callable
from contextlib import nullcontext
from typing import Annotated

import typer
from loguru import logger
from rich.live import Live

from realsense_cli.commands.capture import profile_payload
from realsense_cli.console import console, err_console
from realsense_cli.driver.base import DriverProtocol
from realsense_cli.errors import InvalidValue, NoFrames, with_bandwidth_hint
from realsense_cli.preview import PreviewMode, choose_mode
from realsense_cli.printer import emit, list_frame_counts, list_profiles
from realsense_cli.session import json_output, require_device
from realsense_cli.stream_view import PreviewLive, StreamView
from realsense_cli.types import (
    _STREAM_ALIASES,
    FrameSet,
    Profile,
    resolve_sensor_name,
    resolve_stream_name,
)

stream_app = typer.Typer(help="Stream options", no_args_is_help=True)

# Seconds a bounded run waits for a stream's next frame before failing
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
    payload = [{"sensor": sensor} | profile_payload(p) for sensor, p in sensor_profiles]
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
                    prints the frames received per stream. A stream that sends no
                    frames for 3 seconds fails the run.\n
                    \n
                    --preview adds a live image of one video stream (the first one, or
                    --preview-stream): truecolor half-blocks on a color terminal, ASCII
                    otherwise (--preview-mode), depth colorized.\n
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
            help="Stop once every stream received N frames",
            show_default=False,
        ),
    ] = None,
    duration: Annotated[
        float | None,
        typer.Option("--duration", help="Stop after S seconds", show_default=False),
    ] = None,
    preview: Annotated[
        bool, typer.Option("--preview", help="Show a live image of one video stream")
    ] = False,
    preview_mode: Annotated[
        PreviewMode | None,
        typer.Option(
            "--preview-mode",
            help="How to draw the image: auto picks halfblock on a color terminal, "
            "ascii otherwise. Implies --preview  [default: auto]",
            show_default=False,
        ),
    ] = None,
    preview_stream: Annotated[
        str | None,
        typer.Option(
            "--preview-stream",
            metavar="STREAM",
            help="Video stream to show, by name or alias. Implies --preview  "
            "[default: first video stream]",
            show_default=False,
        ),
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
    preview = preview or preview_mode is not None or preview_stream is not None
    if json_output(ctx) and preview:
        raise typer.BadParameter(
            "can't be used with --json: the live view would corrupt the JSON",
            param_hint="'--preview'",
        )
    driver = require_device(ctx)
    logger.debug(f"stream {profiles}")
    if not profiles:
        profiles = []

    # the profiles the device started, defaults included: frames are reported under their names
    started_profiles = driver.play(profiles, pipeline=api)
    started = [profile.stream for profile in started_profiles]
    view = StreamView(started, metadata=metadata)
    try:
        live: PreviewLive | Live | nullcontext
        update = view.update
        waiting = view.waiting
        if preview:
            stream = preview_target(started_profiles, preview_stream)
            mode = preview_mode or PreviewMode.AUTO
            if mode is PreviewMode.AUTO:
                mode = choose_mode(console)
            live = PreviewLive(view, stream, mode, console)
            update = live.update
            waiting = live.waiting
        elif json_output(ctx):
            # the live view would corrupt the JSON on stdout
            live = nullcontext()
        else:
            live = Live(view, console=console, refresh_per_second=30)
        with live:
            if not bounded:
                while True:
                    frameset = driver.wait_for_frameset(FRAME_TIMEOUT, images=preview)
                    if frameset is None:
                        logger.warning("Frames didn't arrive until timeout")
                        waiting(FRAME_TIMEOUT)
                        continue
                    update(frameset)
            counts = dict.fromkeys(started, 0)
            count_frames(driver, counts, frames, duration, update, images=preview)
    finally:
        err_console.print("Stopping all streams")
        driver.stop()

    missing = [stream for stream, n in counts.items() if n == 0]
    if missing:
        raise NoFrames(
            with_bandwidth_hint(
                f"No frames arrived from {', '.join(missing)}. {received_summary(counts)}",
                started,
            )
        )
    payload = {"streams": [{"stream": s, "frames": n} for s, n in counts.items()]}
    emit(ctx, payload, lambda: list_frame_counts(counts))


def preview_target(started: list[Profile], name: str | None) -> str:
    """
    The stream a preview shows: the one NAME names (a stream name or alias, any case), or the
    first video stream STARTED holds. InvalidValue when it isn't a started video stream
    """
    video = [profile.stream for profile in started if profile.resolution.width]
    if name is None:
        if not video:
            raise InvalidValue(
                "No video stream to preview: the streams playing are "
                f"{', '.join(p.stream for p in started)}"
            )
        return video[0]
    wanted = str(resolve_stream_name(name)).lower()
    for stream in video:
        if stream.lower() == wanted:
            return stream
    raise InvalidValue(
        f"Can't preview '{name}': not a video stream that is playing. "
        f"Video streams playing: {', '.join(video) or 'none'}"
    )


def received_summary(counts: dict[str, int]) -> str:
    received = ", ".join(f"{stream} {n}" for stream, n in counts.items()) or "none"
    return f"Frames received: {received}"


def count_frames(
    driver: DriverProtocol,
    counts: dict[str, int],
    frames: int | None,
    duration: float | None,
    on_frameset: Callable[[FrameSet], None],
    images: bool = False,
) -> None:
    """
    Add the new frames received per stream to COUNTS until each of its streams has FRAMES
    frames or DURATION seconds passed; neither means until interrupted. COUNTS is filled as
    frames arrive, so it holds what arrived even when the run is cut short. Each frameset is
    handed to ON_FRAMESET. A stream still short of FRAMES that sends nothing for FRAME_TIMEOUT
    seconds fails the run. With IMAGES, frames carry their images
    """
    streams = list(counts)
    started = time.monotonic()
    last_frame = dict.fromkeys(streams, started)
    last_index: dict[str, int] = {}
    deadline = None if duration is None else started + duration
    while True:
        now = time.monotonic()
        if deadline is not None and now >= deadline:
            break
        waiting = [s for s in streams if frames is None or counts[s] < frames]
        if not waiting:
            break
        stalled = [s for s in waiting if now - last_frame[s] >= FRAME_TIMEOUT]
        if stalled:
            raise NoFrames(
                with_bandwidth_hint(
                    f"No frames arrived from {', '.join(stalled)} within {FRAME_TIMEOUT:g}s. "
                    f"{received_summary(counts)}",
                    streams,
                )
            )
        # wake up in time to notice the first stall, or the deadline
        timeout = min(last_frame[s] for s in waiting) + FRAME_TIMEOUT - now
        if deadline is not None:
            timeout = min(timeout, deadline - now)
        frameset = driver.wait_for_frameset(timeout, images=images)
        if frameset is None:
            continue
        now = time.monotonic()
        for stream, frame in frameset.items():
            # the pipeline can hand out a slower stream's last frame again in later framesets
            if last_index.get(stream) == frame.index:
                continue
            last_index[stream] = frame.index
            counts[stream] = counts.get(stream, 0) + 1
            last_frame[stream] = now
        on_frameset(frameset)
