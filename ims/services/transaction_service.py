"""Inventory transaction processing, cart submission, and history queries."""

from decimal import Decimal
import math
import psycopg2
from ims.db import AppError, get_db, translate_pg_error
from ims.services.item_service import CAT_INFO_CTE
from ims.utils import (
    clean_text,
    parse_optional_int,
    parse_optional_price,
    parse_positive_int,
)


ALLOWED_TRANSACTION_TYPES = (
    "OPENING",
    "PURCHASE_IN",
    "OUT",
    "ADJUSTMENT_IN",
    "ADJUSTMENT_OUT",
)

INCOMING_TYPES = ("OPENING", "PURCHASE_IN", "ADJUSTMENT_IN")
OUTGOING_TYPES = ("OUT", "ADJUSTMENT_OUT")


def _validate_tx_inputs(tx_type: str, quantity_raw, price_raw) -> tuple[str, int, Decimal | None]:
    clean_type = (tx_type or "").strip().upper()
    if clean_type not in ALLOWED_TRANSACTION_TYPES:
        raise AppError(
            f"Unsupported transaction type '{tx_type}'. Allowed: {', '.join(ALLOWED_TRANSACTION_TYPES)}."
        )

    quantity = parse_positive_int(quantity_raw, "quantity")
    price = parse_optional_price(price_raw, "price")

    if clean_type == "PURCHASE_IN" and price is None:
        raise AppError("Unit price is required for PURCHASE_IN transactions.")

    if clean_type in OUTGOING_TYPES and price is not None:
        raise AppError(
            "Price must not be specified for OUT or ADJUSTMENT_OUT transactions; cost comes from weighted average cost."
        )

    return clean_type, quantity, price


def process_single_transaction(
    user_id: int,
    item_id: int,
    tx_type: str,
    quantity_raw,
    price_raw=None,
    description: str | None = None,
) -> dict:
    """Insert one inventory_transaction row inside its own PostgreSQL transaction.

    All stock checks, locking (SELECT ... FOR UPDATE), stock_before/stock_after,
    cost snapshots, and inventory updates are executed by PostgreSQL triggers.
    """
    clean_type, quantity, price = _validate_tx_inputs(tx_type, quantity_raw, price_raw)
    clean_desc = clean_text(description)

    db = get_db()
    try:
        with db.transaction() as cur:
            cur.execute(
                """
                INSERT INTO inventory_transaction (
                    user_id, item_id, quantity, transaction_type, price, description
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING
                    id, user_id, item_id, quantity, transaction_type, price,
                    stock_before, stock_after, unit_cost_snapshot,
                    transaction_cost_snapshot, created_at, description;
                """,
                (user_id, item_id, quantity, clean_type, price, clean_desc),
            )
            tx_row = dict(cur.fetchone())

            cur.execute(
                """
                SELECT
                    i.item_code,
                    i.model,
                    inv.quantity AS current_quantity,
                    inv.weighted_avg_cost,
                    inv.last_purchase_cost,
                    inv.updated_at AS inventory_updated_at
                  FROM item i
                  JOIN inventory inv ON inv.item_id = i.id
                 WHERE i.id = %s;
                """,
                (item_id,),
            )
            inv_row = dict(cur.fetchone())
    except psycopg2.Error as exc:
        raise translate_pg_error(exc) from exc

    return {
        "transaction": tx_row,
        "inventory": inv_row,
    }


def _fetch_item_context(item_id: int) -> dict | None:
    """Read current item/inventory metadata for reporting failed cart entries."""
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT i.id, i.item_code, i.model, inv.quantity AS available_quantity
              FROM item i
              LEFT JOIN inventory inv ON inv.item_id = i.id
             WHERE i.id = %s;
            """,
            (item_id,),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def submit_cart_transactions(
    user_id: int,
    tx_type: str,
    cart_items: list[dict],
    shared_description: str | None = None,
) -> dict:
    """Aggregate duplicate cart items and process each distinct item independently.

    One item failing stock validation does not abort valid items in the same cart.
    """
    clean_type = (tx_type or "").strip().upper()
    if clean_type not in ALLOWED_TRANSACTION_TYPES:
        raise AppError(
            f"Unsupported transaction type '{tx_type}'. Allowed: {', '.join(ALLOWED_TRANSACTION_TYPES)}."
        )

    if not isinstance(cart_items, list) or not cart_items:
        raise AppError("Transaction cart is empty.")

    shared_note = clean_text(shared_description)

    aggregated: dict[int, dict] = {}
    order_keys: list = []
    orphan_failures: list[dict] = []

    for idx, entry in enumerate(cart_items):
        if not isinstance(entry, dict):
            orphan_failures.append({
                "item_id": None,
                "item_code": None,
                "model": None,
                "requested_quantity": None,
                "status": "failed",
                "error": f"Cart row #{idx + 1} has invalid format.",
            })
            continue

        try:
            item_id = parse_optional_int(entry.get("item_id"), "item_id")
            if item_id is None or item_id <= 0:
                raise AppError("Valid item_id is required.")
        except AppError as exc:
            orphan_failures.append({
                "item_id": entry.get("item_id"),
                "item_code": None,
                "model": None,
                "requested_quantity": entry.get("quantity"),
                "status": "failed",
                "error": exc.message,
            })
            continue

        if item_id not in aggregated:
            aggregated[item_id] = {
                "item_id": item_id,
                "total_quantity": 0,
                "price_set": False,
                "price": None,
                "notes": [],
                "merged_rows": 0,
                "validation_error": None,
            }
            order_keys.append(item_id)

        bucket = aggregated[item_id]
        bucket["merged_rows"] += 1
        note = clean_text(entry.get("description"))
        if note and note not in bucket["notes"]:
            bucket["notes"].append(note)

        if bucket["validation_error"]:
            continue

        try:
            _, qty, price = _validate_tx_inputs(
                clean_type,
                entry.get("quantity"),
                entry.get("price"),
            )
            if not bucket["price_set"]:
                bucket["price"] = price
                bucket["price_set"] = True
            elif bucket["price"] != price:
                raise AppError(
                    "Duplicate cart rows for the same component specify conflicting prices."
                )
            bucket["total_quantity"] += qty
        except AppError as exc:
            bucket["validation_error"] = exc.message

    results: list[dict] = []
    succeeded = 0
    failed = 0

    for err_row in orphan_failures:
        failed += 1
        results.append(err_row)

    for item_id in order_keys:
        bucket = aggregated[item_id]
        combined_note = "; ".join(bucket["notes"]) if bucket["notes"] else shared_note

        if bucket["validation_error"]:
            ctx = _fetch_item_context(item_id) or {}
            failed += 1
            results.append({
                "item_id": item_id,
                "item_code": ctx.get("item_code"),
                "model": ctx.get("model"),
                "available_quantity": ctx.get("available_quantity"),
                "requested_quantity": bucket["total_quantity"] or None,
                "merged_rows": bucket["merged_rows"],
                "status": "failed",
                "error": bucket["validation_error"],
            })
            continue

        try:
            outcome = process_single_transaction(
                user_id=user_id,
                item_id=item_id,
                tx_type=clean_type,
                quantity_raw=bucket["total_quantity"],
                price_raw=bucket["price"],
                description=combined_note,
            )
            tx = outcome["transaction"]
            inv = outcome["inventory"]
            succeeded += 1
            results.append({
                "item_id": item_id,
                "item_code": inv["item_code"],
                "model": inv["model"],
                "requested_quantity": bucket["total_quantity"],
                "merged_rows": bucket["merged_rows"],
                "status": "succeeded",
                "transaction": tx,
                "inventory": inv,
            })
        except AppError as exc:
            ctx = _fetch_item_context(item_id) or {}
            failed += 1
            results.append({
                "item_id": item_id,
                "item_code": ctx.get("item_code"),
                "model": ctx.get("model"),
                "available_quantity": ctx.get("available_quantity"),
                "requested_quantity": bucket["total_quantity"],
                "merged_rows": bucket["merged_rows"],
                "status": "failed",
                "error": exc.message,
            })

    return {
        "transaction_type": clean_type,
        "summary": {
            "total": succeeded + failed,
            "succeeded": succeeded,
            "failed": failed,
        },
        "results": results,
    }


def build_transaction_filter_sql(filters: dict) -> tuple[str, list]:
    """Build parameterized WHERE conditions for transaction history and export."""
    clauses = []
    params: list = []

    item_id = parse_optional_int(filters.get("item_id"), "item_id")
    if item_id is not None:
        clauses.append("t.item_id = %s")
        params.append(item_id)

    user_id = parse_optional_int(filters.get("user_id"), "user_id")
    if user_id is not None:
        clauses.append("t.user_id = %s")
        params.append(user_id)

    item_code = clean_text(filters.get("item_code"))
    if item_code:
        clauses.append("i.item_code ILIKE %s")
        params.append(f"%{item_code}%")

    search = clean_text(filters.get("search"))
    if search:
        like = f"%{search}%"
        clauses.append(
            "(i.item_code ILIKE %s OR i.model ILIKE %s OR COALESCE(t.description, '') ILIKE %s OR u.user_name ILIKE %s)"
        )
        params.extend([like, like, like, like])

    tx_type_raw = clean_text(filters.get("transaction_type"))
    if tx_type_raw:
        types = [part.strip().upper() for part in tx_type_raw.split(",") if part.strip()]
        invalid = [t for t in types if t not in ALLOWED_TRANSACTION_TYPES]
        if invalid:
            raise AppError(f"Invalid transaction type filter: {', '.join(invalid)}")
        if types:
            clauses.append("t.transaction_type = ANY(%s)")
            params.append(types)

    date_from = clean_text(filters.get("date_from"))
    if date_from:
        clauses.append("t.created_at >= %s::date")
        params.append(date_from)

    date_to = clean_text(filters.get("date_to"))
    if date_to:
        clauses.append("t.created_at < (%s::date + INTERVAL '1 day')")
        params.append(date_to)

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return where_sql, params


def list_transactions(filters: dict, paginate: bool = True) -> dict:
    """Query inventory_transaction history with server-side filters and pagination."""
    where_sql, params = build_transaction_filter_sql(filters)

    page = max(1, parse_optional_int(filters.get("page"), "page") or 1)
    page_size = parse_optional_int(filters.get("page_size"), "page_size") or 30
    page_size = max(1, min(page_size, 200))
    offset = (page - 1) * page_size

    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            f"""
            SELECT COUNT(*)::INT AS total
              FROM inventory_transaction t
              JOIN item i ON i.id = t.item_id
              JOIN app_user u ON u.id = t.user_id
            {where_sql};
            """,
            tuple(params),
        )
        total = cur.fetchone()["total"]

        limit_sql = "LIMIT %s OFFSET %s" if paginate else ""
        query_params = list(params) + ([page_size, offset] if paginate else [])
        cur.execute(
            f"""
            {CAT_INFO_CTE}
            SELECT
                t.id,
                t.user_id,
                u.user_name,
                u.first_name,
                u.last_name,
                t.item_id,
                i.item_code,
                i.model,
                ci.category_name,
                ci.subcategory_name,
                ci.category_path,
                t.quantity,
                t.transaction_type,
                t.price,
                t.stock_before,
                t.stock_after,
                t.unit_cost_snapshot,
                t.transaction_cost_snapshot,
                t.created_at,
                t.description
              FROM inventory_transaction t
              JOIN item i ON i.id = t.item_id
              JOIN cat_info ci ON ci.id = i.category_id
              JOIN app_user u ON u.id = t.user_id
            {where_sql}
            ORDER BY t.created_at DESC, t.id DESC
            {limit_sql};
            """,
            tuple(query_params),
        )
        rows = [dict(r) for r in cur.fetchall()]

    total_pages = max(1, math.ceil(total / page_size)) if paginate else 1
    return {
        "transactions": rows,
        "total": total,
        "page": page if paginate else 1,
        "page_size": page_size if paginate else total,
        "total_pages": total_pages,
    }
