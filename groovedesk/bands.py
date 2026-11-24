"""Detect circular band boundary lines around a clicked groove radius.

A real band boundary is the same circle seen from several separated viewing
directions.  A reflection only lights up one short arc, so its bright peak
appears in one or two neighbouring directions.  For every direction we scan a
radial window around the clicked radius, cluster matching peaks by radius and
score each candidate by how many separated directions support it.
"""

import numpy as np
from scipy.ndimage import uniform_filter1d
from scipy.signal import find_peaks

from . import polar

DIRECTION_COUNT = 8
WINDOW = 0.10
PROFILE_STEPS = 401
BASELINE_WIDTH = 81
CLUSTER_RADIUS = 0.012
MIN_PEAK_DISTANCE = 8
RELIABLE_SUPPORT = 4
RELIABLE_SPAN = 135.0
MIN_PROMINENCE = 0.02
PROMINENCE_SIGMA = 2.5


def luminance(samples):
    if samples.ndim == 2:
        return samples
    return samples @ np.array([.2126, .7152, .0722], dtype=np.float32)


def direction_angles(anchor):
    return [(anchor + 360 * index / DIRECTION_COUNT) % 360 for index in range(DIRECTION_COUNT)]


def radial_profile(disk, angle, lo, hi):
    radii = np.linspace(lo, hi, PROFILE_STEPS)
    samples, valid = disk.sample([angle], radii)
    profile = luminance(samples)[:, 0]
    usable = valid[:, 0]
    if not usable.all():
        keep = np.flatnonzero(usable)
        if len(keep) < BASELINE_WIDTH:
            return radii, profile, usable, np.full_like(profile, MIN_PROMINENCE)
        first, last = keep[0], keep[-1] + 1
        radii, profile, usable = radii[first:last], profile[first:last], usable[first:last]
    baseline = uniform_filter1d(profile, size=min(BASELINE_WIDTH, len(profile) // 2 * 2 - 1), mode="nearest")
    response = profile - baseline
    threshold = max(MIN_PROMINENCE, PROMINENCE_SIGMA * float(np.std(response)))
    return radii, response, usable, threshold


def scan_direction(disk, angle, lo, hi):
    radii, response, usable, threshold = radial_profile(disk, angle, lo, hi)
    distance = max(MIN_PEAK_DISTANCE, len(radii) // 40)
    peaks, props = find_peaks(response, prominence=threshold, distance=distance)
    found = [{"radius": float(radii[index]), "prominence": float(props["prominences"][item])}
             for item, index in enumerate(peaks) if usable[index]]
    return found, float(threshold), float(usable.mean() * 100)


def cluster_peaks(observations):
    ordered = sorted(observations, key=lambda item: item["radius"])
    clusters = []
    for item in ordered:
        if clusters and abs(item["radius"] - clusters[-1]["mean"]) <= CLUSTER_RADIUS:
            group = clusters[-1]
            group["items"].append(item)
            radii = [entry["radius"] for entry in group["items"]]
            group["mean"] = float(np.mean(radii))
            group["spread"] = float(np.std(radii))
        else:
            clusters.append({"mean": item["radius"], "spread": 0.0, "items": [item]})
    return clusters


def summarize_cluster(cluster):
    items = cluster["items"]
    direction_ids = sorted({entry["direction"] for entry in items})
    angles = sorted(entry["angle"] for entry in items)
    # Circular coverage: largest empty angular gap between supporting directions.
    gaps = []
    for index in range(len(angles)):
        nxt = angles[(index + 1) % len(angles)]
        gaps.append((nxt - angles[index]) % 360)
    largest_gap = max(gaps) if gaps else 360.0
    span = 360.0 - largest_gap
    return {
        "radius": round(cluster["mean"], 6),
        "support": len(direction_ids),
        "directions": direction_ids,
        "angles": [round(angle, 2) for angle in angles],
        "span": round(span, 2),
        "radius_spread": round(cluster["spread"], 6),
        "prominence": round(float(np.mean([entry["prominence"] for entry in items])), 4),
        "reliable": len(direction_ids) >= RELIABLE_SUPPORT and span >= RELIABLE_SPAN,
    }


def choose_boundaries(candidates, target):
    inner_pool = [item for item in candidates if item["radius"] < target]
    outer_pool = [item for item in candidates if item["radius"] > target]
    inner = max(inner_pool, key=lambda item: item["radius"], default=None)
    outer = min(outer_pool, key=lambda item: item["radius"], default=None)

    def pick(nearest, pool, side):
        if nearest is None:
            return None, "缺边：搜索窗内没有任何分带线证据。"
        if nearest["reliable"]:
            return nearest, "采用：最近且多方向证据完整。"
        complete = [item for item in pool if item["reliable"]]
        if complete:
            fallback = max(complete, key=lambda item: item["radius"]) if side == "inner" \
                else min(complete, key=lambda item: item["radius"])
            return fallback, (f"近处窄线仅 {nearest['support']} 个方向可见（角覆盖 "
                              f"{nearest['span']:.0f}°），旁线覆盖 {fallback['support']} 个方向；"
                              "默认采用覆盖更完整的旁线。")
        return None, (f"缺边：最近候选只在 {nearest['support']} 个方向出现，"
                      "没有达到多方向完整判据的分带线。")

    inner_line, inner_note = pick(inner, inner_pool, "inner")
    outer_line, outer_note = pick(outer, outer_pool, "outer")
    return inner_line, outer_line, inner_note, outer_note


def detect(disk, target, anchor):
    """Return candidate band lines, per-direction evidence and a default pair."""
    settings = disk.settings
    target = float(np.clip(target, settings["inner"] + 0.002, settings["outer"] - 0.002))
    lo = max(settings["inner"], target - WINDOW)
    hi = min(settings["outer"], target + WINDOW)
    anchor = anchor % 360
    angles = direction_angles(settings["phase"] + anchor)
    observations = []
    directions = []
    for index, angle in enumerate(angles):
        peaks, threshold, coverage = scan_direction(disk, angle, lo, hi)
        relative = (angle - settings["phase"]) % 360
        for peak in peaks:
            observations.append({**peak, "direction": index, "angle": relative})
        directions.append({
            "direction": index, "angle": round(relative, 2),
            "peak_count": len(peaks), "threshold": round(threshold, 4),
            "coverage": round(coverage, 1),
            "peaks": [{"radius": round(peak["radius"], 6),
                       "prominence": round(peak["prominence"], 4)} for peak in peaks],
            "point": disk.point(angle, target),
        })
    candidates = [summarize_cluster(cluster) for cluster in cluster_peaks(observations)]
    candidates.sort(key=lambda item: item["radius"])
    inner_line, outer_line, inner_note, outer_note = choose_boundaries(candidates, target)
    return {
        "target": round(target, 6),
        "anchor": round(anchor, 2),
        "window": [round(lo, 6), round(hi, 6)],
        "directions": directions,
        "candidates": candidates,
        "inner_line": inner_line,
        "outer_line": outer_line,
        "inner_note": inner_note,
        "outer_note": outer_note,
    }
