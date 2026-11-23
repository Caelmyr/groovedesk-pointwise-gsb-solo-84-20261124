"""Read circular surface marks, illumination, rim and radial texture from a photo."""

import numpy as np

from . import model, polar


def luminance(samples):
    if samples.ndim == 2:
        return samples
    return samples @ np.array([.2126, .7152, .0722], dtype=np.float32)


def column(title, key):
    return {"title": title, "key": key}


def digits(value):
    return round(float(value), 3)


def visible_point(disk, angle, radius):
    return disk.point(angle, radius)


def surface(disk):
    settings = disk.settings
    rows = []
    for mark in settings["marks"]:
        angle = (mark["start"] + mark["span"] / 2) % 360
        radius = (mark["inner"] + mark["outer"]) / 2
        radial_mm = settings["diameter"] * (mark["outer"] - mark["inner"]) / (2 * settings["outer"])
        rows.append({
            "id": mark["id"], "kind": model.MARKS[mark["kind"]], "angle": digits((angle - settings["phase"]) % 360),
            "span": mark["span"], "width": digits(radial_mm),
            "point": visible_point(disk, angle, radius),
            "segments": polar.sector_segments(mark["start"], mark["span"], settings["phase"]),
        })
    return [column("标记", "id"), column("类别", "kind"), column("角度 °", "angle"),
            column("角宽 °", "span"), column("径向宽 mm", "width")], rows


def lighting(disk):
    settings = disk.settings
    phase = settings["phase"]
    angles = polar.angles(phase, 360, 144)
    samples, valid = disk.sample(angles, np.linspace(settings["inner"], settings["outer"], 67))
    tiles = luminance(samples)
    rows = []
    for sector in range(12):
        sl = slice(sector * 12, (sector + 1) * 12)
        values = tiles[:, sl][valid[:, sl]]
        angle = sector * 30 + 15
        rows.append({
            "angle": angle, "valid": digits(valid[:, sl].mean() * 100),
            "median": digits(np.median(values) * 100) if len(values) else None,
            "dark": digits(np.mean(values < .035) * 100) if len(values) else None,
            "bright": digits(np.mean(values > .95) * 100) if len(values) else None,
            "point": visible_point(disk, phase + angle, (settings["inner"] + settings["outer"]) / 2),
        })
    return [column("扇区中心 °", "angle"), column("入画 %", "valid"), column("中值 %", "median"),
            column("近黑 %", "dark"), column("近白 %", "bright")], rows


def rim(disk):
    settings = disk.settings
    phase = settings["phase"]
    outer = settings["outer"]
    padding = 0.031
    radii = np.linspace(outer - padding, outer + padding, 91)
    angles = polar.angles(phase, 360, 120)
    samples, valid = disk.sample(angles, radii)
    difference = np.diff(luminance(samples), axis=0)
    difference[~(valid[1:] & valid[:-1])] = -1
    rows = []
    for index, angle in enumerate(angles):
        offset = int(np.argmax(difference[:, index]))
        edge = difference[offset, index]
        radius = (radii[offset] + radii[offset + 1]) / 2
        read = edge >= .026
        rows.append({
            "angle": digits((angle - phase) % 360),
            "radius": digits(radius * disk.unit) if read else None,
            "delta": digits((radius - outer) * settings["diameter"] / (2 * outer)) if read else None,
            "edge": digits(max(edge, 0) * 100),
            "point": visible_point(disk, angle, radius if read else outer),
        })
    return [column("方向 °", "angle"), column("盘缘半径 px", "radius"), column("距设定外圈 mm", "delta"),
            column("边缘对比 %", "edge")], rows


def grooves(disk):
    settings = disk.settings
    phase = settings["phase"]
    radii = np.linspace(settings["inner"], settings["outer"], 97)
    samples, valid = disk.sample(polar.angles(phase, 360, 360), radii)
    response = abs(np.diff(luminance(samples), axis=0))
    rows = []
    mid = phase + 180
    for index in range(0, len(response), 3):
        mask = valid[index:index + 3] & valid[index + 1:index + 4]
        slab = response[index:index + 3][mask]
        radius = float(np.mean(radii[index:index + 4]))
        rows.append({
            "radius": digits(radius * disk.unit), "response": digits(slab.mean() * 100) if len(slab) else None,
            "valid": digits(mask.mean() * 100), "point": visible_point(disk, mid, radius),
        })
    return [column("半径 px", "radius"), column("相邻径向变化 %", "response"), column("入画 %", "valid")], rows


def slice_report(disk):
    settings = disk.settings
    start = settings["phase"] + settings["angle"]
    center = start + settings["span"] / 2
    samples, valid = disk.sample(polar.angles(start, settings["span"], 240),
                                 np.linspace(settings["inner"], settings["outer"], 90))
    observed = luminance(samples)[valid]
    row = {"start": settings["angle"], "sweep": settings["span"], "valid": digits(valid.mean() * 100),
           "light": digits(observed.mean() * 100) if len(observed) else None,
           "point": visible_point(disk, center, (settings["inner"] + settings["outer"]) / 2)}
    return [column("起角 °", "start"), column("角宽 °", "sweep"),
            column("入画 %", "valid"), column("平均光度 %", "light")], [row]


READERS = {"surface": surface, "lighting": lighting, "rim": rim, "grooves": grooves, "slice": slice_report}


def report(disk, mode):
    columns, rows = READERS[mode](disk)
    return {"mode": mode, "heading": model.MODES[mode], "columns": columns, "rows": rows,
            "settings": disk.settings, "width": disk.width, "height": disk.height,
            "source_space": "oriented_original_pixels"}
