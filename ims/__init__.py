"""Flask application factory for the Inventory Management System (IMS)."""

from datetime import date, datetime
from decimal import Decimal
from flask import Flask, jsonify, request
from flask.json.provider import DefaultJSONProvider
from werkzeug.exceptions import HTTPException
from ims.auth import get_current_user
from ims.config import build_flask_config
from ims.db import AppError, Database


class ImsJsonProvider(DefaultJSONProvider):
    """Serialize Decimal and datetime cleanly for API JSON responses."""

    @staticmethod
    def default(obj):
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        return DefaultJSONProvider.default(obj)


def create_app(test_config: dict | None = None) -> Flask:
    """Create and configure the IMS Flask application."""
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    app.json = ImsJsonProvider(app)

    cfg = build_flask_config(test_config)
    app.config.update(cfg)

    db = Database(app.config["DB_CONFIG"])
    app.extensions["db"] = db

    @app.context_processor
    def inject_globals():
        return {"current_user": get_current_user()}

    @app.errorhandler(AppError)
    def handle_app_error(exc: AppError):
        payload = {"error": exc.message, "code": exc.code}
        if exc.details is not None:
            payload["details"] = exc.details
        return jsonify(payload), exc.status_code

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc: HTTPException):
        if request.path.startswith("/api/"):
            return jsonify({"error": exc.description, "code": exc.name.lower().replace(" ", "_")}), exc.code
        return exc

    @app.errorhandler(Exception)
    def handle_unexpected_error(exc: Exception):
        app.logger.exception("Unhandled error during request %s", request.path)
        if request.path.startswith("/api/"):
            return jsonify({
                "error": "An unexpected internal server error occurred.",
                "code": "internal_error",
            }), 500
        return "Internal Server Error", 500

    from ims.routes import (
        api_auth,
        api_bom,
        api_categories,
        api_dashboard,
        api_export,
        api_import,
        api_items,
        api_transactions,
        pages,
    )

    app.register_blueprint(pages.bp)
    app.register_blueprint(api_auth.bp)
    app.register_blueprint(api_categories.bp)
    app.register_blueprint(api_items.bp)
    app.register_blueprint(api_transactions.bp)
    app.register_blueprint(api_dashboard.bp)
    app.register_blueprint(api_import.bp)
    app.register_blueprint(api_bom.bp)
    app.register_blueprint(api_export.bp)

    return app
