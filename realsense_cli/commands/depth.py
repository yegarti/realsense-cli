from typing import Annotated, Any

import typer

from realsense_cli.commands.capture import collect, profile_payload
from realsense_cli.console import err_console
from realsense_cli.depth import Region, median, pixel_samples, region_stats
from realsense_cli.errors import InvalidProfile, InvalidValue
from realsense_cli.printer import depth_query, emit
from realsense_cli.session import require_device
from realsense_cli.types import Image, Profile, Resolution, Stream


def _parse_region(value: str) -> Region:
    try:
        x, y, width, height = (int(n) for n in value.split(","))
    except ValueError:
        raise typer.BadParameter(
            f"'{value}' is not X,Y,W,H: four integers, e.g. 100,80,40,30"
        ) from None
    if width < 1 or height < 1:
        raise typer.BadParameter(f"width and height must be at least 1, got '{value}'")
    return Region(x, y, width, height)


def rs_depth(
    ctx: typer.Context,
    x: Annotated[
        int | None, typer.Argument(metavar="X", help="Pixel column", show_default=False)
    ] = None,
    y: Annotated[
        int | None, typer.Argument(metavar="Y", help="Pixel row", show_default=False)
    ] = None,
    roi: Annotated[
        Region | None,
        typer.Option(
            "--roi",
            metavar="X,Y,W,H",
            help="Region to report on: top-left corner, width and height",
            show_default=False,
            parser=_parse_region,
        ),
    ] = None,
    frames: Annotated[int, typer.Option("--frames", min=1, help="Frames to combine")] = 10,
    warmup: Annotated[
        float,
        typer.Option(
            "--warmup",
            min=0,
            help="Seconds of frames to discard first, while auto-exposure settles",
        ),
    ] = 1.0,
) -> None:
    """
    Measure the depth at a pixel, or over a region\n
    \n
    `rs depth X Y` reports one pixel of the depth image, `rs depth --roi X,Y,W,H` a region;
    with neither, the region is the whole image. Each pixel's depth is the median of its
    non-zero samples across --frames frames, taken after --warmup seconds. Depths are in
    meters; a pixel without depth in any frame has none.
    """
    if (x is None) != (y is None):
        raise typer.BadParameter("give both X and Y, or neither", param_hint="'X Y'")
    if x is not None and roi is not None:
        raise typer.BadParameter("can't be combined with X Y", param_hint="'--roi'")
    driver = require_device(ctx)
    scale = driver.depth_scale()
    if scale is None:
        raise InvalidProfile("The device has no depth sensor")

    [profile] = driver.play([Profile(Stream.DEPTH, format="z16")])
    try:
        if x is not None and y is not None:
            _check_pixel(x, y, profile.resolution)
        else:
            roi = roi or Region(0, 0, *profile.resolution)
            _check_region(roi, profile.resolution)
        err_console.print("Warming up")
        framesets = collect(driver, [profile.stream], frames, warmup)
    finally:
        err_console.print("Stopping all streams")
        driver.stop()

    images: list[Image] = []
    for frameset in framesets:
        image = frameset[profile.stream].image
        assert image is not None, "collect() asks for images"
        images.append(image)
    payload: dict[str, Any] = {
        "profiles": [profile_payload(profile)],
        "frames": frames,
        "depth_scale": scale,
    }
    if x is not None and y is not None:
        payload |= _pixel_payload(images, x, y, scale)
    else:
        assert roi is not None
        payload |= _region_payload(images, roi, scale)
    emit(ctx, payload, lambda: depth_query(payload))


def _check_pixel(x: int, y: int, resolution: Resolution) -> None:
    width, height = resolution
    if not (0 <= x < width and 0 <= y < height):
        raise InvalidValue(
            f"Pixel ({x}, {y}) is outside the {resolution} depth image: "
            f"X must be 0 to {width - 1} and Y 0 to {height - 1}"
        )


def _check_region(region: Region, resolution: Resolution) -> None:
    width, height = resolution
    if not (
        0 <= region.x
        and 0 <= region.y
        and region.x + region.width <= width
        and region.y + region.height <= height
    ):
        raise InvalidValue(
            f"Region {region} reaches outside the {resolution} depth image: X and Y must be "
            f"at least 0, X + W at most {width} and Y + H at most {height}"
        )


def _meters(depth: float | None, scale: float) -> float | None:
    return None if depth is None else round(depth * scale, 4)


def _pixel_payload(images: list[Image], x: int, y: int, scale: float) -> dict[str, Any]:
    samples = sorted(pixel_samples(images, x, y))
    depth = median(samples) if samples else None
    return {
        "depth": _meters(depth, scale),
        "pixel": {"x": x, "y": y, "samples": len(samples)},
    }


def _region_payload(images: list[Image], region: Region, scale: float) -> dict[str, Any]:
    stats = region_stats(images, region)
    return {
        "depth": _meters(stats.median, scale),
        "region": {
            **region._asdict(),
            "pixels": stats.pixels,
            "valid_pixels": stats.valid_pixels,
            "fill_rate": round(stats.fill_rate, 4),
            "min": _meters(stats.min, scale),
            "max": _meters(stats.max, scale),
            "mean": _meters(stats.mean, scale),
            "median": _meters(stats.median, scale),
            "stddev": _meters(stats.stddev, scale),
        },
    }
