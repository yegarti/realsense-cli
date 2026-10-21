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
                "stream": group.stream,
                "index": group.index,
                "width": group.resolution.width,
                "height": group.resolution.height,
                "formats": list(group.formats),
                "fps": list(group.fps),
                "ppx": group.intrinsics.ppx,
                "ppy": group.intrinsics.ppy,
                "fx": group.intrinsics.fx,
                "fy": group.intrinsics.fy,
                "model": group.intrinsics.model,
                "coeffs": list(group.intrinsics.coeffs),
            }
            for group in calibration.intrinsics
        ],
        "extrinsics": [
            {
                "from": ext.source,
                "to": ext.target,
                "rotation": list(ext.rotation),
                "translation": list(ext.translation),
            }
            for ext in calibration.extrinsics
        ],
    }
