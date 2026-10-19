from pathlib import Path
from typing import Annotated

import typer

from realsense_cli.printer import emit, list_bag_data
from realsense_cli.rs_bag_parser import RosParser

bag_app = typer.Typer(help="Rosbag options", no_args_is_help=True)


@bag_app.command(name="info", help="Info about realsense rosbag file")
def bag_info(
    ctx: typer.Context,
    bag: Annotated[
        Path,
        typer.Argument(exists=True, file_okay=True),
    ],
):
    with RosParser(bag.absolute()) as parser:
        path, duration = parser.path, parser.duration
        topics = sorted(parser.topics.values(), key=lambda t: (t.total_messages, t.name))
    payload = {
        "path": str(path),
        "duration": duration,
        "topics": [
            {"name": t.name, "messages": t.total_messages, "type": t.msg_type} for t in topics
        ],
    }
    emit(ctx, payload, lambda: list_bag_data(path, duration, topics))
