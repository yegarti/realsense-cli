from typing import Annotated, Any

import typer

from realsense_cli.printer import device_details, emit
from realsense_cli.session import require_device
from realsense_cli.types import _STREAM_ALIASES, Calibration, Profile


def rs_info(
    ctx: typer.Context,
    profiles: Annotated[
        list[Profile] | None,
        typer.Argument(
            help=(
                "Also show calibration for the video profiles matching these, in the "
                "`stream play` syntax. Stream aliases: " + ", ".join(_STREAM_ALIASES)
            ),
            show_default=False,
            parser=Profile.from_string,
        ),
    ] = None,
    all_profiles: Annotated[
        bool,
        typer.Option("--all-profiles", help="Show calibration for every video profile"),
    ] = False,
) -> None:
    """
    Show device details: every camera info field and its sensors\n
    \n
    With PROFILES or --all-profiles, also the intrinsics of the matching video profiles and
    the extrinsics between their streams. Profiles use the `stream play` syntax,
    STREAM-RESOLUTION-FPS-FORMAT, and unset parts match anything: 'depth' is every depth
    profile.
    """
    if profiles and all_profiles:
        raise typer.BadParameter(
            "can't be combined with PROFILES", param_hint="'--all-profiles'"
        )
    driver = require_device(ctx)
    camera_info = driver.camera_info()
    sensors = driver.sensors
    payload: dict[str, Any] = {"device": camera_info, "sensors": sensors}
    calibration = None
    if profiles or all_profiles:
        calibration = driver.calibration(profiles or None)
        payload |= _calibration_payload(calibration)
    emit(ctx, payload, lambda: device_details(camera_info, sensors, calibration))


def _calibration_payload(calibration: Calibration) -> dict[str, Any]:
    return {
        "intrinsics": [
            {
                "stream": s.stream,
                "index": s.index,
                "width": s.resolution.width,
                "height": s.resolution.height,
                "formats": list(s.formats),
                "fps": list(s.fps),
                "ppx": s.intrinsics.ppx,
                "ppy": s.intrinsics.ppy,
                "fx": s.intrinsics.fx,
                "fy": s.intrinsics.fy,
                "model": s.intrinsics.model,
                "coeffs": list(s.intrinsics.coeffs),
            }
            for s in calibration.intrinsics
        ],
        "extrinsics": [
            {
                "from": e.source,
                "to": e.target,
                "rotation": list(e.rotation),
                "translation": list(e.translation),
            }
            for e in calibration.extrinsics
        ],
    }
