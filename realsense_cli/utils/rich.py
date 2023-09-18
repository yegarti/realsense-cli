from typing import Optional, Any

from rich import box
from rich.console import Console
from rich.table import Table

from realsense_cli.types import DeviceInfo, Option, Sensor, Profile, Stream


def list_devices(devices: list[DeviceInfo]) -> None:
    table = Table(title="Devices", box=box.SIMPLE, min_width=80)
    table.add_column("Name", justify="center")
    table.add_column("Serial", justify="center")
    table.add_column("Firmware", justify="center")
    table.add_column("USB Connection", justify="center")
    table.add_column("Sensors", justify="center")

    for dev in devices:
        sensors = "\n".join(dev.sensors)
        table.add_row(dev.name, dev.serial, dev.fw, dev.connection, sensors)

    Console().print(table)


def list_options(
    options: list[Option],
    sensor: Optional[Sensor] = None,
):
    """
    Print a table showing sensor options
    """
    title = f"{sensor.value} controls" if sensor else "Controls"
    table = Table(title=title, box=box.SIMPLE)
    table.add_column("Name")
    table.add_column("Description")
    table.add_column("Min Value")
    table.add_column("Max Value")
    table.add_column("Step")
    table.add_column("Default Value")

    for opt in options:
        table.add_row(
            opt.name,
            opt.description,
            str(opt.min_value),
            str(opt.max_value),
            str(opt.step),
            str(opt.default_value),
        )

    Console().print(table)


def list_options_values(options_values: dict[str, Any]):
    table = Table(box=box.SIMPLE)
    table.add_column("Name")
    table.add_column("Value")

    for opt, value in options_values.items():
        table.add_row(opt, str(value))

    Console().print(table)


def list_profiles(profiles: list[Profile], title: str = "Streams"):
    table = Table(title=title, box=box.SIMPLE)
    table.add_column("Stream")
    table.add_column("Resolution")
    table.add_column("FPS")
    table.add_column("Format")

    stream_order: dict[Stream, int] = {
        Stream.DEPTH: 0,
        Stream.INFRARED: 1,
        Stream.INFRARED2: 2,
        Stream.COLOR: 3,
        Stream.GYRO: 4,
        Stream.ACCEL: 5,
    }

    def sort_key(pro: Profile):
        return (
            stream_order[pro.stream],
            pro.resolution.width * pro.resolution.height,
            pro.format,
            pro.fps,
        )

    profiles = sorted(profiles, key=sort_key)

    def mapi(pro: Profile):
        return Profile(
            stream=pro.stream,
            resolution=pro.resolution,
            format=pro.format,
            index=pro.index,
            fps=0,
        )

    buckets: dict[Profile, list] = {}
    for profile in profiles:
        buckets.setdefault(mapi(profile), []).append(profile.fps)

    for profile, fps in buckets.items():
        table.add_row(
            profile.stream.value,
            str(profile.resolution),
            "/".join(map(str, fps)),
            profile.format,
        )

    Console().print(table)
