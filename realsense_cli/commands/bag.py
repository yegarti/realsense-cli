from pathlib import Path
from typing import Annotated

import typer

from realsense_cli.printer import list_bag_data
from realsense_cli.rs_bag_parser import RosParser

bag_app = typer.Typer(help="Rosbag options", no_args_is_help=True)


@bag_app.command(name="info", help="Info about realsense rosbag file")
def bag_info(
    bag: Annotated[
        Path,
        typer.Argument(exists=True, file_okay=True),
    ],
):
    parser = RosParser(bag.absolute())
    list_bag_data(
        parser.path,
        parser.duration,
        sorted(list(parser.topics.values()), key=lambda t: (t.total_messages, t.name)),
    )
