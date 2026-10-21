import json
import math
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import typer
from rich import box
from rich.table import Table

from realsense_cli.console import console
from realsense_cli.rs_bag_parser import TopicInfo
from realsense_cli.session import json_output
from realsense_cli.types import Calibration, DeviceInfo, Option, Profile, sensor_label
from realsense_cli.utils import group_profiles


def emit(ctx: typer.Context, payload: dict[str, Any], table: Callable[[], None]) -> None:
    """
    Print a command's result: PAYLOAD as JSON under `--json`, otherwise TABLE renders it
    """
    if json_output(ctx):
        # Not `print`: Rich wraps long lines and highlights, which would corrupt the JSON
        console.out(json.dumps(_finite(payload), indent=2, allow_nan=False), highlight=False)
    else:
        table()


def _finite(value: Any) -> Any:
    """
    VALUE with NaN and infinite floats replaced by None: JSON has no token for them
    """
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: _finite(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_finite(v) for v in value]
    return value


def list_devices(devices: list[DeviceInfo]) -> None:
    table = Table(title="Devices", box=box.SIMPLE, min_width=80)
    table.add_column("Name", justify="center")
    table.add_column("Serial", justify="center")
    table.add_column("Firmware", justify="center")
    table.add_column("USB Connection", justify="center")
    table.add_column("Sensors", justify="center")

    for dev in devices:
        sensors = "\n".join(map(sensor_label, dev.sensors))
        table.add_row(dev.name, dev.serial, dev.fw, dev.connection, sensors)

    console.print(table)


def device_details(
    camera_info: dict[str, str], sensors: list[str], calibration: Calibration | None = None
) -> None:
    table = Table(title="Device", box=box.SIMPLE, show_header=False)
    table.add_column()
    table.add_column()
    for name, value in camera_info.items():
        table.add_row(name.replace("_", " ").title(), value)
    table.add_row("Sensors", "\n".join(map(sensor_label, sensors)))
    console.print(table)
    if calibration is None:
        return

    # one table per group: a row per profile would be too wide for a terminal
    for group in calibration.intrinsics:
        intr = group.intrinsics
        title = (
            f"Intrinsics of {group.stream} {group.resolution} {'/'.join(group.formats)} "
            f"@ {'/'.join(map(str, group.fps))} fps"
        )
        # Rich wraps a title wider than its table
        table = Table(title=title, box=box.SIMPLE, show_header=False, min_width=len(title))
        table.add_column()
        table.add_column()
        table.add_row("Principal Point", _numbers([intr.ppx, intr.ppy]))
        table.add_row("Focal Length", _numbers([intr.fx, intr.fy]))
        table.add_row("Distortion", intr.model)
        table.add_row("Coefficients", _numbers(intr.coeffs))
        console.print(table)

    if not calibration.extrinsics:
        return
    table = Table(title="Extrinsics", box=box.SIMPLE)
    table.add_column("From")
    table.add_column("To")
    table.add_column("Rotation")
    table.add_column("Translation (m)")
    for ext in calibration.extrinsics:
        # column-major, printed as the 3x3 matrix it is
        rotation = "\n".join(_numbers(ext.rotation[row::3], sep="  ") for row in range(3))
        table.add_row(ext.source, ext.target, rotation, _numbers(ext.translation))
    console.print(table)


def _numbers(values: Iterable[float], sep: str = ", ") -> str:
    # every digit the SDK's float32 holds: `:g` keeps only 6 of them
    return sep.join(f"{v:.9g}" for v in values)


def list_options(
    options: list[Option],
    sensor: str | None = None,
):
    """
    Print a table showing sensor options
    """
    title = f"{sensor} controls" if sensor else "Controls"
    table = Table(title=title, box=box.SIMPLE)
    table.add_column("Name")
    table.add_column("Min Value")
    table.add_column("Max Value")
    table.add_column("Step")
    table.add_column("Default Value")
    table.add_column("Read Only")
    table.add_column("Description")

    for opt in options:
        table.add_row(
            opt.name,
            str(opt.vtype(opt.min_value)),
            str(opt.vtype(opt.max_value)),
            str(opt.vtype(opt.step)),
            str(opt.vtype(opt.default_value)),
            "yes" if opt.read_only else "",
            opt.description,
        )

    console.print(table)


def list_options_values(options_values: dict[str, Any]):
    table = Table(box=box.SIMPLE)
    table.add_column("Name")
    table.add_column("Value")

    for opt, value in options_values.items():
        table.add_row(opt, str(value))

    console.print(table)


def list_restored(restored: list[dict[str, Any]], failed: list[dict[str, Any]]) -> None:
    if not restored and not failed:
        console.print("Nothing changed: the controls are already at their defaults")
        return
    if restored:
        table = Table(title="Restored controls", box=box.SIMPLE)
        table.add_column("Sensor")
        table.add_column("Control")
        table.add_column("Old Value")
        table.add_column("New Value")
        for row in restored:
            table.add_row(row["sensor"], row["control"], str(row["old"]), str(row["new"]))
        console.print(table)
    if failed:
        table = Table(title="Failed controls", box=box.SIMPLE)
        table.add_column("Sensor")
        table.add_column("Control")
        table.add_column("Error")
        for row in failed:
            table.add_row(row["sensor"], row["control"], row["error"])
        console.print(table)


def list_frame_counts(counts: dict[str, int]) -> None:
    table = Table(title="Frames received", box=box.SIMPLE)
    table.add_column("Stream")
    table.add_column("Frames", justify="right")
    for stream, frames in counts.items():
        table.add_row(stream, str(frames))
    console.print(table)


def list_profiles(profiles: list[Profile], title: str = "Streams"):
    table = Table(title=title, box=box.SIMPLE)
    table.add_column("Stream")
    table.add_column("Resolution")
    table.add_column("FPS")
    table.add_column("Format")

    groups = group_profiles(profiles)
    for profile, fps in groups.items():
        table.add_row(
            profile.stream,
            str(profile.resolution),
            "/".join(map(str, fps)),
            profile.format,
        )

    console.print(table)


def list_bag_data(path: Path, duration: float, topics: list[TopicInfo]):
    info_table = Table(box=box.SIMPLE_HEAD)
    info_table.add_column()
    info_table.add_column()
    info_table.add_row("Bag", str(path))
    info_table.add_row("Duration", f"{duration} seconds")
    table = Table(title="Data", box=box.SIMPLE)
    table.add_column("Topic")
    table.add_column("Messages")
    table.add_column("Message Type")
    for info in topics:
        table.add_row(info.name, str(info.total_messages), info.msg_type)
    console.print(table)
    console.print(info_table)
