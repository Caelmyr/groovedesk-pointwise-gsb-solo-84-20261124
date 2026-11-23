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
    columns = result["columns"]
    writer.writerow([*(item["title"] for item in columns), "原图 X px", "原图 Y px"])
    for item in result["rows"]:
        writer.writerow([*(clean_cell(item.get(column["key"])) for column in columns), *item["point"]])
    return "\ufeff" + buffer.getvalue()


def overlay(image, result):
    image = image.convert("RGB")
    brush = ImageDraw.Draw(image)
    settings = result["settings"]
    cx, cy = settings["center"][0] * (image.width - 1), settings["center"][1] * (image.height - 1)
    unit = min(image.width - 1, image.height - 1)
    green = (102, 224, 183)
    orange = (255, 184, 106)
    for boundary in ("inner", "outer"):
        radius = settings[boundary] * unit
        brush.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline=green, width=2)
    angle = radians(settings["phase"])
    radius = unit * settings["outer"]
    brush.line(((cx, cy), (cx + radius * sin(angle), cy - radius * cos(angle))), fill=green, width=2)
    for row in result["rows"]:
        x, y = row["point"]
        brush.ellipse((x - 3, y - 3, x + 3, y + 3), outline=orange, width=2)
    return image
