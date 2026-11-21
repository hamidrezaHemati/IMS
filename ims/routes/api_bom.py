"""Read-only BOM Cost Calculator and Availability API endpoints."""

import json
from flask import Blueprint, current_app, jsonify, make_response, request
from ims.auth import login_required
from ims.services import bom_service
from ims.utils import save_uploaded_xlsx

bp = Blueprint("api_bom", __name__, url_prefix="/api/bom")


@bp.post("/inspect")
@login_required
def inspect_bom():
    if "file" in request.files:
        upload_id, _ = save_uploaded_xlsx(
            request.files.get("file"),
            current_app.config["UPLOAD_DIR"],
            prefix="bom",
        )
        sheet_name = request.form.get("sheet_name") or None
    else:
        data = request.get_json(silent=True) or {}
        upload_id = data.get("upload_id")
        sheet_name = data.get("sheet_name")

    info = bom_service.inspect_bom_upload(
        upload_id=upload_id,
        upload_dir=current_app.config["UPLOAD_DIR"],
        sheet_name=sheet_name,
    )
    return jsonify(info)


@bp.post("/calculate")
@login_required
def calculate_bom():
    if "file" in request.files:
        upload_id, _ = save_uploaded_xlsx(
            request.files.get("file"),
            current_app.config["UPLOAD_DIR"],
            prefix="bom",
        )
        sheet_name = request.form.get("sheet_name") or None
        raw_mapping = request.form.get("column_mapping")
        mapping = json.loads(raw_mapping) if raw_mapping else None
    else:
        data = request.get_json(silent=True) or {}
        upload_id = data.get("upload_id")
        sheet_name = data.get("sheet_name")
        mapping = data.get("column_mapping")

    result = bom_service.calculate_bom(
        upload_id=upload_id,
        upload_dir=current_app.config["UPLOAD_DIR"],
        sheet_name=sheet_name,
        column_mapping=mapping,
    )
    return jsonify(result)


@bp.post("/export")
@login_required
def export_bom():
    data = request.get_json(silent=True) or {}
    analysis = bom_service.calculate_bom(
        upload_id=data.get("upload_id"),
        upload_dir=current_app.config["UPLOAD_DIR"],
        sheet_name=data.get("sheet_name"),
        column_mapping=data.get("column_mapping"),
    )
    xlsx_bytes = bom_service.export_bom_report_xlsx(analysis)

    resp = make_response(xlsx_bytes)
    resp.headers["Content-Type"] = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    resp.headers["Content-Disposition"] = 'attachment; filename="bom_cost_report.xlsx"'
    return resp
