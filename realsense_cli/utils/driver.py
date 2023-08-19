from typing import Optional, Sequence

from realsense_cli.model import Stream, Profile


def prepare_profiles(
    streams: Sequence[Stream],
) -> list[Profile]:
    """
    Prepare profiles from user requirements for the driver
    """

    res: list[Profile] = []
    for stream in streams:
        if stream == Stream.INFRARED:
            index = 1
        elif stream == Stream.INFRARED2:
            index = 2
        else:
            index = -1

        res.append(Profile(stream=stream, index=index))

    return res
