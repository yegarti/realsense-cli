from typing import Annotated

import typer

from realsense_cli.driver import get_driver
from realsense_cli.utils.rich import show_devices

app = typer.Typer()


@app.command(name='list')
@app.command(name="list")
def rs_list() -> None:
    """
    List connected devices with basic info
    """
    driver = get_driver()
    devices = driver.query_devices()
    list_devices(devices)


@app.command(name='conigure')
def rs_configure():
    pass