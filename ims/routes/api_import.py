"""Initial inventory Excel import API endpoints."""

from flask import Blueprint, current_app, jsonify, request
from ims.auth import get_current_user, login_required
from ims.services import import_service
from ims.utils import save_uploaded_xlsx

bp = Blueprint("api_import", __name__, url_prefix="/api/import")


@bp.post("/upload")
@login_required
def upload_import_file():
    upload_id, _ = save_uploaded_xlsx(
        request.files.get("file"),
        current_app.config["UPLOAD_DIR"],
        prefix="imp",
    )
    sheet_name = request.form.get("sheet_name") or None
    info = import_service.inspect_import_upload(
        upload_id=upload_id,
        upload_dir=current_app.config["UPLOAD_DIR"],
        sheet_name=sheet_name,
    )
    return jsonify(info)


@bp.post("/inspect")
@login_required
def inspect_import_sheet():
    data = request.get_json(silent=True) or {}
    info = import_service.inspect_import_upload(
        upload_id=data.get("upload_id"),
        upload_dir=current_app.config["UPLOAD_DIR"],
        sheet_name=data.get("sheet_name"),
    )
    return jsonify(info)


@bp.post("/preview")
@login_required
def preview_import():
    data = request.get_json(silent=True) or {}
    result = import_service.preview_import(
        upload_id=data.get("upload_id"),
        upload_dir=current_app.config["UPLOAD_DIR"],
        sheet_name=data.get("sheet_name"),
        column_mapping=data.get("column_mapping"),
        existing_policy=data.get("existing_policy", "skip"),
    )
    return jsonify(result)


@bp.post("/confirm")
@login_required
def confirm_import():
    user = get_current_user()
    data = request.get_json(silent=True) or {}
    result = import_service.confirm_import(
        upload_id=data.get("upload_id"),
        upload_dir=current_app.config["UPLOAD_DIR"],
        user_id=user["id"],
        sheet_name=data.get("sheet_name"),
        column_mapping=data.get("column_mapping"),
        existing_policy=data.get("existing_policy", "skip"),
    )
    return jsonify(result)
