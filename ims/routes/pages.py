"""HTML page routes for the Inventory Management System."""

from flask import Blueprint, redirect, render_template, url_for
from ims.auth import admin_required, get_current_user, login_required

bp = Blueprint("pages", __name__)


@bp.get("/login")
def login():
    if get_current_user() is not None:
        return redirect(url_for("pages.dashboard"))
    return render_template("login.html", active_page="login")


@bp.get("/")
@login_required
def dashboard():
    return render_template("dashboard.html", active_page="dashboard")


@bp.get("/inventory")
@login_required
def inventory():
    return render_template("inventory.html", active_page="inventory")


@bp.get("/transactions/new")
@login_required
def new_transaction():
    return render_template("new_transaction.html", active_page="new_transaction")


@bp.get("/bom")
@login_required
def bom():
    return render_template("bom.html", active_page="bom")


@bp.get("/transactions")
@login_required
def transactions():
    return render_template("transactions.html", active_page="transactions")


@bp.get("/reports")
@login_required
def reports():
    return render_template("reports.html", active_page="reports")


@bp.get("/excel")
@admin_required
def excel():
    return render_template("excel.html", active_page="excel")


@bp.get("/users")
@login_required
def users():
    return render_template("users.html", active_page="users")
