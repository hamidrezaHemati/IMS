"""PostgreSQL connection pooling, transaction helpers, and error translation."""

from contextlib import contextmanager
from flask import current_app
import psycopg2
from psycopg2 import errors as pg_errors
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool


class AppError(Exception):
    """Domain or validation error surfaced cleanly as an HTTP JSON response."""

    def __init__(
        self,
        message: str,
        status_code: int = 400,
        code: str = "bad_request",
        details: dict | list | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code
        self.details = details


_UNIQUE_CONSTRAINT_MESSAGES = {
    "app_user_user_name_key": "This username is already taken.",
    "item_item_code_key": "An item with this item code already exists.",
    "inventory_item_id_key": "An inventory record already exists for this item.",
}

_FK_CONSTRAINT_MESSAGES = {
    "fk_category_parent": "Cannot delete this category because it still has subcategories.",
    "fk_item_category": "Cannot delete or change this category because items are assigned to it.",
    "fk_transaction_item": "This item cannot be deleted because it has inventory transactions.",
    "fk_transaction_user": "This user cannot be deleted because they have recorded transactions.",
    "fk_inventory_item": "Inventory record references this item.",
    "fk_user_role": "Cannot delete this role because users are assigned to it.",
    "fk_ura_role": "Cannot delete this role because user role assignments reference it.",
}

_CHECK_CONSTRAINT_MESSAGES = {
    "chk_category_not_own_parent": "A category cannot be its own parent.",
    "chk_electronic_mounting_type": "Mounting type must be either SMD or DIP.",
    "chk_spacer_diameter": "Spacer diameter (mm) must be greater than zero.",
    "chk_spacer_length": "Spacer length (mm) must be greater than zero.",
    "chk_spacer_material": "Spacer material must be STAINLESS_STEEL or PLASTIC.",
    "chk_spacer_type": "Spacer type must be F or H.",
    "chk_screw_diameter": "Screw diameter (mm) must be greater than zero.",
    "chk_screw_length": "Screw length (mm) must be greater than zero.",
    "chk_screw_material": "Screw material must be STAINLESS_STEEL, BLACK, or WHITE.",
    "chk_screw_head_type": "Screw head type must be one of: سرخزینه, آلنی, قارچی, مغزی.",
    "chk_screw_drive_type": "Screw drive type must be one of: چهارسو, آلنی.",
    "chk_nut_diameter": "Nut diameter (mm) must be greater than zero.",
    "chk_nut_material": "Nut material must be STAINLESS_STEEL, IRON, or PLASTIC.",
    "chk_washer_diameter": "Washer diameter (mm) must be greater than zero.",
    "chk_washer_type": "Washer type must be PLAIN or SPRING.",
    "chk_washer_material": "Washer material must be STAINLESS_STEEL, IRON, PLASTIC, or PAPER.",
    "chk_o_ring_inner_diameter": "O-Ring inner diameter (mm) must be greater than zero.",
    "chk_o_ring_outer_gt_inner": "O-Ring outer diameter must be strictly greater than inner diameter.",
    "chk_o_ring_material": "O-Ring material must be NBR, VITON, or SILICONE.",
    "chk_inventory_quantity": "Inventory quantity cannot be negative.",
    "chk_transaction_quantity": "Transaction quantity must be a positive integer.",
    "chk_transaction_type": "Unsupported transaction type.",
    "chk_transaction_price_nonnegative": "Price cannot be negative.",
    "chk_transaction_price_by_type": "Price is required for PURCHASE_IN and must be omitted for outgoing transactions.",
}


def translate_pg_error(exc: psycopg2.Error) -> AppError:
    """Translate PostgreSQL driver/trigger exceptions into user-friendly AppError."""
    diag = getattr(exc, "diag", None)
    constraint = getattr(diag, "constraint_name", None) if diag else None
    primary_msg = getattr(diag, "message_primary", None) if diag else None

    if isinstance(exc, pg_errors.RaiseException):
        msg = primary_msg or str(exc).splitlines()[0]
        return AppError(msg, status_code=400, code="trigger_validation_error")

    if isinstance(exc, pg_errors.UniqueViolation):
        msg = _UNIQUE_CONSTRAINT_MESSAGES.get(
            constraint,
            primary_msg or "A record with the same unique identifier already exists.",
        )
        return AppError(msg, status_code=409, code="conflict")

    if isinstance(exc, (pg_errors.ForeignKeyViolation, pg_errors.RestrictViolation)):
        msg = _FK_CONSTRAINT_MESSAGES.get(
            constraint,
            primary_msg or "Operation blocked because this record is referenced by other data.",
        )
        return AppError(msg, status_code=409, code="foreign_key_violation")

    if isinstance(exc, pg_errors.CheckViolation):
        msg = _CHECK_CONSTRAINT_MESSAGES.get(
            constraint,
            primary_msg or "Submitted values failed database validation.",
        )
        return AppError(msg, status_code=400, code="check_violation")

    if isinstance(exc, pg_errors.NotNullViolation):
        col = getattr(diag, "column_name", None) if diag else None
        msg = f"Field '{col}' is required." if col else "A required field is missing."
        return AppError(msg, status_code=400, code="missing_field")

    if isinstance(exc, pg_errors.NumericValueOutOfRange):
        return AppError(
            "Numeric value is out of range (max 4 decimal places for prices).",
            status_code=400,
            code="numeric_overflow",
        )

    if isinstance(exc, pg_errors.StringDataRightTruncation):
        return AppError(
            "A text value exceeds the maximum allowed column length.",
            status_code=400,
            code="value_too_long",
        )

    fallback = primary_msg or str(exc).splitlines()[0]
    return AppError(f"Database error: {fallback}", status_code=500, code="database_error")


class Database:
    """Thread-safe PostgreSQL connection pool wrapper."""

    def __init__(self, db_config: dict, minconn: int = 2, maxconn: int = 20):
        self.db_config = db_config
        self.pool = ThreadedConnectionPool(minconn, maxconn, **db_config)

    @contextmanager
    def connection(self):
        """Acquire a connection from the pool and return it cleanly."""
        conn = self.pool.getconn()
        try:
            yield conn
        finally:
            self.pool.putconn(conn)

    @contextmanager
    def cursor(self, commit: bool = False):
        """Acquire a RealDictCursor, optionally committing on exit."""
        with self.connection() as conn:
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    yield cur
                if commit:
                    conn.commit()
                else:
                    conn.rollback()
            except Exception:
                conn.rollback()
                raise

    @contextmanager
    def transaction(self):
        """Run operations inside an explicit PostgreSQL transaction."""
        with self.cursor(commit=True) as cur:
            yield cur

    def close(self):
        """Close all pooled database connections."""
        if self.pool:
            self.pool.closeall()


def get_db() -> Database:
    """Return the active Database instance from the current Flask app."""
    return current_app.extensions["db"]
