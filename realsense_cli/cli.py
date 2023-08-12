import typer

from realsense_cli.commands.config.app import config_app
from realsense_cli.commands.stream.app import stream_app
from realsense_cli.driver import get_driver
from realsense_cli.utils.rich import list_devices

app = typer.Typer(no_args_is_help=True)


@app.command(name="list")
def rs_list() -> None:
    """
    List connected devices with basic info
    """
    driver = get_driver()
    devices = driver.query_devices()
    list_devices(devices)


app.add_typer(config_app, name="config")

app.add_typer(stream_app, name="stream")
