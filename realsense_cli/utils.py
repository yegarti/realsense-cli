import time
from collections.abc import Callable

from realsense_cli.types import Profile, Stream

_stream_order: dict[str, int] = {stream: i for i, stream in enumerate(Stream)}


def group_profiles(profiles: list[Profile]) -> dict[Profile, list[int]]:
    """
    Group profiles that differ only by FPS
    """

    def sort_key(pro: Profile):
        return (
            _stream_order.get(pro.stream, 99),
            pro.resolution.width * pro.resolution.height,
            pro.format,
            pro.fps,
        )

    profiles = sorted(profiles, key=sort_key)

    def mapi(pro: Profile):
        return Profile(
            stream=pro.stream,
            resolution=pro.resolution,
            format=pro.format,
            index=pro.index,
            fps=0,
        )

    buckets: dict[Profile, list] = {}
    for profile in profiles:
        buckets.setdefault(mapi(profile), []).append(profile.fps)

    return buckets


def find_origin_sensor(sensor_profiles: dict[str, list[Profile]]) -> dict[str, str]:
    res = {}
    for sensor, profiles in sensor_profiles.items():
        for profile in profiles:
            if profile.stream in res:
                continue
            res[profile.stream] = sensor
    return res


def wait_for_reconnect(
    serial: str,
    connected: Callable[[], set[str]],
    timeout: float,
    poll: float = 0.1,
    drop_grace: float = 5,
) -> bool:
    """
    Wait until device SERIAL drops off CONNECTED and comes back, as after a hardware reset.
    A device still listed after DROP_GRACE seconds counts as back too: its drop fell between
    two polls. Whether it came back within TIMEOUT seconds
    """
    start = time.monotonic()
    dropped = False
    while (elapsed := time.monotonic() - start) < timeout:
        present = serial in connected()
        if present and (dropped or elapsed >= drop_grace):
            return True
        dropped = dropped or not present
        time.sleep(poll)
    return False
