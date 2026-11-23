"""Excel export API endpoints for filtered inventory and movement reports."""

from flask import Blueprint, make_response, request
from ims.auth import login_required
from ims.jalali import format_jalali_filename_stamp
from ims.services import export_service

bp = Blueprint("api_export", __name__, url_prefix="/api/export")


@bp.get("/inventory")
@login_required
def export_inventory():
    filters = request.args.to_dict()
    xlsx_bytes = export_service.export_inventory_xlsx(filters)
    stamp = format_jalali_filename_stamp()

    resp = make_response(xlsx_bytes)
    resp.headers["Content-Type"] = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    resp.headers["Content-Disposition"] = (
        f'attachment; filename="inventory_report_{stamp}.xlsx"'
    )
    return resp


@bp.get("/transactions")
@login_required
def export_transactions():
    filters = request.args.to_dict()
    xlsx_bytes = export_service.export_transactions_xlsx(filters)
    stamp = format_jalali_filename_stamp()

    resp = make_response(xlsx_bytes)
    resp.headers["Content-Type"] = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    resp.headers["Content-Disposition"] = (
        f'attachment; filename="transactions_report_{stamp}.xlsx"'
    )
    return resp
