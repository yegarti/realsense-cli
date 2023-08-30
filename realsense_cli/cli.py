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


@app.callback()
def callback(ctx: typer.Context):
    if ctx.invoked_subcommand != 'list':
        if not get_driver().query_devices():
            print("No devices are connected")
        raise typer.Exit(1)
