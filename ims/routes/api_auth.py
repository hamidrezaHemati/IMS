"""Authentication and internal user management API endpoints."""

from flask import Blueprint, jsonify, request, session
import psycopg2
from ims.auth import authenticate_user, get_current_user, login_required, prepare_password, verify_password
from ims.db import AppError, get_db, translate_pg_error
from ims.utils import clean_text

bp = Blueprint("api_auth", __name__, url_prefix="/api")


@bp.post("/auth/login")
def login():
    data = request.get_json(silent=True) or {}
    user = authenticate_user(data.get("user_name"), data.get("password"))
    session["user_id"] = user["id"]
    session.permanent = False
    return jsonify({"user": user})


@bp.post("/auth/logout")
def logout():
    session.clear()
    return jsonify({"ok": True})


@bp.get("/auth/me")
@login_required
def me():
    return jsonify({"user": get_current_user()})


@bp.get("/users")
@login_required
def list_users():
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT
                u.id,
                u.first_name,
                u.last_name,
                u.user_name,
                u.created_at,
                COUNT(t.id)::INT AS transaction_count
            FROM app_user u
            LEFT JOIN inventory_transaction t ON t.user_id = u.id
            GROUP BY u.id
            ORDER BY u.id ASC;
            """
        )
        users = [dict(r) for r in cur.fetchall()]
    return jsonify({"users": users})


@bp.post("/users")
@login_required
def create_user():
    data = request.get_json(silent=True) or {}
    first_name = clean_text(data.get("first_name"), max_len=100)
    last_name = clean_text(data.get("last_name"), max_len=100)
    user_name = clean_text(data.get("user_name"), max_len=80)
    password = data.get("password") or ""

    if not first_name or not last_name or not user_name or not password:
        raise AppError("First name, last name, username, and password are required.")
    if " " in user_name:
        raise AppError("Username cannot contain spaces.")

    stored_pw = prepare_password(password)
    db = get_db()
    try:
        with db.transaction() as cur:
            cur.execute(
                """
                INSERT INTO app_user (first_name, last_name, user_name, password_hash)
                VALUES (%s, %s, %s, %s)
                RETURNING id, first_name, last_name, user_name, created_at;
                """,
                (first_name, last_name, user_name, stored_pw),
            )
            user = dict(cur.fetchone())
    except psycopg2.Error as exc:
        raise translate_pg_error(exc) from exc

    user["transaction_count"] = 0
    return jsonify({"user": user}), 201


@bp.put("/users/me/password")
@login_required
def change_my_password():
    current_user = get_current_user()
    data = request.get_json(silent=True) or {}
    current_password = data.get("current_password") or ""
    new_password = data.get("new_password") or ""

    if not current_password or not new_password:
        raise AppError("Current password and new password are required.")

    db = get_db()
    with db.transaction() as cur:
        cur.execute(
            "SELECT password_hash FROM app_user WHERE id = %s;",
            (current_user["id"],),
        )
        row = cur.fetchone()
        if not row or not verify_password(row["password_hash"], current_password):
            raise AppError("Current password is incorrect.", status_code=400)

        cur.execute(
            "UPDATE app_user SET password_hash = %s WHERE id = %s;",
            (prepare_password(new_password), current_user["id"]),
        )

    return jsonify({"ok": True})
