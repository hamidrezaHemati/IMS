"""Items and inventory search, filtering, and CRUD service."""

import math
import psycopg2
from ims.db import AppError, get_db, translate_pg_error
from ims.jalali import format_jalali_datetime
from ims.utils import (
    clean_text,
    normalize_mounting_type,
    parse_bool_param,
    parse_nonnegative_int,
    parse_optional_int,
    parse_optional_price,
)


CAT_INFO_CTE = """
WITH RECURSIVE cat_info AS (
    SELECT
        c.id,
        c.parent_id,
        c.name AS leaf_name,
        c.id AS root_id,
        c.name AS root_name,
        c.name AS category_name,
        NULL::VARCHAR(100) AS subcategory_name,
        0 AS depth,
        c.name::TEXT AS category_path
    FROM category c
    WHERE c.parent_id IS NULL

    UNION ALL

    SELECT
        c.id,
        c.parent_id,
        c.name AS leaf_name,
        ci.root_id,
        ci.root_name,
        ci.root_name AS category_name,
        c.name AS subcategory_name,
        ci.depth + 1 AS depth,
        (ci.category_path || ' > ' || c.name) AS category_path
    FROM category c
    JOIN cat_info ci ON c.parent_id = ci.id
)
"""

_SORT_EXPRESSIONS = {
    "item_code": "LOWER(i.item_code)",
    "model": "LOWER(i.model)",
    "category": "LOWER(ci.category_path)",
    "location": "LOWER(i.location)",
    "quantity": "inv.quantity",
    "weighted_avg_cost": "inv.weighted_avg_cost",
    "last_purchase_cost": "inv.last_purchase_cost",
    "created_at": "i.created_at",
    "updated_at": "inv.updated_at",
}


def build_inventory_filter_sql(filters: dict) -> tuple[str, list]:
    """Build parameterized WHERE conditions shared by item search and Excel export."""
    clauses = []
    params: list = []

    search = clean_text(filters.get("search"))
    if search:
        like = f"%{search}%"
        clauses.append(
            """(
                i.item_code ILIKE %s
                OR COALESCE(i.model, '') ILIKE %s
                OR COALESCE(i.size, '') ILIKE %s
                OR COALESCE(i.material, '') ILIKE %s
                OR COALESCE(i.voltage, '') ILIKE %s
                OR i.location ILIKE %s
                OR COALESCE(i.description, '') ILIKE %s
                OR ci.category_name ILIKE %s
                OR COALESCE(ci.subcategory_name, '') ILIKE %s
            )"""
        )
        params.extend([like] * 9)

    text_ilike_fields = (
        ("item_code", "i.item_code"),
        ("model", "COALESCE(i.model, '')"),
        ("size", "COALESCE(i.size, '')"),
        ("material", "COALESCE(i.material, '')"),
        ("voltage", "COALESCE(i.voltage, '')"),
        ("location", "i.location"),
        ("description", "COALESCE(i.description, '')"),
    )
    for key, expr in text_ilike_fields:
        val = clean_text(filters.get(key))
        if val:
            clauses.append(f"{expr} ILIKE %s")
            params.append(f"%{val}%")

    mounting_raw = clean_text(filters.get("mounting_type"))
    if mounting_raw:
        mounting = normalize_mounting_type(mounting_raw)
        clauses.append("i.mounting_type = %s")
        params.append(mounting)

    parent_cat_id = parse_optional_int(filters.get("parent_category_id"), "parent_category_id")
    if parent_cat_id is not None:
        clauses.append(
            """i.category_id IN (
                WITH RECURSIVE sub AS (
                    SELECT id FROM category WHERE id = %s
                    UNION ALL
                    SELECT c.id FROM category c JOIN sub s ON c.parent_id = s.id
                )
                SELECT id FROM sub
            )"""
        )
        params.append(parent_cat_id)

    cat_id = parse_optional_int(filters.get("category_id"), "category_id")
    if cat_id is not None:
        clauses.append(
            """i.category_id IN (
                WITH RECURSIVE sub AS (
                    SELECT id FROM category WHERE id = %s
                    UNION ALL
                    SELECT c.id FROM category c JOIN sub s ON c.parent_id = s.id
                )
                SELECT id FROM sub
            )"""
        )
        params.append(cat_id)

    min_qty_raw = clean_text(filters.get("min_quantity"))
    if min_qty_raw is not None:
        min_qty = parse_nonnegative_int(min_qty_raw, "min_quantity")
        clauses.append("inv.quantity >= %s")
        params.append(min_qty)

    max_qty_raw = clean_text(filters.get("max_quantity"))
    if max_qty_raw is not None:
        max_qty = parse_nonnegative_int(max_qty_raw, "max_quantity")
        clauses.append("inv.quantity <= %s")
        params.append(max_qty)

    if parse_bool_param(filters.get("zero_stock")):
        clauses.append("inv.quantity = 0")

    below_raw = clean_text(filters.get("below_threshold"))
    if below_raw is not None:
        below_val = parse_nonnegative_int(below_raw, "below_threshold")
        clauses.append("inv.quantity < %s")
        params.append(below_val)

    min_wac = parse_optional_price(filters.get("min_wac"), "min_wac")
    if min_wac is not None:
        clauses.append("inv.weighted_avg_cost >= %s")
        params.append(min_wac)

    max_wac = parse_optional_price(filters.get("max_wac"), "max_wac")
    if max_wac is not None:
        clauses.append("inv.weighted_avg_cost <= %s")
        params.append(max_wac)

    min_lpc = parse_optional_price(filters.get("min_lpc"), "min_lpc")
    if min_lpc is not None:
        clauses.append("inv.last_purchase_cost >= %s")
        params.append(min_lpc)

    max_lpc = parse_optional_price(filters.get("max_lpc"), "max_lpc")
    if max_lpc is not None:
        clauses.append("inv.last_purchase_cost <= %s")
        params.append(max_lpc)

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return where_sql, params


def _build_order_sql(filters: dict) -> str:
    sort_by = (filters.get("sort_by") or "item_code").strip()
    sort_expr = _SORT_EXPRESSIONS.get(sort_by, _SORT_EXPRESSIONS["item_code"])
    sort_dir = (filters.get("sort_dir") or "asc").strip().lower()
    direction = "DESC" if sort_dir == "desc" else "ASC"
    nulls_clause = "NULLS LAST" if sort_by in ("model", "weighted_avg_cost", "last_purchase_cost") else ""
    return f"ORDER BY {sort_expr} {direction} {nulls_clause}, i.id ASC"


def list_items(filters: dict, paginate: bool = True) -> dict:
    """Query items joined with inventory and category path, with optional pagination."""
    where_sql, params = build_inventory_filter_sql(filters)
    order_sql = _build_order_sql(filters)

    page = max(1, parse_optional_int(filters.get("page"), "page") or 1)
    page_size = parse_optional_int(filters.get("page_size"), "page_size") or 25
    page_size = max(1, min(page_size, 200))
    offset = (page - 1) * page_size

    db = get_db()
    with db.cursor() as cur:
        count_sql = f"""
            {CAT_INFO_CTE}
            SELECT COUNT(*)::INT AS total
              FROM item i
              JOIN inventory inv ON inv.item_id = i.id
              JOIN cat_info ci ON ci.id = i.category_id
            {where_sql};
        """
        cur.execute(count_sql, tuple(params))
        total = cur.fetchone()["total"]

        limit_sql = "LIMIT %s OFFSET %s" if paginate else ""
        query_params = list(params) + ([page_size, offset] if paginate else [])

        data_sql = f"""
            {CAT_INFO_CTE}
            SELECT
                i.id,
                i.item_code,
                i.category_id,
                ci.root_id AS parent_category_id,
                ci.category_name,
                ci.subcategory_name,
                ci.category_path,
                i.model,
                i.size,
                i.mounting_type,
                i.voltage,
                i.material,
                i.location,
                i.description,
                i.created_at,
                inv.quantity,
                inv.weighted_avg_cost,
                inv.last_purchase_cost,
                inv.updated_at AS inventory_updated_at,
                CASE
                    WHEN inv.weighted_avg_cost IS NOT NULL
                    THEN ROUND(inv.quantity::NUMERIC * inv.weighted_avg_cost, 4)
                    ELSE NULL
                END AS total_wac_value,
                CASE
                    WHEN inv.last_purchase_cost IS NOT NULL
                    THEN ROUND(inv.quantity::NUMERIC * inv.last_purchase_cost, 4)
                    ELSE NULL
                END AS total_lpc_value
            FROM item i
            JOIN inventory inv ON inv.item_id = i.id
            JOIN cat_info ci ON ci.id = i.category_id
            {where_sql}
            {order_sql}
            {limit_sql};
        """
        cur.execute(data_sql, tuple(query_params))
        rows = []
        for r in cur.fetchall():
            item_dict = dict(r)
            item_dict["created_at_jalali"] = format_jalali_datetime(item_dict.get("created_at"))
            item_dict["inventory_updated_at_jalali"] = format_jalali_datetime(
                item_dict.get("inventory_updated_at")
            )
            rows.append(item_dict)

    total_pages = max(1, math.ceil(total / page_size)) if paginate else 1
    return {
        "items": rows,
        "total": total,
        "page": page if paginate else 1,
        "page_size": page_size if paginate else total,
        "total_pages": total_pages,
    }


def get_item_detail(item_id: int, tx_limit: int = 50) -> dict:
    """Return full item specifications, live inventory state, and recent transactions."""
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            f"""
            {CAT_INFO_CTE}
            SELECT
                i.id,
                i.item_code,
                i.category_id,
                ci.root_id AS parent_category_id,
                ci.category_name,
                ci.subcategory_name,
                ci.category_path,
                i.model,
                i.size,
                i.mounting_type,
                i.voltage,
                i.material,
                i.location,
                i.description,
                i.created_at,
                inv.quantity,
                inv.weighted_avg_cost,
                inv.last_purchase_cost,
                inv.updated_at AS inventory_updated_at,
                CASE
                    WHEN inv.weighted_avg_cost IS NOT NULL
                    THEN ROUND(inv.quantity::NUMERIC * inv.weighted_avg_cost, 4)
                    ELSE NULL
                END AS total_wac_value,
                CASE
                    WHEN inv.last_purchase_cost IS NOT NULL
                    THEN ROUND(inv.quantity::NUMERIC * inv.last_purchase_cost, 4)
                    ELSE NULL
                END AS total_lpc_value
            FROM item i
            JOIN inventory inv ON inv.item_id = i.id
            JOIN cat_info ci ON ci.id = i.category_id
            WHERE i.id = %s;
            """,
            (item_id,),
        )
        item_row = cur.fetchone()
        if not item_row:
            raise AppError("Item not found.", status_code=404)

        cur.execute(
            """
            SELECT
                t.id,
                t.user_id,
                u.user_name,
                u.first_name,
                u.last_name,
                t.item_id,
                t.quantity,
                t.transaction_type,
                t.price,
                t.stock_before,
                t.stock_after,
                t.unit_cost_snapshot,
                t.transaction_cost_snapshot,
                t.created_at,
                t.created_at_jalali,
                t.description
            FROM inventory_transaction t
            JOIN app_user u ON u.id = t.user_id
            WHERE t.item_id = %s
            ORDER BY t.created_at DESC, t.id DESC
            LIMIT %s;
            """,
            (item_id, tx_limit),
        )
        transactions = [dict(r) for r in cur.fetchall()]

    result = dict(item_row)
    result["created_at_jalali"] = format_jalali_datetime(result.get("created_at"))
    result["inventory_updated_at_jalali"] = format_jalali_datetime(
        result.get("inventory_updated_at")
    )
    result["transactions"] = transactions
    return result


def validate_item_payload(data: dict) -> dict:
    """Validate and normalize item specification fields."""
    item_code = clean_text(data.get("item_code"), max_len=80)
    if not item_code:
        raise AppError("Item code is required.")

    category_id = parse_optional_int(data.get("category_id"), "category_id")
    if category_id is None:
        raise AppError("Category is required.")

    model = clean_text(data.get("model"), max_len=150)

    location = clean_text(data.get("location"), max_len=150)
    if not location:
        raise AppError("Storage location is required.")

    return {
        "item_code": item_code,
        "category_id": category_id,
        "model": model,
        "size": clean_text(data.get("size"), max_len=50),
        "mounting_type": normalize_mounting_type(data.get("mounting_type")),
        "voltage": clean_text(data.get("voltage"), max_len=80),
        "material": clean_text(data.get("material"), max_len=100),
        "location": location,
        "description": clean_text(data.get("description")),
    }


def create_item(data: dict) -> dict:
    """Create a new item record; PostgreSQL trigger initializes its inventory row."""
    fields = validate_item_payload(data)

    db = get_db()
    try:
        with db.transaction() as cur:
            cur.execute("SELECT id FROM category WHERE id = %s;", (fields["category_id"],))
            if not cur.fetchone():
                raise AppError("Selected category does not exist.", status_code=404)

            cur.execute(
                """
                INSERT INTO item (
                    item_code, category_id, model, size, mounting_type,
                    voltage, material, location, description
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id;
                """,
                (
                    fields["item_code"],
                    fields["category_id"],
                    fields["model"],
                    fields["size"],
                    fields["mounting_type"],
                    fields["voltage"],
                    fields["material"],
                    fields["location"],
                    fields["description"],
                ),
            )
            item_id = cur.fetchone()["id"]
    except psycopg2.Error as exc:
        raise translate_pg_error(exc) from exc

    return get_item_detail(item_id, tx_limit=10)


def update_item(item_id: int, data: dict) -> dict:
    """Update item specifications only (never modifies inventory quantities or costs)."""
    fields = validate_item_payload(data)

    db = get_db()
    try:
        with db.transaction() as cur:
            cur.execute("SELECT id FROM item WHERE id = %s;", (item_id,))
            if not cur.fetchone():
                raise AppError("Item not found.", status_code=404)

            cur.execute("SELECT id FROM category WHERE id = %s;", (fields["category_id"],))
            if not cur.fetchone():
                raise AppError("Selected category does not exist.", status_code=404)

            cur.execute(
                """
                UPDATE item
                   SET item_code = %s,
                       category_id = %s,
                       model = %s,
                       size = %s,
                       mounting_type = %s,
                       voltage = %s,
                       material = %s,
                       location = %s,
                       description = %s
                 WHERE id = %s;
                """,
                (
                    fields["item_code"],
                    fields["category_id"],
                    fields["model"],
                    fields["size"],
                    fields["mounting_type"],
                    fields["voltage"],
                    fields["material"],
                    fields["location"],
                    fields["description"],
                    item_id,
                ),
            )
    except psycopg2.Error as exc:
        raise translate_pg_error(exc) from exc

    return get_item_detail(item_id, tx_limit=20)


def get_filter_options() -> dict:
    """Return distinct attribute values to populate filter suggestions in the UI."""
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT
                ARRAY(
                    SELECT DISTINCT mounting_type FROM item
                     WHERE mounting_type IS NOT NULL ORDER BY mounting_type
                ) AS mounting_types,
                ARRAY(
                    SELECT DISTINCT material FROM item
                     WHERE material IS NOT NULL ORDER BY material
                ) AS materials,
                ARRAY(
                    SELECT DISTINCT voltage FROM item
                     WHERE voltage IS NOT NULL ORDER BY voltage
                ) AS voltages,
                ARRAY(
                    SELECT DISTINCT location FROM item
                     WHERE location IS NOT NULL ORDER BY location
                ) AS locations,
                ARRAY(
                    SELECT DISTINCT size FROM item
                     WHERE size IS NOT NULL ORDER BY size
                ) AS sizes;
            """
        )
        row = cur.fetchone()
    return dict(row) if row else {
        "mounting_types": [],
        "materials": [],
        "voltages": [],
        "locations": [],
        "sizes": [],
    }
