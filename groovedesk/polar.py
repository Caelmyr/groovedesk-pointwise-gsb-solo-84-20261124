"""Sample a circular disk in clockwise angle and source-pixel radius."""

from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image

from .photo import pixel_values

WIDTH = 960
HEIGHT = 160


@dataclass(frozen=True)
class Disk:
    pixels: np.ndarray
    settings: dict

    @property
    def width(self):
        return self.pixels.shape[1]

    @property
    def height(self):
        return self.pixels.shape[0]

    @property
    def unit(self):
        return min(self.width - 1, self.height - 1)

    @property
    def center(self):
        x, y = self.settings["center"]
        return x * (self.width - 1), y * (self.height - 1)

    def source_xy(self, angles, radii):
        x, y = self.center
        degrees = np.deg2rad(angles)
        return x + self.unit * radii * np.sin(degrees), y - self.unit * radii * np.cos(degrees)

    def point(self, angle, radius):
        x, y = self.source_xy(angle, radius)
        return [round(float(x), 3), round(float(y), 3)]

    def sample(self, angles, radii):
        x, y = self.source_xy(np.asarray(angles)[None, :], np.asarray(radii)[:, None])
        valid = (x >= 0) & (x <= self.width - 1) & (y >= 0) & (y <= self.height - 1)
        samples = cv2.remap(self.pixels, x.astype(np.float32), y.astype(np.float32), cv2.INTER_LINEAR)
        return samples, valid


def open_disk(path, settings):
    with Image.open(path) as image:
        return Disk(pixel_values(image), settings)


def angles(start, sweep, count):
    return start + np.arange(count) * sweep / count


def unroll(disk, start=0, sweep=360, width=WIDTH, radial_bounds=None):
    settings = disk.settings
    if radial_bounds is None:
        outer, inner = settings["outer"], settings["inner"]
    else:
        outer, inner = radial_bounds
    samples, valid = disk.sample(angles(settings["phase"] + start, sweep, width),
                                 np.linspace(outer, inner, HEIGHT))
    pixels = np.rint(np.clip(samples, 0, 1) * 255).astype(np.uint8)
    if pixels.ndim == 2:
        pixels = np.repeat(pixels[..., None], 3, axis=2)
    alpha = np.where(valid, 255, 0).astype(np.uint8)
    return Image.fromarray(np.dstack((pixels, alpha)))


def sector_segments(start, span, phase):
    left = (start - phase) % 360
    right = left + span
    if right <= 360:
        return [[left, right]]
    return [[left, 360], [0, right - 360]]
