from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

from rosbags.rosbag1 import Reader


class TopicInfo(NamedTuple):
    name: str
    msg_type: str
    total_messages: int


@dataclass
class RosParser:
    path: Path
    duration: float = field(init=False)
    topics: dict[str, TopicInfo] = field(init=False, default_factory=dict)
    _reader: Reader = field(init=False)

    def __post_init__(self):
        self._reader = Reader(self.path)
        self._reader.open()
        self.duration = self._reader.duration / 1e9
        for conn in self._reader.connections:
            self.topics[conn.topic] = TopicInfo(conn.topic, conn.msgtype, conn.msgcount)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self._reader.close()
