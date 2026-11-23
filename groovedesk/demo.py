"""Generate a reproducible, synthetic record photograph for local inspection."""

import numpy as np
from PIL import Image, ImageDraw

from . import model, photo


def image():
    size = 760
    y, x = np.mgrid[:size, :size]
    dx, dy = x - 378, y - 372
    radius = np.hypot(dx, dy)
    angle = np.degrees(np.arctan2(dx, -dy)) % 360
    rng = np.random.default_rng(117)
    light = 11 + 26 * np.clip(np.cos(np.deg2rad(angle - 57)), 0, 1) ** 4
    tracks = 4 * (1 + np.cos(radius * 2.7)) + 2 * np.sin(radius * 0.14)
    light = light + tracks + rng.normal(0, 1.2, radius.shape)
    for ring in (187, 229, 279, 323):
        light += 15 * np.exp(-((radius - ring) / 1.8) ** 2)
    wood = 72 + 6 * np.sin(0.04 * x) + 4 * np.cos((x + y) * 0.07)
    edge_angle = (angle >= 114) & (angle < 127)
    edge_depth = 6 * np.clip(1 - abs(angle - 120.5) / 6.5, 0, 1)
    on_record = radius < 349 - edge_angle * edge_depth
    rgb = np.stack([np.where(on_record, light + tone, wood + base)
                    for tone, base in [(0, 34), (2, 12), (5, -8)]], axis=2)
    for channels, bounds in [((130, 138, 153), ((angle >= 352) | (angle <= 16)) & (abs(radius - 264 - 0.29 * dx) < 0.9)),
                             ((111, 115, 120), (angle > 146) & (angle < 169) & (abs(radius - 213 - 0.09 * dx) < 0.8))]:
        rgb[bounds] = channels
    label = radius < 138
    rgb[label] = (96, 144, 142)
    rgb[(radius > 119) & (radius < 121)] = (190, 209, 188)
    rgb[(radius > 110) & (radius < 112)] = (190, 209, 188)
    canvas = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8))
    draw = ImageDraw.Draw(canvas)
    draw.ellipse((369, 363, 387, 381), fill=(49, 38, 31))
    draw.text((378, 321), "WORKSHOP  /  A", fill=(228, 235, 218), anchor="mm", font_size=17)
    draw.text((378, 405), "SYNTHETIC RECORD", fill=(224, 233, 218), anchor="mm", font_size=13)
    draw.text((378, 429), "33 1/3   RPM", fill=(224, 233, 218), anchor="mm", font_size=14)
    return canvas


def create(library):
    canvas = image()
    settings = {
        **model.DEFAULTS, "center": [378 / 759, 372 / 759], "inner": 0.215, "outer": 349 / 759,
        "marks": [
            {"id": "A-01", "kind": "scratch", "start": 351, "span": 27, "inner": 0.32, "outer": 0.39},
            {"id": "A-02", "kind": "chip", "start": 114, "span": 13, "inner": 0.445, "outer": 0.46},
            {"id": "A-03", "kind": "scratch", "start": 145, "span": 26, "inner": 0.245, "outer": 0.285},
        ],
    }
    return library.create("合成练习唱片", "practice-record.png", photo.png(canvas), canvas.size, settings, {"kind": "synthetic"})
