from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

from rosbags.rosbag1 import Reader
from rosbags.typesys import Stores, get_typestore, get_types_from_idl

_rs_msgs_idl = """
module realsense_msgs {
    typedef std_msgs::msg::Bool bool;
    typedef std_msgs::msg::Time time;
    typedef float vector3[3];
    typedef float vector12[12];

    module msg {
        struct StreamInfo {
            uint32 fps;
            string encoding;
            bool is_recommended;
        };

        struct ImuIntrinsic {
            vector12 data;
            vector3 noise_variances;
            vector3 bias_variances;
        };

        struct Notification {
            time timestamp;
            string category;
            string severity;
            string description;
            string serialized_data;
        };
    };
};
"""


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
        typestore = get_typestore(Stores.ROS1_NOETIC)
        typestore.register(get_types_from_idl(_rs_msgs_idl))
        self._reader = Reader(self.path)
        self._reader.open()
        self.duration = self._reader.duration / 1e9
        for conn in self._reader.connections:
            self.topics[conn.topic] = TopicInfo(conn.topic, conn.msgtype, conn.msgcount)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self._reader.close()

            # if conn.msgtype == 'sensor_msgs/msg/Image':
            #     # extra unknown 4 bytes at the end
            #     rd = rd[:-4]
            # msg = deserialize_ros1(rd, conn.msgtype)
