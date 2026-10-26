"""
NPY encoding of video frames, with only the standard library.
"""

import struct
import sys

from realsense_cli.types import Image

# rs.format name: (NumPy dtype kind and size, channels)
_FORMATS: dict[str, tuple[str, int]] = {
    "z16": ("u2", 1),
    "y16": ("u2", 1),
    "y8": ("u1", 1),
    "rgb8": ("u1", 3),
    "bgr8": ("u1", 3),
    "rgba8": ("u1", 4),
    "bgra8": ("u1", 4),
    "yuyv": ("u1", 2),
}

FORMATS = tuple(_FORMATS)
"""The formats `encode` takes, as `rs.format` names"""

_MAGIC = b"\x93NUMPY\x01\x00"  # format version 1.0


def encode(image: Image) -> bytes:
    """
    IMAGE as an NPY file holding the frame's values as the camera sent them: uint16 (H, W) for
    Z16 and Y16, uint8 (H, W) for Y8, uint8 (H, W, 2) for YUYV (Y0 U, Y1 V ... per pixel pair),
    uint8 (H, W, 3) or (H, W, 4) for the others, BGR(A) channels left in BGR(A) order
    """
    kind, channels = _FORMATS[image.format]
    shape = (image.height, image.width) + ((channels,) if channels > 1 else ())
    # the frame holds 16-bit values in the machine's byte order; bytes have none
    order = "|" if kind == "u1" else "<" if sys.byteorder == "little" else ">"
    header = f"{{'descr': '{order}{kind}', 'fortran_order': False, 'shape': {shape}, }}"
    # the header ends in a newline and is padded with spaces so the data starts 64-byte aligned
    prefix = len(_MAGIC) + 2
    header += " " * (-(prefix + len(header) + 1) % 64) + "\n"
    return _MAGIC + struct.pack("<H", len(header)) + header.encode("latin1") + image.data
