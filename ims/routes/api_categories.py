"""Category hierarchy API endpoints."""

from flask import Blueprint, jsonify, request
from ims.auth import login_required
from ims.services import category_service

bp = Blueprint("api_categories", __name__, url_prefix="/api/categories")


@bp.get("")
@login_required
def get_categories():
    flat = category_service.list_categories()
    tree = category_service.get_category_tree()
    return jsonify({"categories": flat, "tree": tree})


@bp.post("")
@login_required
def create_category():
    data = request.get_json(silent=True) or {}
    category = category_service.create_category(data)
    return jsonify({"category": category}), 201


@bp.put("/<int:category_id>")
@login_required
def update_category(category_id: int):
    data = request.get_json(silent=True) or {}
    category = category_service.update_category(category_id, data)
    return jsonify({"category": category})


@bp.delete("/<int:category_id>")
@login_required
def delete_category(category_id: int):
    category_service.delete_category(category_id)
    return jsonify({"ok": True})
