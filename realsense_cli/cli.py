import typer

from realsense_cli.driver import get_driver
from realsense_cli.utils.rich import show_devices

app = typer.Typer()


@app.command(name='list')
def rs_list() -> None:
    driver = get_driver()
    devices = driver.query_devices()
    show_devices(devices)


@app.command(name='conigure')
def rs_configure():
    pass