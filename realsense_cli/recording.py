"""
A recording's file read directly with the standard library's `sqlite3`, before the SDK opens
it: librealsense's playback hangs for over 15 seconds on a recording with no frames.

A recording is a rosbag2 `.db3` database: a `topics` table, and a `messages` table holding each
message's `topic_id`.
"""

import re
import sqlite3
from contextlib import closing
from pathlib import Path

from realsense_cli.errors import InvalidValue, NoFrames

# A frame's topic, named after its stream type and index:
# `/device_0/sensor_0/Depth_0/image/data` (`.../image/data/compressed` or `.../compressedDepth`
# when compressed), or `/device_0/sensor_2/Gyro_0/imu/data`
_FRAME_TOPIC = re.compile(
    r"/device_\d+/sensor_\d+/(?P<type>[^/]+)_(?P<index>\d+)"
    r"/(image/data(/compressed(Depth)?)?|imu/data)"
)


def check_recording(path: Path) -> dict[tuple[str, int], int]:
    """
    The frames per stream in the recording at PATH, keyed by stream name and index as the SDK
    lists its profiles, e.g. ('Infrared 1', 1). Raises `InvalidValue` for a file that isn't a
    `.db3` recording and `NoFrames` for a recording with no frames
    """
    if path.suffix.lower() != ".db3":
        raise InvalidValue(
            "Only `.db3` recordings are supported; "
            "convert a `.bag` with librealsense's `convert_bag_to_db3`"
        )
    try:
        with closing(sqlite3.connect(f"{path.absolute().as_uri()}?mode=ro", uri=True)) as db:
            topics = db.execute(
                "SELECT topics.name, COUNT(messages.id) FROM topics"
                " LEFT JOIN messages ON messages.topic_id = topics.id GROUP BY topics.id"
            ).fetchall()
    except sqlite3.DatabaseError as e:
        raise InvalidValue(f"'{path}' is not a recording: not a rosbag2 database ({e})") from e

    names = {name for name, _ in topics}
    # the SDK writes /file_version first and the camera info with the first frame, so a
    # recording that never got a frame has only the former
    if "/file_version" not in names:
        raise _not_recording(path, "/file_version")
    frames: dict[tuple[str, int], int] = {}
    for name, count in topics:
        if match := _FRAME_TOPIC.fullmatch(name):
            key = _stream_name(match["type"], int(match["index"])), int(match["index"])
            frames[key] = frames.get(key, 0) + count
    if not any(frames.values()):
        raise NoFrames(f"'{path}' holds no frames")
    if "/device_0/info" not in names:
        raise _not_recording(path, "/device_0/info")
    return frames


def _stream_name(stream_type: str, index: int) -> str:
    """The SDK's name for a stream: its type, followed by its index unless that is 0"""
    return f"{stream_type} {index}" if index else stream_type


def _not_recording(path: Path, topic: str) -> InvalidValue:
    return InvalidValue(f"'{path}' is not a recording: it has no {topic} topic")
