from pathlib import Path
from typing import Optional, Any

from rich import box
from rich.console import Console
from rich.table import Table

from realsense_cli.rs_bag_parser import TopicInfo
from realsense_cli.types import DeviceInfo, Option, Sensor, Profile
from realsense_cli.utils import group_profiles


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
    table.add_column("Min Value")
    table.add_column("Max Value")
    table.add_column("Step")
    table.add_column("Default Value")
    table.add_column("Description")

    for opt in options:
        table.add_row(
            opt.name,
            str(opt.vtype(opt.min_value)),
            str(opt.vtype(opt.max_value)),
            str(opt.vtype(opt.step)),
            str(opt.vtype(opt.default_value)),
            opt.description,
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

    groups = group_profiles(profiles)
    for profile, fps in groups.items():
        table.add_row(
            profile.stream.value,
            str(profile.resolution),
            "/".join(map(str, fps)),
            profile.format,
        )

    Console().print(table)


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
    Console().print(table)
    Console().print(info_table)
