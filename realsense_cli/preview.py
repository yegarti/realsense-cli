"""
Terminal previews of video frames, with only the standard library: truecolor half-blocks, two
pixels per cell, or an ASCII ramp of brightness. Only the pixels drawn are read (nearest
neighbour), which keeps plain Python fast enough for a live view.
"""

from enum import StrEnum

from rich.console import Console

from realsense_cli.types import Frame, Image

RAMP = " .:-=+*#%@"
"""ASCII characters from dark to bright, as rs-depth draws depth"""

HALF_BLOCK = "▀"


class PreviewMode(StrEnum):
    AUTO = "auto"
    HALFBLOCK = "halfblock"
    ASCII = "ascii"


FORMATS = ("rgb8", "bgr8", "rgba8", "bgra8", "y8", "yuyv")
"""The formats a preview draws, as `rs.format` names; depth is drawn from its colorized image"""

RGB = tuple[int, int, int]


def choose_mode(console: Console) -> PreviewMode:
    """
    Half-blocks on a console with any color, 256 colors included: a multiplexer such as Zellij
    reports TERM=xterm-256color while passing truecolor through. ASCII on one without color
    """
    if console.color_system is None or console.no_color:
        return PreviewMode.ASCII
    return PreviewMode.HALFBLOCK


def preview_image(frame: Frame) -> Image | None:
    """The image a preview draws for FRAME: a depth frame's colorized one, else its own"""
    return frame.colorized or frame.image


def fit(width: int, height: int, cols: int, rows: int) -> tuple[int, int]:
    """
    The cells, as (columns, rows), that a WIDTHxHEIGHT image takes within COLS x ROWS cells,
    keeping its aspect ratio: a cell is one pixel wide and two tall, as terminal cells are about
    twice as tall as wide. Never more pixels than the image has; at least one cell
    """
    scale = min(cols / width, rows * 2 / height, 1.0)
    return max(1, int(width * scale)), max(1, int(height * scale / 2))


def render(image: Image, mode: PreviewMode, cols: int, rows: int) -> list[str]:
    """
    IMAGE fitted into COLS x ROWS cells as lines of text in MODE (HALFBLOCK or ASCII); a
    one-line notice for a format it can't draw
    """
    if image.format not in FORMATS:
        return [f"no preview for {image.format}"]
    cols, rows = fit(image.width, image.height, cols, rows)
    if mode is PreviewMode.ASCII:
        return ascii_art(image, cols, rows)
    return halfblock(image, cols, rows)


def halfblock(image: Image, cols: int, rows: int) -> list[str]:
    """
    IMAGE scaled to COLS x ROWS cells of `▀`: each cell's foreground is the upper pixel, its
    background the lower one, in 24-bit color. A run of equal cells sets its colors once
    """
    pixels = _sample(image, cols, rows * 2)
    lines = []
    for top, bottom in zip(pixels[0::2], pixels[1::2], strict=True):
        parts: list[str] = []
        last = None
        for upper, lower in zip(top, bottom, strict=True):
            if (upper, lower) != last:
                parts.append(
                    f"\x1b[38;2;{upper[0]};{upper[1]};{upper[2]};"
                    f"48;2;{lower[0]};{lower[1]};{lower[2]}m"
                )
                last = (upper, lower)
            parts.append(HALF_BLOCK)
        parts.append("\x1b[0m")
        lines.append("".join(parts))
    return lines


def ascii_art(image: Image, cols: int, rows: int) -> list[str]:
    """IMAGE scaled to COLS x ROWS characters of RAMP, by each pixel's brightness"""
    last = len(RAMP) - 1
    return [
        "".join(RAMP[(299 * r + 587 * g + 114 * b) * last // 255_000] for r, g, b in row)
        for row in _sample(image, cols, rows)
    ]


def _sample(image: Image, cols: int, rows: int) -> list[list[RGB]]:
    """The ROWS x COLS pixels of IMAGE nearest to an even grid over it, as RGB"""
    width, data = image.width, image.data
    xs = [(2 * i + 1) * width // (2 * cols) for i in range(cols)]
    ys = [(2 * j + 1) * image.height // (2 * rows) for j in range(rows)]
    match image.format:
        case "rgb8" | "bgr8" | "rgba8" | "bgra8":
            size = 4 if image.format.endswith("a8") else 3
            red, blue = (2, 0) if image.format.startswith("bgr") else (0, 2)
            return [
                [
                    (data[i + red], data[i + 1], data[i + blue])
                    for i in (y * width * size + x * size for x in xs)
                ]
                for y in ys
            ]
        case "y8":
            return [[(v, v, v) for v in (data[y * width + x] for x in xs)] for y in ys]
        case "yuyv":
            # Y0 U Y1 V: two pixels share their U and V
            return [
                [
                    _yuv(data[i + x % 2 * 2], data[i + 1], data[i + 3])
                    for i, x in _pairs(xs, y, width)
                ]
                for y in ys
            ]
    raise ValueError(f"no preview for {image.format}")


def _pairs(xs: list[int], y: int, width: int):
    """For each column in XS of row Y, the offset of its YUYV pair and the column"""
    return (((y * width + x - x % 2) * 2, x) for x in xs)


def _yuv(y: int, u: int, v: int) -> RGB:
    """BT.601 limited-range YUV as RGB, librealsense's YUY2 conversion"""
    c, d, e = y - 16, u - 128, v - 128
    return (
        _clamp((298 * c + 409 * e + 128) >> 8),
        _clamp((298 * c - 100 * d - 208 * e + 128) >> 8),
        _clamp((298 * c + 516 * d + 128) >> 8),
    )


def _clamp(value: int) -> int:
    return 0 if value < 0 else 255 if value > 255 else value
