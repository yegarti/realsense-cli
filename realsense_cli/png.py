"""
PNG encoding of video frames, with only the standard library.
"""

import struct
import sys
import zlib
from array import array

from realsense_cli.types import Image

# rs.format name: (PNG color type, bit depth, channels, whether the first and third channels
# swap, as BGR(A) is stored RGB(A))
_FORMATS: dict[str, tuple[int, int, int, bool]] = {
    "z16": (0, 16, 1, False),
    "y16": (0, 16, 1, False),
    "y8": (0, 8, 1, False),
    "rgb8": (2, 8, 3, False),
    "bgr8": (2, 8, 3, True),
    "rgba8": (6, 8, 4, False),
    "bgra8": (6, 8, 4, True),
}

FORMATS = tuple(_FORMATS)
"""The formats `encode` takes, as `rs.format` names"""


def encode(image: Image) -> bytes:
    """
    IMAGE as a PNG file: 16-bit grayscale for Z16 and Y16 (the raw values), 8-bit grayscale,
    RGB or RGBA for the others
    """
    color_type, bit_depth, channels, swap = _FORMATS[image.format]
    data = image.data
    if bit_depth == 16 and sys.byteorder == "little":
        # PNG samples are big-endian
        samples = array("H")
        samples.frombytes(data)
        samples.byteswap()
        data = samples.tobytes()
    if swap:
        swapped = bytearray(data)
        swapped[0::channels] = data[2::channels]
        swapped[2::channels] = data[0::channels]
        data = bytes(swapped)
    row = image.width * channels * bit_depth // 8
    # each row starts with its filter type, 0 for none
    scanlines = b"".join(b"\0" + data[i : i + row] for i in range(0, len(data), row))
    header = struct.pack(">IIBBBBB", image.width, image.height, bit_depth, color_type, 0, 0, 0)
    return b"".join(
        [
            b"\x89PNG\r\n\x1a\n",
            _chunk(b"IHDR", header),
            _chunk(b"IDAT", zlib.compress(scanlines)),
            _chunk(b"IEND", b""),
        ]
    )


def _chunk(kind: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(kind + data)
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)
