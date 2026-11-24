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
    mm_per_unit = settings["diameter"] / (2 * outer)
    relative, measured, contrast = [], [], []
    for index, angle in enumerate(angles):
        offset = int(np.argmax(difference[:, index]))
        edge = float(difference[offset, index])
        radius = float((radii[offset] + radii[offset + 1]) / 2)
        read = edge >= .026
        relative.append(float((angle - phase) % 360))
        measured.append(radius if read else None)
        contrast.append(max(edge, 0.0))
    assessment = None
    per_row = {}
    if settings.get("chip"):
        assessment, per_row = assess_chip(disk, relative, measured, contrast, float(radii[1] - radii[0]))
    rows = []
    for index, angle in enumerate(angles):
        radius = measured[index]
        row = {
            "angle": digits(relative[index]),
            "radius": digits(radius * disk.unit) if radius is not None else None,
            "delta": digits((radius - outer) * mm_per_unit) if radius is not None else None,
            "edge": digits(contrast[index] * 100),
            "point": visible_point(disk, angle, radius if radius is not None else outer),
        }
        if assessment is not None:
            estimate, missing, reference = per_row.get(index, (None, None, False))
            row["estimate"] = digits(estimate * disk.unit) if estimate is not None else None
            row["missing"] = digits(missing) if missing is not None else None
            row["reference"] = "✓" if reference else ""
        rows.append(row)
    columns = [column("方向 °", "angle"), column("盘缘半径 px", "radius"), column("距设定外圈 mm", "delta"),
               column("边缘对比 %", "edge")]
    if assessment is not None:
        columns += [column("估计盘缘 px", "estimate"), column("缺失 mm", "missing"), column("参照", "reference")]
    return columns, rows, assessment


def assess_chip(disk, relative, measured, contrast, grid):
    """Estimate the un-chipped rim from intact rim flanking a marked chip.

    Reads next to the notch can still sit on its shoulder, and rim far away can
    genuinely curve differently, so only a bounded window on each side of the
    chip (skipping a shoulder margin and any other chip) fits a circle with a
    free center.  When that evidence is clearly insufficient the depth is left
    empty.
    """
    settings = disk.settings
    phase = settings["phase"]
    mm_per_unit = settings["diameter"] / (2 * settings["outer"])
    mark = next((item for item in settings["marks"] if item["id"] == settings.get("chip")), None)
    if mark is None:
        return None, {}
    c0 = (mark["start"] - phase) % 360
    span = mark["span"]
    center = c0 + span / 2
    shoulder = min(max(0.55 * span, 3.0), 12.0)
    window = min(max(1.7 * span, 16.0), 40.0)
    others = [((item["start"] - phase) % 360, item["span"]) for item in settings["marks"]
              if item["kind"] == "chip" and item["id"] != mark["id"]]

    def sector(rel):
        shifted = (rel - c0) % 360
        if shifted <= span:
            return "chip"
        if span + shoulder < shifted <= span + shoulder + window:
            return "right"
        if 360 - shoulder - window <= shifted < 360 - shoulder:
            return "left"
        return None

    def intact(rel):
        for start, width in others:
            shifted = (rel - start) % 360
            if shifted <= width + shoulder or shifted >= 360 - shoulder:
                return False
        return True

    sectors = [sector(rel) for rel in relative]
    chip_rows = [index for index, name in enumerate(sectors) if name == "chip"]
    candidates = [index for index, name in enumerate(sectors)
                  if name in ("left", "right") and measured[index] is not None and intact(relative[index])]
    assessment = {"mark": mark["id"], "window": [digits(c0), digits(c0 + span)],
                  "status": "insufficient", "depth": None, "deepest": None, "deepest_point": None,
                  "points": 0, "ranges": [], "residual": None, "edge": [], "note": ""}
    sides = {name: [index for index in candidates if sectors[index] == name] for name in ("left", "right")}
    if len(candidates) < 8 or min(len(sides["left"]), len(sides["right"])) < 3:
        assessment["note"] = (f"磕口两侧的完整盘边不足（缺口肩外左侧 {len(sides['left'])} 点、右侧 "
                              f"{len(sides['right'])} 点，各需至少 3 点），深度留空。")
        return assessment, {}

    phi = np.deg2rad([((relative[index] - center + 180) % 360) - 180 for index in candidates])
    values = np.array([measured[index] for index in candidates])
    weights = np.array([min(contrast[index], 0.15) for index in candidates])

    def fit(idx):
        design = np.column_stack((np.ones(len(idx)), np.cos(phi[idx]), np.sin(phi[idx])))
        beta, *_ = np.linalg.lstsq(design * weights[idx, None], values[idx] * weights[idx], rcond=None)
        return beta

    def residuals(beta):
        return values - (beta[0] + beta[1] * np.cos(phi) + beta[2] * np.sin(phi))

    idx = np.arange(len(candidates))
    beta = fit(idx)
    resid = residuals(beta)
    scale = 1.4826 * float(np.median(np.abs(resid - np.median(resid))))
    keep = np.abs(resid) <= 2.5 * max(scale, grid)
    if 6 <= int(keep.sum()) < len(idx) and {sectors[candidates[i]] for i in idx[keep]} == {"left", "right"}:
        idx = idx[keep]
        beta = fit(idx)
        resid = residuals(beta)
    kept = {"left": [i for i in idx if sectors[candidates[i]] == "left"],
            "right": [i for i in idx if sectors[candidates[i]] == "right"]}
    residual_mm = float(np.sqrt(np.mean(resid[idx] ** 2)) * mm_per_unit)
    assessment["points"] = int(len(idx))
    if len(idx) < 6 or min(len(kept["left"]), len(kept["right"])) < 2:
        assessment["note"] = "剔除离群读数后完整盘边不足，深度留空。"
        return assessment, {}
    if residual_mm > 0.4:
        assessment["note"] = f"参照盘边残差 {residual_mm:.2f} mm 超过 0.40 mm，盘边起伏过大，深度留空。"
        return assessment, {}

    per_row = {candidates[i]: (None, None, True) for i in idx}
    ranges = []
    for name in ("left", "right"):
        unrolled = [c0 + (relative[candidates[i]] - c0) % 360 for i in kept[name]]
        start = min(unrolled) % 360
        ranges.append([digits(start), digits(start + max(unrolled) - min(unrolled))])

    def estimate_at(rel):
        angle = np.deg2rad(((rel - center) + 180) % 360 - 180)
        return float(beta[0] + beta[1] * np.cos(angle) + beta[2] * np.sin(angle))

    misses = {}
    for index in chip_rows:
        estimate = estimate_at(relative[index])
        misses[index] = (estimate - measured[index]) * mm_per_unit if measured[index] is not None else None
        per_row[index] = (estimate, misses[index], False)
    steps = 24
    assessment["edge"] = [[digits((center - span / 2 + span * step / steps) % 360),
                           round(estimate_at(center - span / 2 + span * step / steps), 6)]
                          for step in range(steps + 1)]
    assessment["ranges"] = ranges
    assessment["residual"] = digits(residual_mm)
    valid = [(index, miss) for index, miss in misses.items() if miss is not None]
    if valid:
        deepest, depth = max(valid, key=lambda item: item[1])
        assessment.update(status="ok", depth=digits(depth), deepest=digits(relative[deepest]),
                          deepest_point=visible_point(disk, phase + relative[deepest], measured[deepest]))
    else:
        assessment["status"] = "unmeasured"
        assessment["note"] = ("缺口范围内没有有效实测盘缘，深度留空。" if chip_rows
                              else "缺口角宽内没有盘缘读点，深度留空。")
    return assessment, per_row


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
    columns, rows, *extra = READERS[mode](disk)
    result = {"mode": mode, "heading": model.MODES[mode], "columns": columns, "rows": rows,
              "settings": disk.settings, "width": disk.width, "height": disk.height,
              "source_space": "oriented_original_pixels"}
    if extra and extra[0] is not None:
        result["assessment"] = extra[0]
    return result
