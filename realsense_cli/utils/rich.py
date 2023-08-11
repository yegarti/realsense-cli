from typing import Optional, Any

from rich import box
from rich.console import Console
from rich.table import Table

from realsense_cli.types import DeviceInfo, Option, Sensor


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
    title = f"{sensor} controls" if sensor else "Controls"
    table = Table(title=title, box=box.SIMPLE, min_width=80)
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

