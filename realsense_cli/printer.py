import json
import math
from collections.abc import Callable, Iterable
from decimal import Decimal
from itertools import groupby
from pathlib import Path
from typing import Any

import typer
from rich import box
from rich.table import Table

from realsense_cli.console import console
from realsense_cli.rs_bag_parser import TopicInfo
from realsense_cli.session import json_output
from realsense_cli.types import (
    Calibration,
    DeviceInfo,
    Option,
    Profile,
    Resolution,
    StreamIntrinsics,
    sensor_label,
)
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

    list_intrinsics(calibration.intrinsics)
    list_distortion(calibration.intrinsics)

    if not calibration.extrinsics:
        return
    table = Table(title="Extrinsics", box=box.SIMPLE)
    table.add_column("From")
    table.add_column("To")
    table.add_column("Rotation")
    table.add_column("Translation (m)")
    for ext in calibration.extrinsics:
        table.add_row(
            ext.source,
            ext.target,
            # column-major: row i holds every third value from i
            _matrix([ext.rotation[row::3] for row in range(3)]),
            _matrix([[t] for t in ext.translation]),
        )
    console.print(table)


def _matrix(rows: list[tuple[float, ...]] | list[list[float]]) -> Table:
    grid = Table.grid(padding=(0, 1))
    for _ in rows[0]:
        grid.add_column(justify="right")
    for row in rows:
        grid.add_row(*map(_number, row))
    return grid


def list_intrinsics(intrinsics: list[StreamIntrinsics]) -> None:
    """
    A row per stream and resolution, the stream named on its first row only. Distortion is
    left to `list_distortion`: it rarely changes with the resolution
    """
    table = Table(title="Intrinsics", box=box.SIMPLE)
    table.add_column("Stream")
    table.add_column("Resolution")
    for attribute in ("ppx", "ppy", "fx", "fy"):
        table.add_column(attribute, justify="right")
    # last: a long list of formats wraps without pushing the numbers apart
    table.add_column("Formats")
    for stream, groups in groupby(intrinsics, key=lambda group: group.stream):
        groups = list(groups)
        for i, group in enumerate(groups):
            intr = group.intrinsics
            values = (
                ["n/a"] * 4
                if intr is None
                else [_number(value) for value in (intr.ppx, intr.ppy, intr.fx, intr.fy)]
            )
            table.add_row(
                stream if i == 0 else "",
                str(group.resolution),
                *values,
                ", ".join(group.formats),
                end_section=i == len(groups) - 1,
            )
    console.print(table)


def list_distortion(intrinsics: list[StreamIntrinsics]) -> None:
    """
    A row per stream and distortion, listing its resolutions only when a stream has several
    """
    resolutions: dict[tuple[str, str, tuple[float, ...]], list[Resolution]] = {}
    for group in intrinsics:
        if group.intrinsics is not None:
            key = (group.stream, group.intrinsics.model, group.intrinsics.coeffs)
            resolutions.setdefault(key, []).append(group.resolution)
    if not resolutions:
        return
    streams = [stream for stream, _, _ in resolutions]
    by_resolution = len(streams) > len(set(streams))

    table = Table(title="Distortion", box=box.SIMPLE)
    table.add_column("Stream")
    if by_resolution:
        table.add_column("Resolutions")
    table.add_column("Model")
    table.add_column("Coefficients")
    for (stream, model, coeffs), stream_resolutions in resolutions.items():
        cells = [stream, model, _numbers(coeffs)]
        if by_resolution:
            cells.insert(1, "/".join(map(str, stream_resolutions)))
        table.add_row(*cells)
    console.print(table)


def _numbers(values: Iterable[float]) -> str:
    return ", ".join(map(_number, values))


def _number(value: float) -> str:
    """
    VALUE with every digit it holds, without an exponent: `:g` keeps only 6 digits and
    prints 0.0000907 as 9.07e-05
    """
    if value == 0:
        return "0"
    return format(Decimal(repr(value)), "f").removesuffix(".0")


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


def depth_query(payload: dict[str, Any]) -> None:
    """`rs depth`'s result, from its JSON payload: the depth first, then how it was measured"""
    table = Table(title="Depth", box=box.SIMPLE, show_header=False)
    table.add_column()
    table.add_column(justify="right")
    table.add_row("Depth", _meters(payload["depth"]))
    if "pixel" in payload:
        pixel = payload["pixel"]
        table.add_row("Pixel", f"{pixel['x']}, {pixel['y']}")
        table.add_row("Samples", f"{pixel['samples']} of {payload['frames']} frames")
    else:
        region = payload["region"]
        table.add_row(
            "Region", f"{region['x']}, {region['y']}, {region['width']}x{region['height']}"
        )
        table.add_row("Fill rate", f"{region['fill_rate']:.1%}")
        table.add_row("Valid pixels", f"{region['valid_pixels']} of {region['pixels']}")
        for statistic in ("min", "max", "mean", "median", "stddev"):
            table.add_row(statistic.title(), _meters(region[statistic]))
        table.add_row("Frames", str(payload["frames"]))
    [profile] = payload["profiles"]
    table.add_row(
        "Profile",
        f"{profile['stream']} {profile['width']}x{profile['height']} "
        f"{profile['format']} @ {profile['fps']}",
    )
    console.print(table)


def _meters(depth: float | None) -> str:
    return "no depth" if depth is None else f"{depth:.3f} m"


def list_paths(paths: list[str]) -> None:
    # one per line and unwrapped, so they can be piped or copied
    for path in paths:
        console.print(path, soft_wrap=True, highlight=False, markup=False)


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
