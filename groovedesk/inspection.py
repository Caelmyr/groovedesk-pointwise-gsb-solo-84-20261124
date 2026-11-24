"""Read circular surface marks, illumination, rim and radial texture from a photo."""

import numpy as np

from . import bands as banding, model, polar


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


def band_bounds(settings):
    """Effective slice radii: chosen band pair, falling back to the ring edges."""
    inner = settings["band_inner"] if settings["band_inner"] is not None else settings["inner"]
    outer = settings["band_outer"] if settings["band_outer"] is not None else settings["outer"]
    return inner, outer


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


def band_report(disk, target, anchor):
    settings = disk.settings
    found = banding.detect(disk, target, anchor)
    phase = settings["phase"]

    def line_point(line):
        return visible_point(disk, phase + found["anchor"], line["radius"]) if line else None

    rows = []
    for line in found["candidates"]:
        rows.append({
            "radius": digits(line["radius"] * disk.unit),
            "radius_norm": line["radius"],
            "support": line["support"], "span": line["span"],
            "prominence": digits(line["prominence"] * 100),
            "verdict": "完整" if line["reliable"] else "窄线/不完整",
            "directions": "、".join(str(index * 360 // banding.DIRECTION_COUNT) + "°"
                                    for index in line["directions"]),
            "point": visible_point(disk, phase + (line["angles"][0] if line["angles"] else 0), line["radius"]),
        })
    direction_rows = []
    for item in found["directions"]:
        peak_text = "；".join(f'{digits(peak["radius"] * disk.unit)}px' for peak in item["peaks"]) or "无达阈值峰"
        direction_rows.append({
            "direction": item["angle"], "coverage": item["coverage"],
            "threshold": digits(item["threshold"] * 100), "peaks": peak_text,
            "point": item["point"],
        })
    inner_line, outer_line = found["inner_line"], found["outer_line"]
    boundary_rows = [
        {"side": "内边界", "radius": digits(inner_line["radius"] * disk.unit) if inner_line else None,
         "support": inner_line["support"] if inner_line else 0,
         "missing": settings["band_inner_missing"], "note": found["inner_note"],
         "point": line_point(inner_line)},
        {"side": "外边界", "radius": digits(outer_line["radius"] * disk.unit) if outer_line else None,
         "support": outer_line["support"] if outer_line else 0,
         "missing": settings["band_outer_missing"], "note": found["outer_note"],
         "point": line_point(outer_line)},
    ]
    columns = [column("候选半径 px", "radius"), column("支持方向数", "support"),
               column("角覆盖 °", "span"), column("峰强度 %", "prominence"),
               column("判定", "verdict"), column("出现方向", "directions")]
    direction_columns = [column("核对方向 °", "direction"), column("入画 %", "coverage"),
                         column("阈值 %", "threshold"), column("该方向峰位", "peaks")]
    boundary_columns = [column("边界", "side"), column("采用半径 px", "radius"),
                        column("支持方向数", "support"), column("缺边", "missing"), column("判断依据", "note")]
    return {
        "mode": "bands", "heading": model.MODES["bands"],
        "columns": columns, "rows": rows,
        "direction_columns": direction_columns, "direction_rows": direction_rows,
        "boundary_columns": boundary_columns, "boundary_rows": boundary_rows,
        "detection": found,
        "settings": disk.settings, "width": disk.width, "height": disk.height,
        "source_space": "oriented_original_pixels",
    }


def slice_report(disk):
    settings = disk.settings
    start = settings["phase"] + settings["angle"]
    center = start + settings["span"] / 2
    bound_inner, bound_outer = band_bounds(settings)
    samples, valid = disk.sample(polar.angles(start, settings["span"], 240),
                                 np.linspace(bound_inner, bound_outer, 90))
    observed = luminance(samples)[valid]
    row = {"start": settings["angle"], "sweep": settings["span"], "valid": digits(valid.mean() * 100),
           "light": digits(observed.mean() * 100) if len(observed) else None,
           "point": visible_point(disk, center, (bound_inner + bound_outer) / 2)}
    return [column("起角 °", "start"), column("角宽 °", "sweep"),
            column("入画 %", "valid"), column("平均光度 %", "light")], [row]


READERS = {"surface": surface, "lighting": lighting, "rim": rim, "grooves": grooves, "slice": slice_report}


def report(disk, mode, target=None, anchor=None):
    if mode == "bands":
        if target is None:
            target = (disk.settings["inner"] + disk.settings["outer"]) / 2
        return band_report(disk, float(target), float(anchor if anchor is not None else 0.0))
    columns, rows = READERS[mode](disk)
    return {"mode": mode, "heading": model.MODES[mode], "columns": columns, "rows": rows,
            "settings": disk.settings, "width": disk.width, "height": disk.height,
            "source_space": "oriented_original_pixels"}
