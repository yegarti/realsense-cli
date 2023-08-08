from rich import box
from rich.console import Console
from rich.table import Table

from realsense_cli.types import DeviceInfo


def show_devices(devices: list[DeviceInfo]) -> None:
    table = Table(title='Devices', box=box.SIMPLE, min_width=80)
    table.add_column('Name', justify='center')
    table.add_column('Serial', justify='center')
    table.add_column('Firmware', justify='center')
    table.add_column('USB Connection', justify='center')

    for dev in devices:
        table.add_row(dev.name, dev.serial, dev.fw, dev.connection)

    Console().print(table)
