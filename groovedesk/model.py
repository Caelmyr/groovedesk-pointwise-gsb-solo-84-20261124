"""Validate inspection geometry, surface annotations and input limits."""

from math import isfinite

from image_lab.validation import Invalid

MAX_UPLOAD = 22 * 1024**2
MAX_PIXELS = 14_000_000
MODES = {
    "surface": "表面标记",
    "lighting": "照明巡检",
    "rim": "盘缘读数",
    "grooves": "径向纹理",
    "slice": "角度切片",
}
MARKS = {"scratch": "擦伤", "chip": "磕口", "reference": "参照", "dust": "颗粒"}
DEFAULTS = {"center": [0.5, 0.5], "inner": 0.23, "outer": 0.46, "phase": 0.0,
            "diameter": 300.0, "angle": 45.0, "span": 30.0, "marks": []}


def object_value(value):
    if not isinstance(value, dict):
        raise Invalid("盘照设置应为对象。")
    return value


def text_value(value, field="照片名称"):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 100:
        raise Invalid(f"{field}应有 1 至 100 个字符。")
    return " ".join(value.split())


def numeric(value, label, start, stop):
    if isinstance(value, bool):
        raise Invalid(f"{label}超出范围。")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise Invalid(f"{label}需要数字。") from None
    if not isfinite(number) or not start <= number <= stop:
        raise Invalid(f"{label}超出范围。")
    return number


def mark_list(values):
    if not isinstance(values, list) or len(values) > 64:
        raise Invalid("最多保存 64 条盘面标记。")
    marks = []
    ids = set()
    for value in values:
        item = object_value(value)
        name = text_value(item.get("id"), "标记编号")
        if name in ids:
            raise Invalid("标记编号应唯一。")
        ids.add(name)
        kind = item.get("kind")
        if not isinstance(kind, str) or kind not in MARKS:
            raise Invalid("请选择有效的标记类别。")
        start = numeric(item.get("start"), "标记起角", 0, 360) % 360
        span = numeric(item.get("span"), "标记角宽", 0.1, 180)
        inner = numeric(item.get("inner"), "标记内半径", 0, 0.9)
        outer = numeric(item.get("outer"), "标记外半径", 0, 0.9)
        if outer - inner < 0.001:
            raise Invalid("标记需要正的半径宽度。")
        marks.append({"id": name, "kind": kind, "start": start, "span": span, "inner": inner, "outer": outer})
    return marks


def settings(value, fallback):
    chosen = {**fallback, **object_value(value)}
    center = chosen["center"]
    if not isinstance(center, list) or len(center) != 2:
        raise Invalid("请在原片上指定盘心。")
    inner = numeric(chosen["inner"], "内半径", 0.02, 0.84)
    outer = numeric(chosen["outer"], "外半径", 0.04, 0.9)
    if outer - inner < 0.02:
        raise Invalid("内外半径间距太小。")
    return {
        "center": [numeric(axis, "盘心", 0, 1) for axis in center],
        "inner": inner, "outer": outer,
        "phase": numeric(chosen["phase"], "盘面零位", 0, 360) % 360,
        "diameter": numeric(chosen["diameter"], "外圈实测直径", 10, 1000),
        "angle": numeric(chosen["angle"], "切片起角", 0, 360) % 360,
        "span": numeric(chosen["span"], "切片角宽", 1, 180),
        "marks": mark_list(chosen["marks"]),
    }


def mode(value):
    if not isinstance(value, str) or value not in MODES:
        raise Invalid("请选择一种检查。")
    return value


def crosscheck(value):
    item = object_value(value)
    chosen = settings(item.get("settings", {}), DEFAULTS)
    mark_id = text_value(item.get("mark"), "标记编号")
    if not any(mark["id"] == mark_id for mark in chosen["marks"]):
        raise Invalid("请先在表面标记中选择这条标记。")
    return {"settings": chosen, "mark": mark_id}
