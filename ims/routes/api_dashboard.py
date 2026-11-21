"""Dashboard summary and analytics API endpoints."""

from flask import Blueprint, jsonify, request
from ims.auth import login_required
from ims.services import inventory_service

bp = Blueprint("api_dashboard", __name__, url_prefix="/api")


@bp.get("/dashboard/summary")
@login_required
def dashboard_summary():
    return jsonify(inventory_service.get_dashboard_summary())


@bp.get("/reports/analytics")
@login_required
def reports_analytics():
    return jsonify(
        inventory_service.get_analytics(
            date_from=request.args.get("date_from"),
            date_to=request.args.get("date_to"),
        )
    )
