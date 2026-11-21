"""Session-based authentication helpers using the existing app_user table."""

from functools import wraps
import hmac
from flask import g, jsonify, redirect, request, session, url_for
from ims.db import AppError, get_db


def prepare_password(raw_password: str) -> str:
    """Return password value for storage in app_user.password_hash.

    Plaintext storage is intentionally kept for now per project owner direction
    so existing seeded credentials remain compatible until hashing is enabled.
    """
    return raw_password


def verify_password(stored_value: str | None, provided_password: str | None) -> bool:
    """Verify a password against app_user.password_hash in constant time."""
    if not stored_value or provided_password is None:
        return False
    return hmac.compare_digest(stored_value, provided_password)


def authenticate_user(user_name: str, password: str) -> dict:
    """Validate credentials against app_user and return public user fields."""
    clean_username = (user_name or "").strip()
    if not clean_username or not password:
        raise AppError("Username and password are required.", status_code=400)

    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT id, first_name, last_name, user_name, password_hash, created_at
              FROM app_user
             WHERE user_name = %s;
            """,
            (clean_username,),
        )
        row = cur.fetchone()

    if not row or not verify_password(row["password_hash"], password):
        raise AppError("Invalid username or password.", status_code=401, code="invalid_credentials")

    return {
        "id": row["id"],
        "first_name": row["first_name"],
        "last_name": row["last_name"],
        "user_name": row["user_name"],
        "created_at": row["created_at"],
    }


def get_current_user() -> dict | None:
    """Fetch the currently signed-in user from the database, cached per request."""
    if hasattr(g, "current_user"):
        return g.current_user

    user_id = session.get("user_id")
    if not user_id:
        g.current_user = None
        return None

    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT id, first_name, last_name, user_name, created_at
              FROM app_user
             WHERE id = %s;
            """,
            (user_id,),
        )
        user = cur.fetchone()

    if not user:
        session.pop("user_id", None)
        g.current_user = None
        return None

    g.current_user = dict(user)
    return g.current_user


def login_required(view):
    """Require an authenticated user for API endpoints and page routes."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = get_current_user()
        if user is None:
            if request.path.startswith("/api/"):
                return jsonify({
                    "error": "Authentication required.",
                    "code": "unauthorized",
                }), 401
            return redirect(url_for("pages.login", next=request.full_path.rstrip("?")))
        return view(*args, **kwargs)

    return wrapped
