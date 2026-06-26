from realsense_cli.types import Profile

_stream_order: dict[str, int] = {
    "Depth": 0,
    "Infrared 1": 1,
    "Infrared 2": 2,
    "Color": 3,
    "Gyro": 4,
    "Accel": 5,
}


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
