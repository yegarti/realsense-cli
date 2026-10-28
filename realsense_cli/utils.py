from pathlib import Path

from realsense_cli.types import Profile, Stream

_stream_order: dict[str, int] = {stream: i for i, stream in enumerate(Stream)}


def stream_rank(stream: str) -> int:
    """
    Where STREAM sorts: known streams in `Stream` order, then the rest
    """
    return _stream_order.get(stream, len(_stream_order))


def group_profiles(profiles: list[Profile]) -> dict[Profile, list[int]]:
    """
    Group profiles that differ only by FPS
    """

    def sort_key(pro: Profile):
        return (
            stream_rank(pro.stream),
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


def new_path(stem: str, suffix: str = "") -> Path:
    """
    ./STEM+SUFFIX, or ./STEM-2+SUFFIX, ./STEM-3+SUFFIX ... when it is taken, e.g. by a run in
    the same second
    """
    path, n = Path(stem + suffix), 1
    while path.exists():
        n += 1
        path = Path(f"{stem}-{n}{suffix}")
    return path
