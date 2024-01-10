from realsense_cli.types import Profile, Stream, Sensor


def group_profiles(profiles: list[Profile]) -> dict[Profile, list[int]]:
    """
    Group profiles that differ only by FPS
    """
    stream_order: dict[Stream, int] = {
        Stream.DEPTH: 0,
        Stream.INFRARED: 1,
        Stream.INFRARED2: 2,
        Stream.COLOR: 3,
        Stream.GYRO: 4,
        Stream.ACCEL: 5,
    }

    def sort_key(pro: Profile):
        return (
            stream_order[pro.stream],
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


def find_origin_sensor(sensor_profiles: dict[Sensor, list[Profile]]) -> dict[Stream, Sensor]:
    res = {}
    for sensor, profiles in sensor_profiles.items():
        for profile in profiles:
            if profile.stream in res:
                continue
            res[profile.stream] = sensor
    return res
