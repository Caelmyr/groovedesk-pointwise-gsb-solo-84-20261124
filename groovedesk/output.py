"""Download rows and a source-space annotation copy without modifying the original."""

import csv
from io import StringIO
from math import cos, radians, sin

from PIL import Image, ImageDraw


def clean_cell(value):
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value


def csv_text(result):
    buffer = StringIO(newline="")
    writer = csv.writer(buffer)
    columns = result["columns"]
    rows = result.get("rows")
    if rows is None and result.get("mode") == "crosscheck":
        rows = result["segments"]
        writer.writerow([item["title"] for item in columns] +
                        ["A 图 X px", "A 图 Y px", "B 图 X px", "B 图 Y px"])
        for item in rows:
            writer.writerow([*(clean_cell(item.get(column["key"])) for column in columns),
                             *item["point"], *item["point_b"]])
        return "\ufeff" + buffer.getvalue()
    writer.writerow([*(item["title"] for item in columns), "原图 X px", "原图 Y px"])
    for item in rows:
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


KIND_COLORS = {"joint": (255, 184, 106), "a": (110, 196, 240), "b": (180, 150, 244)}


def crosscheck_overlay(primary, companion, result):
    """Side-by-side originals with the analyzed mark and evidence segments."""
    gap = 24
    height = max(primary.height, companion.height)
    canvas = Image.new("RGB", (primary.width + companion.width + gap, height), (245, 242, 236))
    canvas.paste(primary, (0, 0))
    canvas.paste(companion, (primary.width + gap, 0))
    brush = ImageDraw.Draw(canvas)
    green = (102, 224, 183)
    anchor_segment = None
    if result.get("default"):
        anchor_segment = next((item for item in result["segments"]
                               if item["id"] == result["default"]["segment"]), None)
    if anchor_segment is None and result["segments"]:
        anchor_segment = result["segments"][0]

    def geometry(settings, image):
        cx, cy = settings["center"][0] * (image.width - 1), settings["center"][1] * (image.height - 1)
        unit = min(image.width - 1, image.height - 1)
        return cx, cy, unit

    def draw_frame(settings, image, offset_x, view):
        cx, cy, unit = geometry(settings, image)
        for boundary in ("inner", "outer"):
            radius = settings[boundary] * unit
            brush.ellipse((cx + offset_x - radius, cy - radius, cx + offset_x + radius, cy + radius),
                          outline=green, width=2)
        angle = radians(settings["phase"])
        brush.line(((cx + offset_x, cy),
                    (cx + offset_x + unit * settings["outer"] * sin(angle),
                     cy - unit * settings["outer"] * cos(angle))), fill=green, width=2)
        for segment in result["segments"]:
            color = KIND_COLORS[segment["kind"]]
            points = [(x + offset_x, y) for x, y in segment["corners"][view]]
            brush.line(points + [points[0]], fill=color, width=3)
            anchor = points[0]
            brush.text((anchor[0] + 4, anchor[1] - 14), segment["id"], fill=color)
        if anchor_segment is not None:
            mx, my = anchor_segment["point"] if view == "a" else anchor_segment["point_b"]
            brush.ellipse((mx + offset_x - 3, my - 3, mx + offset_x + 3, my + 3),
                          outline=(255, 184, 106), width=2)

    draw_frame(result["settings"], primary, 0, "a")
    draw_frame(result["companion_settings"], companion, primary.width + gap, "b")
    brush.text((8, 6), f"A {result.get('panel_title', '')}", fill=(37, 43, 39))
    brush.text((primary.width + gap + 8, 6), f"B {result.get('companion_title', '')}", fill=(37, 43, 39))
    return canvas
