import io

import pytest
from rich.console import Console

from realsense_cli.preview import (
    HALF_BLOCK,
    PreviewMode,
    ascii_art,
    choose_mode,
    fit,
    halfblock,
    render,
)
from realsense_cli.stream_view import PreviewLive, StreamView
from realsense_cli.types import Frame, Image, Profile, Resolution


def sgr(upper, lower):
    return f"\x1b[38;2;{upper[0]};{upper[1]};{upper[2]};48;2;{lower[0]};{lower[1]};{lower[2]}m"


RED, GREEN, BLUE, WHITE = (255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255)


def rgb_image(rows: list[list[tuple[int, int, int]]], fmt: str = "rgb8") -> Image:
    """An image of ROWS of RGB pixels, stored in FMT"""
    data = bytearray()
    for row in rows:
        for r, g, b in row:
            match fmt:
                case "rgb8":
                    data += bytes((r, g, b))
                case "bgr8":
                    data += bytes((b, g, r))
                case "rgba8":
                    data += bytes((r, g, b, 7))
                case "bgra8":
                    data += bytes((b, g, r, 7))
    return Image(len(rows[0]), len(rows), fmt, bytes(data))


def test_halfblock_cell_holds_upper_and_lower_pixel():
    image = rgb_image([[RED, GREEN], [BLUE, WHITE]])
    assert halfblock(image, 2, 1) == [
        sgr(RED, BLUE) + HALF_BLOCK + sgr(GREEN, WHITE) + HALF_BLOCK + "\x1b[0m"
    ]


def test_halfblock_sets_colors_once_per_run():
    image = rgb_image([[RED] * 3, [BLUE] * 3])
    assert halfblock(image, 3, 1) == [sgr(RED, BLUE) + HALF_BLOCK * 3 + "\x1b[0m"]


@pytest.mark.parametrize("fmt", ["rgb8", "bgr8", "rgba8", "bgra8"])
def test_halfblock_reads_each_color_format(fmt):
    image = rgb_image([[RED], [BLUE]], fmt)
    assert halfblock(image, 1, 1) == [sgr(RED, BLUE) + HALF_BLOCK + "\x1b[0m"]


def test_halfblock_samples_nearest_pixels():
    # 4x4 down to 2x1 cells: the pixels at (1, 1), (3, 1), (1, 3) and (3, 3)
    pixels = [[(x * 10, y * 10, 0) for x in range(4)] for y in range(4)]
    assert halfblock(rgb_image(pixels), 2, 1) == [
        sgr((10, 10, 0), (10, 30, 0))
        + HALF_BLOCK
        + sgr((30, 10, 0), (30, 30, 0))
        + HALF_BLOCK
        + "\x1b[0m"
    ]


def test_y8_is_gray():
    image = Image(1, 2, "y8", bytes((40, 200)))
    assert halfblock(image, 1, 1) == [sgr((40,) * 3, (200,) * 3) + HALF_BLOCK + "\x1b[0m"]


def test_yuyv_converts_as_librealsense():
    # Y0 U Y1 V: black and white share neutral chroma; then pure-ish red
    image = Image(2, 2, "yuyv", bytes((16, 128, 235, 128, 81, 90, 81, 240)))
    assert halfblock(image, 2, 1) == [
        sgr((0, 0, 0), (255, 0, 0))
        + HALF_BLOCK
        + sgr((255, 255, 255), (255, 0, 0))
        + HALF_BLOCK
        + "\x1b[0m"
    ]


def test_ascii_maps_brightness_to_ramp():
    image = Image(3, 1, "y8", bytes((0, 128, 255)))
    assert ascii_art(image, 3, 1) == [" =@"]


@pytest.mark.parametrize(
    ("size", "area", "cells"),
    [
        ((640, 480), (80, 40), (80, 30)),  # width-bound, 4:3 kept with 1x2 px cells
        ((640, 480), (200, 20), (53, 20)),  # height-bound
        ((4, 2), (100, 100), (4, 1)),  # never larger than the image
        ((640, 480), (0, 0), (1, 1)),  # at least one cell
    ],
)
def test_fit_keeps_aspect(size, area, cells):
    assert fit(*size, *area) == cells


def test_render_fits_then_draws():
    image = Image(640, 480, "y8", bytes(640 * 480))
    lines = render(image, PreviewMode.ASCII, 80, 40)
    assert len(lines) == 30
    assert {len(line) for line in lines} == {80}


def test_render_notes_a_format_it_cannot_draw():
    image = Image(2, 2, "z16", bytes(8))
    assert render(image, PreviewMode.HALFBLOCK, 10, 10) == ["no preview for z16"]


@pytest.mark.parametrize(
    ("console", "mode"),
    [
        (
            Console(file=io.StringIO(), force_terminal=True, color_system="truecolor"),
            "halfblock",
        ),
        (Console(file=io.StringIO(), force_terminal=True, color_system="256"), "halfblock"),
        (Console(file=io.StringIO(), force_terminal=False), "ascii"),
        (Console(file=io.StringIO(), force_terminal=True, no_color=True), "ascii"),
    ],
)
def test_choose_mode_by_color(console, mode):
    assert choose_mode(console) == mode


def preview_live(fmt: str = "y8", width: int = 64, height: int = 48) -> PreviewLive:
    profile = Profile("Infrared 1", Resolution(width, height), 30, fmt, 1)
    # all white: drawn as `@`, unlike the padding around it
    image = Image(width, height, fmt, b"\xff" * width * height * (2 if fmt == "y16" else 1))
    frame = Frame(profile, timestamp=0, index=1, metadata={}, image=image)
    console = Console(file=io.StringIO(), force_terminal=False)
    live = PreviewLive(StreamView(["Infrared 1"]), "Infrared 1", PreviewMode.ASCII, console)
    live.update({"Infrared 1": frame})
    return live


def test_preview_draws_image_beside_panels():
    lines = preview_live().lines(100, 20)
    assert len(lines) == 20
    # the 64x48 image fits 20 rows at 53 columns; the panel starts right of it
    panel = lines[1].index("╭")
    assert panel > 53
    assert all(line[:53] == "@" * 53 and line[53:panel].strip() == "" for line in lines)


def test_preview_stacks_image_above_panels_when_narrow():
    lines = preview_live().lines(50, 30)
    assert len(lines) <= 30
    image = [line for line in lines if "@" in line]
    # the full width, with the rows the panels leave
    assert image == ["@" * 50] * len(image)
    assert lines[: len(image)] == image
    assert any("Infrared 1" in line for line in lines[len(image) :])


def test_preview_notes_unsupported_format_in_place_of_image():
    lines = preview_live("y16").lines(100, 20)
    assert lines[0].startswith("no preview for y16")


def test_preview_waits_for_first_frame():
    console = Console(file=io.StringIO(), force_terminal=False)
    live = PreviewLive(StreamView(["Depth"]), "Depth", PreviewMode.ASCII, console)
    assert live.lines(100, 10)[0].startswith("waiting for frames...")


def test_preview_on_terminal_draws_in_alternate_screen():
    out = io.StringIO()
    console = Console(
        file=out, force_terminal=True, color_system="truecolor", width=100, height=20
    )
    profile = Profile("Infrared 1", Resolution(64, 48), 30, "y8", 1)
    frame = Frame(profile, 0, 1, {}, image=Image(64, 48, "y8", b"\x80" * 64 * 48))
    live = PreviewLive(StreamView(["Infrared 1"]), "Infrared 1", PreviewMode.HALFBLOCK, console)
    live.update({"Infrared 1": frame})
    with live:
        pass
    text = out.getvalue()
    # enter the alternate screen, clear it on the first draw, then leave it
    assert text.startswith("\x1b[?1049h\x1b[?25l\x1b[2J\x1b[H")
    assert text.endswith("\x1b[0m\x1b[?25h\x1b[?1049l")
    assert sgr((128,) * 3, (128,) * 3) + HALF_BLOCK in text
    # one draw: nothing changed after it
    assert text.count("\x1b[H") == 1


def test_preview_image_too_small_for_its_area():
    lines = preview_live().lines(100, 0)
    assert lines == []
