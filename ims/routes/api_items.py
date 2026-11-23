"""Items and inventory query/CRUD API endpoints."""

from flask import Blueprint, jsonify, request
from ims.auth import login_required
from ims.item_specs import get_public_schema
from ims.services import item_service

bp = Blueprint("api_items", __name__, url_prefix="/api/items")


@bp.get("/spec-schema")
@login_required
def spec_schema():
    return jsonify(get_public_schema())


@bp.get("")
@login_required
def list_items():
    filters = request.args.to_dict()
    return jsonify(item_service.list_items(filters, paginate=True))


@bp.post("")
@login_required
def create_item():
    data = request.get_json(silent=True) or {}
    item = item_service.create_item(data)
    return jsonify({"item": item}), 201


@bp.get("/filter-options")
@login_required
def filter_options():
    return jsonify(item_service.get_filter_options())


@bp.get("/<int:item_id>")
@login_required
def get_item(item_id: int):
    item = item_service.get_item_detail(item_id)
    return jsonify({"item": item})


@bp.put("/<int:item_id>")
@login_required
def update_item(item_id: int):
    data = request.get_json(silent=True) or {}
    item = item_service.update_item(item_id, data)
    return jsonify({"item": item})
