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


def unroll(disk, start=0, sweep=360, width=WIDTH):
    settings = disk.settings
    samples, valid = disk.sample(angles(settings["phase"] + start, sweep, width),
                                 np.linspace(settings["outer"], settings["inner"], HEIGHT))
    pixels = np.rint(np.clip(samples, 0, 1) * 255).astype(np.uint8)
    if pixels.ndim == 2:
        pixels = np.repeat(pixels[..., None], 3, axis=2)
    alpha = np.where(valid, 255, 0).astype(np.uint8)
    return Image.fromarray(np.dstack((pixels, alpha)))


def sector_segments(start, span, origin):
    left = (start - origin) % 360
    right = left + span
    if right <= 360:
        return [[left, right]]
    return [[left, 360], [0, right - 360]]


def suggest_seam(settings):
    """Choose a strip seam, in degrees from the phase zero, that spares marked sectors.

    Fewest marks cut wins; ties go to the widest clear interval so the seam sits
    mid-gap with intact surface on both sides, then to the lowest angle.  Margins
    report the clear degrees from the seam to the nearest mark edge on each side.
    """
    phase = settings["phase"]
    intervals = [(mark["id"], (mark["start"] - phase) % 360, mark["span"])
                 for mark in settings.get("marks", [])]
    if not intervals:
        return {"seam": 0.0, "cut": [], "left": None, "right": None}

    def cut_at(angle):
        return [name for name, start, span in intervals
                if 1e-9 < (angle - start) % 360 < span - 1e-9]

    edges = sorted({edge % 360 for _, start, span in intervals for edge in (start, start + span)})
    best = None
    for index, low in enumerate(edges):
        high = edges[(index + 1) % len(edges)] + (360 if index + 1 == len(edges) else 0)
        if high - low <= 0:
            continue
        mid = low + (high - low) / 2
        candidate = (len(cut_at(mid % 360)), low - high, mid % 360)
        if best is None or candidate < best:
            best = candidate
    seam = round(best[2], 1)
    left = round(min((seam - edge) % 360 for edge in edges), 1)
    right = round(min((edge - seam) % 360 for edge in edges), 1)
    return {"seam": seam, "cut": cut_at(seam), "left": left, "right": right}
