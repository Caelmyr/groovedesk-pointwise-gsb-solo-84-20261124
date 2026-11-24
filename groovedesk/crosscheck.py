"""Compare a surface mark across two photographs lit from different directions.

The two panels were calibrated with the same disk center, rings and zero mark,
so disk angles and normalized radii address the same physical surface point in
both pixel frames. Each photograph is sampled on the same angle/radius grid;
a radial high-pass response keeps narrow scratch-like contrast while removing
broad moving light pools. Column-level responses are robustly standardized,
classified into joint / single-photo evidence and merged into angular segments
that can be located on either original.
"""

import cv2
import numpy as np

from image_lab.validation import Invalid

from .inspection import luminance
from .model import MARKS
from .polar import angles

ANGLE_STEPS = 240
RADIUS_STEPS = 64
SHORT_WINDOW = 5
TOP_K = 8
STRONG = 3.0
WEAK = 1.5
MIN_HIT_RATE = 0.015
MIN_RUN = 4
MERGE_GAP = 3
JOINT_TOLERANCE = 1
MIN_SHARED_COVERAGE = 0.5
MIN_COLUMN_COVERAGE = 0.5
VIEW_LABELS = {"a": "原片 A", "b": "对照片 B"}
VERDICTS = {
    "co_located": "同位证据",
    "single": "主要见于一张",
    "insufficient": "共同证据不足",
}


def _frame(disk, grid_angles, radii):
    samples, valid = disk.sample(grid_angles, radii)
    lum = luminance(samples).astype(np.float32)
    return np.where(valid, lum, np.nan), valid


def _column_response(frame, valid):
    """Return scratch contrast, hit rate, polarity, glare and coverage per angle.

    The radial high-pass runs on raw luminance so a narrow line keeps its
    full amplitude against the moving illumination, instead of being
    renormalized away inside its own column. A column is only credible when
    several radial rows cross a threshold derived from the mark region's own
    noise floor; isolated sensor extremes cannot form evidence.
    """
    row_count = frame.shape[0]
    medians = np.nanmedian(np.where(valid, frame, np.nan), axis=0)
    medians = np.where(np.isfinite(medians), medians, 0.0)
    fill = np.where(valid, frame, medians[np.newaxis, :]).astype(np.float32)
    detail = fill - cv2.GaussianBlur(fill, (1, SHORT_WINDOW), 0)
    magnitude = np.abs(detail)
    noise_floor = float(np.median(magnitude[valid])) if valid.any() else 0.0
    hit_level = max(0.03, noise_floor * 3.5)
    ordered = np.sort(magnitude, axis=0)
    contrast = np.mean(ordered[-TOP_K:, :], axis=0)
    hits = np.mean(magnitude >= hit_level, axis=0)
    glare = np.mean(fill > 0.965, axis=0)
    coverage = valid.sum(axis=0) / row_count
    return contrast, hits, glare, coverage, magnitude, fill


def _robust_scale(values, mask):
    reference = values[mask]
    if reference.size < 8:
        return np.zeros_like(values)
    center = np.median(reference)
    scale = np.median(np.abs(reference - center)) * 1.4826
    if scale < 1e-6:
        scale = np.std(reference)
    if scale < 1e-6:
        return np.zeros_like(values)
    return (values - center) / scale


def _dilate(mask, radius):
    if radius <= 0:
        return mask
    padded = np.concatenate((np.zeros(radius, dtype=bool), mask, np.zeros(radius, dtype=bool)))
    out = np.zeros_like(mask)
    for offset in range(2 * radius + 1):
        out |= padded[offset:offset + len(mask)]
    return out


def _runs(mask, bridge, min_run=MIN_RUN, gap=MERGE_GAP):
    spans = []
    index = 0
    total = len(mask)
    while index < total:
        if not mask[index]:
            index += 1
            continue
        start = index
        end = index
        gap_len = 0
        index += 1
        while index < total:
            if mask[index]:
                end = index
                gap_len = 0
            elif bridge[index] and gap_len < gap:
                gap_len += 1
            else:
                break
            index += 1
        if end - start + 1 >= min_run:
            spans.append((start, end))
    return spans


def _polarity(fill, first, last):
    """Polarity from raw luminance peaks versus each column's local level.

    High-pass edges surround both bright and dark lines, so their signed
    detail alone is ambiguous. The direction in which the raw luminance
    departs farthest from the column median identifies the line core itself.
    """
    band = fill[:, first:last + 1]
    column_level = np.median(band, axis=0)
    upward = np.mean(np.max(band, axis=0) - column_level)
    downward = np.mean(column_level - np.min(band, axis=0))
    value = float(upward - downward)
    return "亮线" if value >= 0 else "暗线", value


def _percent(score):
    return round(float(np.clip(score / 4.0, 0, 1) * 100), 1)


def _relative(angle, phase):
    return round((angle - phase) % 360, 2)


def _corners(disk, angle_first, angle_last, inner, outer):
    points = [
        disk.point(angle_first, outer), disk.point(angle_last, outer),
        disk.point(angle_last, inner), disk.point(angle_first, inner),
    ]
    return [[round(x, 2), round(y, 2)] for x, y in points]


def _segment_payload(kind, first, last, grid, mark, disks, settings, scores, fills, magnitude, glare):
    phase = settings["a"]["phase"]
    angle_first = grid[first]
    angle_last = grid[min(last + 1, len(grid) - 1)]
    mid_angle = float((angle_first + angle_last) / 2)
    mid_radius = (mark["inner"] + mark["outer"]) / 2
    polarity_a, signed_a = _polarity(fills["a"], first, last)
    polarity_b, signed_b = _polarity(fills["b"], first, last)
    flip = kind == "joint" and np.sign(signed_a) != np.sign(signed_b)
    strength_a = float(np.mean(scores["a"][first:last + 1]))
    strength_b = float(np.mean(scores["b"][first:last + 1]))
    if kind == "joint":
        label = "同位证据"
        view = "a" if strength_a >= strength_b else "b"
    else:
        label = "仅见于原片 A" if kind == "a" else "仅见于对照片 B"
        view = kind
    return {
        "kind": kind, "verdict_label": label, "view": view, "flip": bool(flip),
        "first": first, "last": last,
        "angle_first": round(angle_first, 3), "angle_last": round(angle_last, 3),
        "start_rel": _relative(angle_first, phase), "end_rel": _relative(angle_last, phase),
        "angle_range": f"{_relative(angle_first, phase)}°–{_relative(angle_last, phase)}°",
        "a_contrast": _percent(strength_a), "b_contrast": _percent(strength_b),
        "a_polarity": polarity_a, "b_polarity": polarity_b,
        "a_glare": round(float(np.mean(glare["a"][first:last + 1])) * 100, 1),
        "b_glare": round(float(np.mean(glare["b"][first:last + 1])) * 100, 1),
        "inner": mark["inner"], "outer": mark["outer"],
        "point": disks["a"].point(mid_angle, mid_radius),
        "point_b": disks["b"].point(mid_angle, mid_radius),
        "corners": {
            "a": _corners(disks["a"], angle_first, angle_last, mark["inner"], mark["outer"]),
            "b": _corners(disks["b"], angle_first, angle_last, mark["inner"], mark["outer"]),
        },
    }


def _default_text(segment, mark_id):
    head = f"标记 {mark_id} 的默认读法：{VIEW_LABELS[segment['view']]} 中 {segment['angle_range']} 一段"
    if segment["kind"] == "joint":
        flip = "对照片 B 同位由亮变暗（或由暗变亮），极性反转但反差仍在" if segment["flip"] else "两张照片同位都有强反差，极性一致"
        return head + f"共同入画且反差最强，{flip}，采用这段共同证据，判为{VERDICTS['co_located']}。"
    photo = "原片 A" if segment["kind"] == "a" else "对照片 B"
    other = "对照片 B" if segment["kind"] == "a" else "原片 A"
    return head + f"反差最强；{other} 同位只有弱反差或无反差，采用这段单方证据，判为{VERDICTS['single']}。"


def _overall_text(verdict, segments, coverage):
    if verdict == "insufficient":
        return (f"标记共同入画比例 {coverage}%，两张照片在标记范围内都没有稳定的强反差列，"
                f"无法相互印证，判为{VERDICTS['insufficient']}。")
    notes = []
    for segment in segments:
        if segment["kind"] == "joint":
            flip = "，且 B 片极性反转" if segment["flip"] else ""
            notes.append(f"{segment['angle_range']} 两片同位强反差{flip}")
        else:
            photo = "A" if segment["kind"] == "a" else "B"
            notes.append(f"{segment['angle_range']} 仅 {photo} 片强反差")
    return f"共同入画 {coverage}%。证据段：" + "；".join(notes) + "。"


def analyze(disks, settings, mark):
    """Analyze one mark on two open disks.

    disks and settings are dicts keyed ``a`` (selected photograph) and
    ``b`` (companion photograph); mark uses normalized disk coordinates.
    """
    grid = angles(mark["start"], mark["span"], ANGLE_STEPS)
    radii = np.linspace(mark["inner"], mark["outer"], RADIUS_STEPS)
    contrast, hits, magnitude, fills, glare, coverage = {}, {}, {}, {}, {}, {}
    for view in ("a", "b"):
        frame, valid = _frame(disks[view], grid, radii)
        contrast[view], hits[view], glare[view], coverage[view], magnitude[view], fills[view] = \
            _column_response(frame, valid)
    shared = (coverage["a"] >= MIN_COLUMN_COVERAGE) & (coverage["b"] >= MIN_COLUMN_COVERAGE)
    if int(shared.sum()) < 8:
        raise Invalid("两张照片在该标记范围内共同入画的采样不足，无法核对。")
    scores = {view: _robust_scale(contrast[view], shared) for view in ("a", "b")}
    # A column only counts as evidence when its robust contrast is high and
    # several radial rows cross a fixed local level, so isolated noise cannot
    # become evidence.
    strong_a = (scores["a"] >= STRONG) & (hits["a"] >= MIN_HIT_RATE)
    strong_b = (scores["b"] >= STRONG) & (hits["b"] >= MIN_HIT_RATE)
    weak_a, weak_b = scores["a"] >= WEAK, scores["b"] >= WEAK
    # The two photographs are independent samples; allow one grid column of
    # angular tolerance when matching the same physical groove.
    strong_a_near = _dilate(strong_a, JOINT_TOLERANCE) & shared
    strong_b_near = _dilate(strong_b, JOINT_TOLERANCE) & shared
    joint = strong_a_near & strong_b_near
    only_a = strong_a & ~strong_b_near & ~weak_b
    only_b = strong_b & ~strong_a_near & ~weak_a
    bridgeable = shared & ~joint & ~only_a & ~only_b
    spans = (
        [("joint", first, last) for first, last in _runs(joint, bridgeable)]
        + [("a", first, last) for first, last in _runs(only_a, bridgeable)]
        + [("b", first, last) for first, last in _runs(only_b, bridgeable)]
    )
    spans.sort(key=lambda item: item[1])
    segments = [
        _segment_payload(kind, first, last, grid, mark, disks, settings, scores, fills, magnitude, glare)
        for index, (kind, first, last) in enumerate(spans)
    ]
    for index, segment in enumerate(segments, 1):
        segment["id"] = f"S-{index}"
    shared_coverage = round(float(shared.mean()) * 100, 1)
    if not segments or shared_coverage < MIN_SHARED_COVERAGE * 100:
        verdict = "insufficient"
    elif any(segment["kind"] == "joint" for segment in segments):
        verdict = "co_located"
    else:
        verdict = "single"
    default_segment = None
    if segments:
        if verdict == "co_located":
            default_segment = max(
                (segment for segment in segments if segment["kind"] == "joint"),
                key=lambda item: min(item["a_contrast"], item["b_contrast"]),
            )
        else:
            default_segment = max(
                segments,
                key=lambda item: item["a_contrast"] if item["kind"] == "a" else item["b_contrast"],
            )
    narrative = _overall_text(verdict, segments, shared_coverage)
    default = None
    if default_segment is not None:
        default = {
            "segment": default_segment["id"], "view": default_segment["view"],
            "text": _default_text(default_segment, mark["id"]),
        }
    return {
        "verdict": verdict, "verdict_label": VERDICTS[verdict],
        "shared_coverage": shared_coverage,
        "narrative": narrative, "default": default, "segments": segments,
        "mark_id": mark["id"], "mark_kind": MARKS[mark["kind"]],
        "grid": {"start": mark["start"], "span": mark["span"], "steps": ANGLE_STEPS},
    }


def find_mark(settings, mark_id):
    for mark in settings["marks"]:
        if mark["id"] == mark_id:
            return mark
    raise Invalid("请先在表面标记中选择这条标记。")
