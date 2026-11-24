"""Developer check for two-photo co-located scratch verification.

Builds three synthetic disk pairs that share identical disk geometry but use
different light directions, then drives the GrooveDesk HTTP API end to end:

* a scratch strong in both photographs (may flip polarity),
* a scratch strong only in the first photograph,
* a mark region with no scratch in either photograph.

Run with: python3 -I scripts/dev_crosscheck_test.py
"""

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from groovedesk import model, photo  # noqa: E402
from groovedesk.__main__ import application  # noqa: E402

SIZE = 760
CENTER = (378 / 759, 372 / 759)
OUTER = 349 / 759
INNER = 0.215


def disk_base(light_angle, rng):
    y, x = np.mgrid[:SIZE, :SIZE]
    dx, dy = x - 378, y - 372
    radius = np.hypot(dx, dy)
    angle = np.degrees(np.arctan2(dx, -dy)) % 360
    light = 11 + 26 * np.clip(np.cos(np.deg2rad(angle - light_angle)), 0, 1) ** 4
    tracks = 4 * (1 + np.cos(radius * 2.7)) + 2 * np.sin(radius * 0.14)
    glow = light + tracks + rng.normal(0, 1.2, radius.shape)
    wood = 72 + 6 * np.sin(0.04 * x) + 4 * np.cos((x + y) * 0.07)
    on_record = radius < 349
    rgb = np.stack([np.where(on_record, glow + tone, wood + base)
                    for tone, base in [(0, 34), (2, 12), (5, -8)]], axis=2)
    rgb[radius < 138] = (96, 144, 142)
    canvas = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8))
    draw = ImageDraw.Draw(canvas)
    draw.ellipse((369, 363, 387, 381), fill=(49, 38, 31))
    return canvas, (x, y, radius, angle)


def polar_point(angle, norm_radius):
    unit = SIZE - 1
    cx, cy = CENTER[0] * unit, CENTER[1] * unit
    theta = np.deg2rad(angle)
    return cx + norm_radius * unit * np.sin(theta), cy - norm_radius * unit * np.cos(theta)


def stroke_scratch(canvas, start, span, inner, outer, color, width=2):
    """Draw a narrow radial-ish line inside the given disk mark box."""
    draw = ImageDraw.Draw(canvas)
    mid = start + span / 2
    x0, y0 = polar_point(mid, outer)
    x1, y1 = polar_point(mid + 2.5, inner)
    draw.line((x0, y0, x1, y1), fill=color, width=width)


def add_light_pool(canvas, geometry, center_angle, center_radius):
    x, y, radius, angle = geometry
    pool = 26 * np.exp(-(((angle - center_angle) / 10) ** 2 +
                         ((radius - center_radius) / 34) ** 2))
    arr = np.asarray(canvas).astype(np.float32) + pool[..., None]
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def make_pair(kind):
    rng = np.random.default_rng(233)
    image_a, geometry_a = disk_base(57, rng)
    image_b, geometry_b = disk_base(203, np.random.default_rng(404))
    # Co-located region: angles 40-62, radii 0.30-0.38.
    start, span, inner, outer = 40, 22, 0.30, 0.38
    if kind in ("joint", "single"):
        stroke_scratch(image_a, start, span, inner, outer, (238, 236, 220), width=3)
    if kind == "joint":
        # The second light direction lights this region, so the same physical
        # groove reads as a dark line against a brighter pool (polarity flips
        # from bright in A to dark in B) while staying clearly measurable.
        image_b = add_light_pool(image_b, geometry_b, 52, 258)
        stroke_scratch(image_b, start, span, inner, outer, (4, 4, 6), width=4)
    if kind == "single":
        # Broad moving light pool in B at the same place, but no narrow line.
        image_b = add_light_pool(image_b, geometry_b, 52, 258)
    return image_a, image_b, {"start": start, "span": span, "inner": inner, "outer": outer}


def settings(mark_id, box):
    base = {**model.DEFAULTS, "center": list(CENTER), "inner": INNER, "outer": OUTER}
    base["marks"] = [{"id": mark_id, "kind": "scratch", **box}]
    return base


def upload(client, image, title, mark_id, box):
    import io
    blob = photo.png(image)
    response = client.post("/groove/panels", data={
        "title": title, "file": (io.BytesIO(blob), title + ".png")},
        content_type="multipart/form-data")
    assert response.status_code == 201, response.get_json()
    panel = response.get_json()
    chosen = settings(mark_id, box)
    saved = client.put(f"/groove/panels/{panel['id']}/settings",
                       json={"settings": chosen, "revision": panel["revision"]})
    assert saved.status_code == 200, saved.get_json()
    return saved.get_json()


def main():
    app = application("/tmp/groovedesk-crosscheck-test")
    client = app.test_client()
    results = {}
    for kind in ("joint", "single", "none"):
        image_a, image_b, box = make_pair(kind)
        panel_a = upload(client, image_a, f"{kind}-A", "S-1", box)
        panel_b = upload(client, image_b, f"{kind}-B", "S-1", box)
        paired = client.put(f"/groove/panels/{panel_a['id']}/pair",
                            json={"companion": panel_b["id"]})
        assert paired.status_code == 200, paired.get_json()
        response = client.post(f"/groove/panels/{panel_a['id']}/crosscheck",
                               json={"settings": panel_a["settings"], "mark": "S-1"})
        assert response.status_code == 200, response.get_json()
        cross = response.get_json()
        results[kind] = cross
        save = client.post(f"/groove/panels/{panel_a['id']}/crosscheck/save", json={
            "settings": panel_a["settings"], "mark": "S-1", "revision": panel_a["revision"]})
        assert save.status_code == 201, save.get_json()
        check_id = save.get_json()["check"]["id"]
        overlay = client.get(f"/groove/panels/{panel_a['id']}/checks/{check_id}/overlay.png")
        assert overlay.status_code == 200 and overlay.data[:8] == b"\x89PNG\r\n\x1a\n"
        csv_response = client.get(f"/groove/panels/{panel_a['id']}/checks/{check_id}/report.csv")
        assert csv_response.status_code == 200
    for kind, cross in results.items():
        print(f"== {kind}: verdict={cross['verdict']} coverage={cross['shared_coverage']}%")
        print("   narrative:", cross["narrative"])
        if cross["default"]:
            print("   default:", cross["default"]["segment"], cross["default"]["view"],
                  cross["default"]["text"])
        for segment in cross["segments"]:
            print(f"   {segment['id']} {segment['verdict_label']} {segment['angle_range']} "
                  f"A={segment['a_contrast']}%/{segment['a_polarity']} "
                  f"B={segment['b_contrast']}%/{segment['b_polarity']} "
                  f"flip={segment['flip']}")
    assert results["joint"]["verdict"] == "co_located"
    assert any(s["kind"] == "joint" and s["flip"] for s in results["joint"]["segments"])
    assert results["single"]["verdict"] == "single"
    assert results["single"]["segments"] and results["single"]["segments"][0]["kind"] == "a"
    assert results["none"]["verdict"] == "insufficient"
    print("all crosscheck assertions passed")


if __name__ == "__main__":
    main()
