from dataclasses import dataclass


@dataclass
class DeviceInfo:
    name: str
    serial: str
    fw: str
    connection: str

