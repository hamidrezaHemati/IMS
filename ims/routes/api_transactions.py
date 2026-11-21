"""Inventory transaction API endpoints (single, cart bulk, and history)."""

from flask import Blueprint, jsonify, request
from ims.auth import get_current_user, login_required
from ims.db import AppError
from ims.services import transaction_service
from ims.utils import parse_optional_int

bp = Blueprint("api_transactions", __name__, url_prefix="/api/transactions")


@bp.get("")
@login_required
def list_transactions():
    filters = request.args.to_dict()
    return jsonify(transaction_service.list_transactions(filters, paginate=True))


@bp.post("")
@login_required
def create_transaction():
    user = get_current_user()
    data = request.get_json(silent=True) or {}
    item_id = parse_optional_int(data.get("item_id"), "item_id")
    if item_id is None or item_id <= 0:
        raise AppError("Valid item_id is required.")

    result = transaction_service.process_single_transaction(
        user_id=user["id"],
        item_id=item_id,
        tx_type=data.get("transaction_type"),
        quantity_raw=data.get("quantity"),
        price_raw=data.get("price"),
        description=data.get("description"),
    )
    return jsonify(result), 201


@bp.post("/bulk")
@login_required
def bulk_transactions():
    user = get_current_user()
    data = request.get_json(silent=True) or {}
    result = transaction_service.submit_cart_transactions(
        user_id=user["id"],
        tx_type=data.get("transaction_type"),
        cart_items=data.get("items"),
        shared_description=data.get("description"),
    )
    return jsonify(result)
