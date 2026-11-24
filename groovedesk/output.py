"""Download rows and a source-space annotation copy without modifying the original."""

import csv
from io import StringIO
from math import cos, radians, sin

from PIL import ImageDraw


def clean_cell(value):
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value


def csv_text(result):
    buffer = StringIO(newline="")
    writer = csv.writer(buffer)
    table_keys = (("columns", "rows"), ("direction_columns", "direction_rows"),
                  ("boundary_columns", "boundary_rows"))
    for index, (columns_key, rows_key) in enumerate(table_keys):
        columns = result.get(columns_key)
        rows = result.get(rows_key)
        if not columns or not rows:
            continue
        if index:
            writer.writerow([])
        writer.writerow([*(item["title"] for item in columns), "原图 X px", "原图 Y px"])
        for item in rows:
            point = item.get("point") or ["", ""]
            writer.writerow([*(clean_cell(item.get(column["key"])) for column in columns), *point])
    return "﻿" + buffer.getvalue()


def overlay(image, result):
    image = image.convert("RGB")
    brush = ImageDraw.Draw(image)
    settings = result["settings"]
    cx, cy = settings["center"][0] * (image.width - 1), settings["center"][1] * (image.height - 1)
    unit = min(image.width - 1, image.height - 1)
    green = (102, 224, 183)
    orange = (255, 184, 106)
    purple = (176, 151, 255)
    for boundary in ("inner", "outer"):
        radius = settings[boundary] * unit
        brush.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline=green, width=2)
    angle = radians(settings["phase"])
    radius = unit * settings["outer"]
    brush.line(((cx, cy), (cx + radius * sin(angle), cy - radius * cos(angle))), fill=green, width=2)
    if result["mode"] == "bands":
        for item in result.get("direction_rows", []):
            x, y = item["point"]
            brush.line(((cx, cy), (x, y)), fill=purple, width=1)
        for item in result.get("boundary_rows", []):
            key = "band_outer" if item["side"] == "外边界" else "band_inner"
            ring_radius = settings.get(key)
            if ring_radius is None:
                continue
            r = ring_radius * unit
            brush.ellipse((cx - r, cy - r, cx + r, cy + r), outline=orange, width=2)
            if item.get("point"):
                x, y = item["point"]
                brush.ellipse((x - 4, y - 4, x + 4, y + 4), outline=orange, width=2)
    for row in result["rows"]:
        x, y = row["point"]
        brush.ellipse((x - 3, y - 3, x + 3, y + 3), outline=orange, width=2)
    return image
