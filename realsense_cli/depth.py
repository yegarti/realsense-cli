"""
Depth queries over a few Z16 frames, with only the standard library.

A pixel's depth is the median of its non-zero samples across the frames: 0 is no depth, and a
pixel zero in every frame is invalid. Values stay in depth units until the caller scales them.
"""

import math
from array import array
from typing import NamedTuple

from realsense_cli.types import Image


class Region(NamedTuple):
    """A rectangle of pixels: its top-left corner, width and height"""

    x: int
    y: int
    width: int
    height: int

    def __str__(self):
        return f"{self.x},{self.y},{self.width},{self.height}"


class RegionStats(NamedTuple):
    """
    The depths of a region's valid pixels, in depth units; each statistic is None when no
    pixel is valid
    """

    pixels: int
    valid_pixels: int
    min: float | None
    max: float | None
    mean: float | None
    median: float | None
    stddev: float | None  # population standard deviation

    @property
    def fill_rate(self) -> float:
        return self.valid_pixels / self.pixels


def pixel_samples(images: list[Image], x: int, y: int) -> list[int]:
    """The non-zero depths pixel (X, Y) has across IMAGES"""
    samples = (_depths(image)[y * image.width + x] for image in images)
    return [sample for sample in samples if sample]


def median(values: list[int] | list[float]) -> float:
    """The median of VALUES, which must be sorted and not empty"""
    mid = len(values) // 2
    if len(values) % 2:
        return float(values[mid])
    return (values[mid - 1] + values[mid]) / 2


def region_stats(images: list[Image], region: Region) -> RegionStats:
    """
    Statistics of REGION's combined depth map: each pixel the median of its non-zero
    samples across IMAGES
    """
    frames = [_depths(image) for image in images]
    width = images[0].width
    depths: list[float] = []
    for y in range(region.y, region.y + region.height):
        start = y * width + region.x
        rows = [frame[start : start + region.width] for frame in frames]
        for samples in zip(*rows, strict=True):
            valid = sorted(sample for sample in samples if sample)
            if valid:
                depths.append(median(valid))

    pixels = region.width * region.height
    if not depths:
        return RegionStats(pixels, 0, None, None, None, None, None)
    depths.sort()
    mean = math.fsum(depths) / len(depths)
    variance = math.fsum((depth - mean) ** 2 for depth in depths) / len(depths)
    return RegionStats(
        pixels=pixels,
        valid_pixels=len(depths),
        min=depths[0],
        max=depths[-1],
        mean=mean,
        median=median(depths),
        stddev=math.sqrt(variance),
    )


def _depths(image: Image) -> array:
    # Z16 holds 16-bit values in the machine's byte order, as `array` reads them
    return array("H", image.data)
