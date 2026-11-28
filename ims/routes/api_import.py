"""Type-aware Initial Inventory Excel import & template download API endpoints."""

from flask import Blueprint, current_app, jsonify, make_response, request
from ims.auth import admin_required, get_current_user
from ims.item_specs import get_spec_definition
from ims.services import import_service
from ims.utils import save_uploaded_xlsx

bp = Blueprint("api_import", __name__, url_prefix="/api/import")


@bp.get("/template/<item_type>")
@admin_required
def download_import_template(item_type: str):
    get_spec_definition(item_type)
    xlsx_bytes = import_service.generate_import_template_xlsx(item_type)
    resp = make_response(xlsx_bytes)
    resp.headers["Content-Type"] = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    resp.headers["Content-Disposition"] = (
        f'attachment; filename="template_{item_type}.xlsx"'
    )
    return resp


@bp.post("/upload")
@admin_required
def upload_import_file():
    item_type = (request.form.get("item_type") or "").strip()
    get_spec_definition(item_type)

    upload_id, _ = save_uploaded_xlsx(
        request.files.get("file"),
        current_app.config["UPLOAD_DIR"],
        prefix=f"imp_{item_type}",
    )
    sheet_name = request.form.get("sheet_name") or None
    info = import_service.inspect_import_upload(
        upload_id=upload_id,
        upload_dir=current_app.config["UPLOAD_DIR"],
        item_type=item_type,
        sheet_name=sheet_name,
    )
    return jsonify(info)


@bp.post("/inspect")
@admin_required
def inspect_import_sheet():
    data = request.get_json(silent=True) or {}
    item_type = (data.get("item_type") or "").strip()
    get_spec_definition(item_type)

    info = import_service.inspect_import_upload(
        upload_id=data.get("upload_id"),
        upload_dir=current_app.config["UPLOAD_DIR"],
        item_type=item_type,
        sheet_name=data.get("sheet_name"),
    )
    return jsonify(info)


@bp.post("/preview")
@admin_required
def preview_import():
    data = request.get_json(silent=True) or {}
    item_type = (data.get("item_type") or "").strip()
    get_spec_definition(item_type)

    result = import_service.preview_import(
        upload_id=data.get("upload_id"),
        upload_dir=current_app.config["UPLOAD_DIR"],
        item_type=item_type,
        sheet_name=data.get("sheet_name"),
        column_mapping=data.get("column_mapping"),
        existing_policy=data.get("existing_policy", "skip"),
    )
    return jsonify(result)


@bp.post("/confirm")
@admin_required
def confirm_import():
    user = get_current_user()
    data = request.get_json(silent=True) or {}
    item_type = (data.get("item_type") or "").strip()
    get_spec_definition(item_type)

    result = import_service.confirm_import(
        upload_id=data.get("upload_id"),
        upload_dir=current_app.config["UPLOAD_DIR"],
        user_id=user["id"],
        item_type=item_type,
        sheet_name=data.get("sheet_name"),
        column_mapping=data.get("column_mapping"),
        existing_policy=data.get("existing_policy", "skip"),
    )
    return jsonify(result)
