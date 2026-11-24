"""Normal inspection entry points, source intake, settings and saved checks."""

from io import BytesIO
from pathlib import Path

from flask import Blueprint, Response, jsonify, render_template, request, send_file
from werkzeug.exceptions import NotFound

from image_lab.validation import Invalid

from . import demo, inspection, model, output, photo, polar
from .store import Library


def payload():
    return model.object_value(request.get_json(silent=True))


def make_result(library, panel, mode, settings, target=None, anchor=None):
    return inspection.report(polar.open_disk(library.source(panel), settings), mode, target, anchor)


def install(app, path):
    library = Library(path)
    api = Blueprint("groovedesk", __name__, url_prefix="/groove")

    @app.get("/")
    def desk():
        return render_template("groovedesk.html")

    @api.get("/health")
    def health():
        return jsonify(status="ready", service="groovedesk")

    @api.get("/config")
    def config():
        return jsonify(settings=model.DEFAULTS, modes=model.MODES, marks=model.MARKS)

    @api.get("/panels")
    def panels():
        return jsonify(library.list())

    @api.post("/demo")
    def sample():
        return jsonify(demo.create(library)), 201

    @api.post("/panels")
    def upload():
        file = request.files.get("file")
        if file is None:
            raise Invalid("请先选择原片。")
        filename = model.text_value(Path(file.filename).name, "原文件名")
        title = model.text_value(request.form.get("title") or Path(filename).stem)
        image = photo.decode(file.stream.read(model.MAX_UPLOAD + 1))
        return jsonify(library.create(title, filename, photo.png(image), image.size, model.DEFAULTS)), 201

    @api.post("/prepare")
    def prepared():
        value = payload()
        project_id = model.text_value(value.get("project"), "准备工程 ID")
        result_id = model.text_value(value.get("result"), "准备结果 ID")
        results = app.extensions["results"]
        meta = results.metadata(project_id, result_id)
        if meta["stale"]:
            raise Invalid("请更新准备结果后再导入。")
        source = results.image_path(project_id, "image", result_id)
        if isinstance(source, bytes):
            content = source
        else:
            with source.open("rb") as handle:
                content = handle.read(model.MAX_UPLOAD + 1)
        image = photo.decode(content)
        title = model.text_value(meta.get("name") or "准备区处理照片")
        tags = {"kind": "prepared", "project": project_id, "result": result_id}
        return jsonify(library.create(title, title + ".png", photo.png(image), image.size, model.DEFAULTS, tags)), 201

    @api.get("/panels/<panel_id>")
    def panel(panel_id):
        return jsonify(library.panel(panel_id))

    @api.get("/panels/<panel_id>/image")
    def source(panel_id):
        path = library.source(library.panel(panel_id))
        if not path.exists():
            raise NotFound("照片数据不可用。")
        return send_file(path, mimetype="image/png", conditional=True)

    @api.put("/panels/<panel_id>/settings")
    def settings(panel_id):
        value = payload()
        panel = library.panel(panel_id)
        chosen = model.settings(value.get("settings", {}), panel["settings"])
        return jsonify(library.revise(panel_id, value.get("revision"), chosen))

    @api.post("/panels/<panel_id>/preview")
    def preview(panel_id):
        value = payload()
        panel = library.panel(panel_id)
        chosen = model.settings(value.get("settings", {}), panel["settings"])
        mode = model.mode(value.get("mode"))
        target = value.get("target")
        anchor = value.get("anchor")
        if mode == "bands":
            target = model.numeric(target if target is not None else chosen["inner"], "目标半径", 0.02, 0.9)
            anchor = model.numeric(anchor if anchor is not None else 0.0, "锚定方向", 0, 360)
        return jsonify(make_result(library, panel, mode, chosen, target, anchor))

    def strip_file(panel, settings, start, sweep, download=False):
        disk = polar.open_disk(library.source(panel), settings)
        radial_bounds = inspection.band_bounds(settings) if sweep < 360 else None
        payload = photo.png(polar.unroll(disk, start, sweep, radial_bounds=radial_bounds))
        return send_file(BytesIO(payload), mimetype="image/png", download_name="groove-strip.png",
                         as_attachment=download, max_age=0)

    @api.post("/panels/<panel_id>/strip")
    def preview_strip(panel_id):
        value = payload()
        panel = library.panel(panel_id)
        chosen = model.settings(value.get("settings", {}), panel["settings"])
        sliced = value.get("mode") == "slice"
        return strip_file(panel, chosen, chosen["angle"] if sliced else 0, chosen["span"] if sliced else 360)

    @api.get("/panels/<panel_id>/checks/<check_id>/strip.png")
    def saved_strip(panel_id, check_id):
        result = library.check(panel_id, check_id)
        chosen = result["settings"]
        sliced = result["mode"] == "slice"
        return strip_file(result, chosen, chosen["angle"] if sliced else 0,
                          chosen["span"] if sliced else 360, download=True)

    @api.post("/panels/<panel_id>/checks")
    def save(panel_id):
        value = payload()
        panel = library.panel(panel_id)
        revision = value.get("revision")
        library.require_revision(panel, revision)
        settings = model.settings(value.get("settings", {}), panel["settings"])
        mode = model.mode(value.get("mode"))
        target = anchor = None
        if mode == "bands":
            target = model.numeric(value.get("target", settings["inner"]), "目标半径", 0.02, 0.9)
            anchor = model.numeric(value.get("anchor", 0.0), "锚定方向", 0, 360)
        result = make_result(library, panel, mode, settings, target, anchor)
        current, saved = library.retain(panel_id, revision, result)
        return jsonify(panel=current, check=saved), 201

    @api.get("/panels/<panel_id>/checks/<check_id>")
    def open_check(panel_id, check_id):
        return jsonify(library.check(panel_id, check_id))

    @api.get("/panels/<panel_id>/checks/<check_id>/report.csv")
    def csv_report(panel_id, check_id):
        result = library.check(panel_id, check_id)
        return Response(output.csv_text(result), mimetype="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="groove-{result["mode"]}.csv"'})

    @api.get("/panels/<panel_id>/checks/<check_id>/overlay.png")
    def png_report(panel_id, check_id):
        result = library.check(panel_id, check_id)
        image = photo.display(library.source(result))
        return send_file(BytesIO(photo.png(output.overlay(image, result))), mimetype="image/png",
                         download_name=f'groove-{result["mode"]}.png', as_attachment=True, max_age=0)

    app.register_blueprint(api)
