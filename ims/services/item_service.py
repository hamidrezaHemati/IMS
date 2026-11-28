"""Items, category-specific specifications, filtering, and CRUD service."""

import math
import psycopg2
from ims.db import AppError, get_db, translate_pg_error
from ims.item_specs import (
    SPEC_DEFINITIONS,
    build_display_name,
    build_spec_summary,
    get_spec_definition,
    resolve_spec_type,
    validate_specs,
)
from ims.jalali import format_jalali_datetime
from ims.utils import (
    clean_text,
    normalize_mounting_type,
    normalize_persian_text,
    parse_bool_param,
    parse_nonnegative_int,
    parse_optional_int,
    parse_optional_mm,
    parse_optional_price,
)


CAT_INFO_CTE = """
WITH RECURSIVE cat_info AS (
    SELECT
        c.id,
        c.parent_id,
        c.name AS leaf_name,
        c.spec_type AS category_spec_type,
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
        c.spec_type AS category_spec_type,
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

ITEM_SPECS_JOIN_SQL = """
LEFT JOIN electronic_item ei ON ei.item_id = i.id
LEFT JOIN spacer sp ON sp.item_id = i.id
LEFT JOIN screw sc ON sc.item_id = i.id
LEFT JOIN nut nu ON nu.item_id = i.id
LEFT JOIN washer wa ON wa.item_id = i.id
LEFT JOIN o_ring ori ON ori.item_id = i.id
"""

ITEM_SPECS_SELECT_SQL = """
    ei.item_id AS ei_present,
    ei.model AS ei_model,
    ei.package_size AS ei_package_size,
    ei.mounting_type AS ei_mounting_type,
    ei.voltage AS ei_voltage,
    ei.material AS ei_material,
    sp.item_id AS sp_present,
    sp.diameter AS sp_diameter,
    sp.length AS sp_length,
    sp.material AS sp_material,
    sp.spacer_type AS sp_spacer_type,
    sc.item_id AS sc_present,
    sc.diameter AS sc_diameter,
    sc.length AS sc_length,
    sc.material AS sc_material,
    sc.head_type AS sc_head_type,
    sc.drive_type AS sc_drive_type,
    nu.item_id AS nu_present,
    nu.diameter AS nu_diameter,
    nu.material AS nu_material,
    wa.item_id AS wa_present,
    wa.diameter AS wa_diameter,
    wa.washer_type AS wa_washer_type,
    wa.material AS wa_material,
    ori.item_id AS ori_present,
    ori.inner_diameter AS ori_inner_diameter,
    ori.outer_diameter AS ori_outer_diameter,
    ori.cross_section AS ori_cross_section,
    ori.material AS ori_material
"""

ITEM_TYPE_CASE_SQL = """
CASE
    WHEN ei.item_id IS NOT NULL THEN 'electronic_item'
    WHEN sp.item_id IS NOT NULL THEN 'spacer'
    WHEN sc.item_id IS NOT NULL THEN 'screw'
    WHEN nu.item_id IS NOT NULL THEN 'nut'
    WHEN wa.item_id IS NOT NULL THEN 'washer'
    WHEN ori.item_id IS NOT NULL THEN 'o_ring'
    ELSE NULL
END
"""

_SPEC_PREFIX_AND_FIELDS = {
    "electronic_item": ("ei_", ("model", "package_size", "mounting_type", "voltage", "material")),
    "spacer": ("sp_", ("diameter", "length", "material", "spacer_type")),
    "screw": ("sc_", ("diameter", "length", "material", "head_type", "drive_type")),
    "nut": ("nu_", ("diameter", "material")),
    "washer": ("wa_", ("diameter", "washer_type", "material")),
    "o_ring": ("ori_", ("inner_diameter", "outer_diameter", "cross_section", "material")),
}

_SPEC_WRITE_COLUMNS = {
    "electronic_item": ("model", "package_size", "mounting_type", "voltage", "material"),
    "spacer": ("diameter", "length", "material", "spacer_type"),
    "screw": ("diameter", "length", "material", "head_type", "drive_type"),
    "nut": ("diameter", "material"),
    "washer": ("diameter", "washer_type", "material"),
    "o_ring": ("inner_diameter", "outer_diameter", "material"),
}

_RAW_SPEC_COLS = tuple(
    f"{prefix}{key}"
    for prefix, keys in (
        ("ei_", ("present", "model", "package_size", "mounting_type", "voltage", "material")),
        ("sp_", ("present", "diameter", "length", "material", "spacer_type")),
        ("sc_", ("present", "diameter", "length", "material", "head_type", "drive_type")),
        ("nu_", ("present", "diameter", "material")),
        ("wa_", ("present", "diameter", "washer_type", "material")),
        ("ori_", ("present", "inner_diameter", "outer_diameter", "cross_section", "material")),
    )
    for key in keys
)

_SORT_EXPRESSIONS = {
    "item_code": "LOWER(i.item_code)",
    "model": "LOWER(COALESCE(ei.model, ''))",
    "category": "LOWER(ci.category_path)",
    "location": "LOWER(i.location)",
    "quantity": "inv.quantity",
    "weighted_avg_cost": "inv.weighted_avg_cost",
    "last_purchase_cost": "inv.last_purchase_cost",
    "created_at": "i.created_at",
    "updated_at": "inv.updated_at",
}

_ALL_MATERIAL_ENUMS = {
    "STAINLESS_STEEL": "STAINLESS_STEEL",
    "STAINLESS STEEL": "STAINLESS_STEEL",
    "PLASTIC": "PLASTIC",
    "BLACK": "BLACK",
    "WHITE": "WHITE",
    "IRON": "IRON",
    "PAPER": "PAPER",
    "NBR": "NBR",
    "VITON": "VITON",
    "SILICONE": "SILICONE",
}


def hydrate_spec_fields(row: dict) -> dict:
    """Attach unified item_type, specs, display_name, and spec_summary onto a SQL row."""
    item_type = None
    for candidate, (prefix, _) in _SPEC_PREFIX_AND_FIELDS.items():
        if row.get(f"{prefix}present") is not None:
            item_type = candidate
            break

    if item_type is None:
        item_type = resolve_spec_type(
            row.get("category_name"),
            row.get("subcategory_name"),
            is_leaf=row.get("subcategory_name") is not None,
            explicit_spec_type=row.get("category_spec_type"),
        )
    row.pop("category_spec_type", None)

    specs: dict = {}
    if item_type and item_type in _SPEC_PREFIX_AND_FIELDS:
        prefix, keys = _SPEC_PREFIX_AND_FIELDS[item_type]
        for key in keys:
            specs[key] = row.get(f"{prefix}{key}")

    for raw_col in _RAW_SPEC_COLS:
        row.pop(raw_col, None)

    defn = SPEC_DEFINITIONS.get(item_type) if item_type else None
    row["item_type"] = item_type
    row["item_type_label_fa"] = defn["label_fa"] if defn else "نامشخص"
    row["item_type_label_en"] = defn["label_en"] if defn else "Unknown"
    row["specs"] = specs
    row["spec_summary"] = build_spec_summary(item_type, specs)
    row["display_name"] = build_display_name(
        item_type,
        specs,
        row.get("subcategory_name"),
        row.get("item_code", ""),
    )
    return row


def _trim_num_sql(expr: str) -> str:
    return f"COALESCE(TRIM(TRAILING '.' FROM TRIM(TRAILING '0' FROM {expr}::TEXT)), '')"


def _add_mm_range_clauses(
    clauses: list[str],
    params: list,
    expr: str,
    filters: dict,
    field: str,
    label: str,
) -> None:
    exact_val = parse_optional_mm(filters.get(field), label)
    if exact_val is not None:
        clauses.append(f"{expr} = %s")
        params.append(exact_val)

    min_val = parse_optional_mm(filters.get(f"min_{field}"), f"min_{label}", require_positive=False)
    if min_val is not None:
        clauses.append(f"{expr} >= %s")
        params.append(min_val)

    max_val = parse_optional_mm(filters.get(f"max_{field}"), f"max_{label}", require_positive=False)
    if max_val is not None:
        clauses.append(f"{expr} <= %s")
        params.append(max_val)


def build_inventory_filter_sql(filters: dict) -> tuple[str, list]:
    """Build parameterized WHERE conditions shared by item search and Excel export."""
    clauses: list[str] = []
    params: list = []

    search = clean_text(filters.get("search"))
    if search:
        norm_search = normalize_persian_text(search) or search
        like = f"%{norm_search}%"
        search_exprs = [
            "i.item_code ILIKE %s",
            "i.location ILIKE %s",
            "COALESCE(i.description, '') ILIKE %s",
            "ci.category_name ILIKE %s",
            "COALESCE(ci.subcategory_name, '') ILIKE %s",
            "COALESCE(ei.model, '') ILIKE %s",
            "COALESCE(ei.package_size, '') ILIKE %s",
            "COALESCE(ei.mounting_type, '') ILIKE %s",
            "COALESCE(ei.voltage, '') ILIKE %s",
            "COALESCE(ei.material, '') ILIKE %s",
            "COALESCE(sp.material, '') ILIKE %s",
            "COALESCE(sp.spacer_type, '') ILIKE %s",
            "COALESCE(sc.material, '') ILIKE %s",
            "COALESCE(sc.head_type, '') ILIKE %s",
            "COALESCE(sc.drive_type, '') ILIKE %s",
            "COALESCE(nu.material, '') ILIKE %s",
            "COALESCE(wa.washer_type, '') ILIKE %s",
            "COALESCE(wa.material, '') ILIKE %s",
            "COALESCE(ori.material, '') ILIKE %s",
            f"{_trim_num_sql('sp.diameter')} ILIKE %s",
            f"{_trim_num_sql('sp.length')} ILIKE %s",
            f"{_trim_num_sql('sc.diameter')} ILIKE %s",
            f"{_trim_num_sql('sc.length')} ILIKE %s",
            f"{_trim_num_sql('nu.diameter')} ILIKE %s",
            f"{_trim_num_sql('wa.diameter')} ILIKE %s",
            f"{_trim_num_sql('ori.inner_diameter')} ILIKE %s",
            f"{_trim_num_sql('ori.outer_diameter')} ILIKE %s",
            f"{_trim_num_sql('ori.cross_section')} ILIKE %s",
        ]
        clauses.append("(" + " OR ".join(search_exprs) + ")")
        params.extend([like] * len(search_exprs))

    for key, expr in (
        ("item_code", "i.item_code"),
        ("location", "i.location"),
        ("description", "COALESCE(i.description, '')"),
        ("model", "COALESCE(ei.model, '')"),
        ("voltage", "COALESCE(ei.voltage, '')"),
        ("electronic_material", "COALESCE(ei.material, '')"),
    ):
        val = clean_text(filters.get(key))
        if val:
            clauses.append(f"{expr} ILIKE %s")
            params.append(f"%{val}%")

    pkg_val = clean_text(filters.get("package_size")) or clean_text(filters.get("size"))
    if pkg_val:
        clauses.append("COALESCE(ei.package_size, '') ILIKE %s")
        params.append(f"%{pkg_val}%")

    mounting_raw = clean_text(filters.get("mounting_type"))
    if mounting_raw:
        clauses.append("ei.mounting_type = %s")
        params.append(normalize_mounting_type(mounting_raw))

    item_type_raw = clean_text(filters.get("item_type"))
    if item_type_raw:
        get_spec_definition(item_type_raw)
        clauses.append(f"({ITEM_TYPE_CASE_SQL}) = %s")
        params.append(item_type_raw)

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

    # Mechanical dimension numeric exact & range filters (mm)
    _add_mm_range_clauses(
        clauses, params,
        "COALESCE(sp.diameter, sc.diameter, nu.diameter, wa.diameter)",
        filters, "diameter", "diameter",
    )
    _add_mm_range_clauses(
        clauses, params,
        "COALESCE(sp.length, sc.length)",
        filters, "length", "length",
    )
    _add_mm_range_clauses(
        clauses, params,
        "ori.inner_diameter",
        filters, "inner_diameter", "inner_diameter",
    )
    _add_mm_range_clauses(
        clauses, params,
        "ori.outer_diameter",
        filters, "outer_diameter", "outer_diameter",
    )
    _add_mm_range_clauses(
        clauses, params,
        "ori.cross_section",
        filters, "cross_section", "cross_section",
    )

    # Mechanical enum filters
    spacer_type_raw = clean_text(filters.get("spacer_type"))
    if spacer_type_raw:
        clauses.append("sp.spacer_type = %s")
        params.append(spacer_type_raw.upper())

    head_type_raw = normalize_persian_text(clean_text(filters.get("head_type")))
    if head_type_raw:
        clauses.append("sc.head_type = %s")
        params.append(head_type_raw)

    drive_type_raw = normalize_persian_text(clean_text(filters.get("drive_type")))
    if drive_type_raw:
        clauses.append("sc.drive_type = %s")
        params.append(drive_type_raw)

    washer_type_raw = clean_text(filters.get("washer_type"))
    if washer_type_raw:
        clauses.append("wa.washer_type = %s")
        params.append(washer_type_raw.upper())

    material_raw = clean_text(filters.get("material"))
    if material_raw:
        mat_enum = _ALL_MATERIAL_ENUMS.get(material_raw.upper())
        if item_type_raw == "electronic_item":
            clauses.append("COALESCE(ei.material, '') ILIKE %s")
            params.append(f"%{material_raw}%")
        elif item_type_raw in ("spacer", "screw", "nut", "washer", "o_ring"):
            tbl_alias = {"spacer": "sp", "screw": "sc", "nut": "nu", "washer": "wa", "o_ring": "ori"}[item_type_raw]
            clauses.append(f"{tbl_alias}.material = %s")
            params.append(mat_enum or material_raw.upper())
        else:
            mech_val = mat_enum or material_raw.upper()
            clauses.append(
                "(COALESCE(ei.material, '') ILIKE %s OR sp.material = %s OR sc.material = %s OR nu.material = %s OR wa.material = %s OR ori.material = %s)"
            )
            params.extend([f"%{material_raw}%", mech_val, mech_val, mech_val, mech_val, mech_val])

    # Shared inventory stock & cost filters
    min_qty_raw = clean_text(filters.get("min_quantity"))
    if min_qty_raw is not None:
        clauses.append("inv.quantity >= %s")
        params.append(parse_nonnegative_int(min_qty_raw, "min_quantity"))

    max_qty_raw = clean_text(filters.get("max_quantity"))
    if max_qty_raw is not None:
        clauses.append("inv.quantity <= %s")
        params.append(parse_nonnegative_int(max_qty_raw, "max_quantity"))

    if parse_bool_param(filters.get("zero_stock")):
        clauses.append("inv.quantity = 0")

    below_raw = clean_text(filters.get("below_threshold"))
    if below_raw is not None:
        clauses.append("inv.quantity < %s")
        params.append(parse_nonnegative_int(below_raw, "below_threshold"))

    for key, expr in (
        ("min_wac", "inv.weighted_avg_cost >="),
        ("max_wac", "inv.weighted_avg_cost <="),
        ("min_lpc", "inv.last_purchase_cost >="),
        ("max_lpc", "inv.last_purchase_cost <="),
    ):
        val = parse_optional_price(filters.get(key), key)
        if val is not None:
            clauses.append(f"{expr} %s")
            params.append(val)

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return where_sql, params


def _build_order_sql(filters: dict) -> str:
    sort_by = (filters.get("sort_by") or "item_code").strip()
    sort_expr = _SORT_EXPRESSIONS.get(sort_by, _SORT_EXPRESSIONS["item_code"])
    sort_dir = (filters.get("sort_dir") or "asc").strip().lower()
    direction = "DESC" if sort_dir == "desc" else "ASC"
    nulls_clause = (
        "NULLS LAST"
        if sort_by in ("model", "weighted_avg_cost", "last_purchase_cost")
        else ""
    )
    return f"ORDER BY {sort_expr} {direction} {nulls_clause}, i.id ASC"


def list_items(filters: dict, paginate: bool = True) -> dict:
    """Query items joined with all specification tables, inventory, and category path."""
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
              {ITEM_SPECS_JOIN_SQL}
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
                ci.category_spec_type,
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
                END AS total_lpc_value,
                {ITEM_SPECS_SELECT_SQL}
            FROM item i
            JOIN inventory inv ON inv.item_id = i.id
            JOIN cat_info ci ON ci.id = i.category_id
            {ITEM_SPECS_JOIN_SQL}
            {where_sql}
            {order_sql}
            {limit_sql};
        """
        cur.execute(data_sql, tuple(query_params))
        rows = []
        for r in cur.fetchall():
            item_dict = hydrate_spec_fields(dict(r))
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
    """Return full item info, category-specific specs, inventory state, and transactions."""
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
                ci.category_spec_type,
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
                END AS total_lpc_value,
                {ITEM_SPECS_SELECT_SQL}
            FROM item i
            JOIN inventory inv ON inv.item_id = i.id
            JOIN cat_info ci ON ci.id = i.category_id
            {ITEM_SPECS_JOIN_SQL}
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

    result = hydrate_spec_fields(dict(item_row))
    result["created_at_jalali"] = format_jalali_datetime(result.get("created_at"))
    result["inventory_updated_at_jalali"] = format_jalali_datetime(
        result.get("inventory_updated_at")
    )
    result["transactions"] = transactions
    return result


def resolve_category_spec_for_write(cur, category_id: int) -> str:
    """Validate that category_id is an existing leaf category mapped to a spec table."""
    cur.execute(
        f"""
        {CAT_INFO_CTE}
        SELECT
            ci.id,
            ci.root_name,
            ci.leaf_name,
            ci.category_spec_type,
            ci.parent_id,
            EXISTS (SELECT 1 FROM category ch WHERE ch.parent_id = ci.id) AS has_children
          FROM cat_info ci
         WHERE ci.id = %s;
        """,
        (category_id,),
    )
    row = cur.fetchone()
    if not row:
        raise AppError("Selected category does not exist.", status_code=404)

    is_leaf = bool(row["parent_id"] is not None and not row["has_children"])
    spec_type = resolve_spec_type(
        row["root_name"],
        row["leaf_name"],
        is_leaf=is_leaf,
        explicit_spec_type=row["category_spec_type"],
    )
    if not spec_type:
        raise AppError(
            "Items must belong to a valid leaf component category (Electronic or Mechanical subcategory)."
        )
    return spec_type


def upsert_spec_row(cur, spec_type: str, item_id: int, specs: dict) -> None:
    """Insert or update the single matching 1:1 specification row for item_id."""
    cols = _SPEC_WRITE_COLUMNS[spec_type]
    all_cols = ("item_id",) + cols
    placeholders = ", ".join(["%s"] * len(all_cols))
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols)
    values = [item_id] + [specs.get(c) for c in cols]
    cur.execute(
        f"""
        INSERT INTO {spec_type} ({", ".join(all_cols)})
        VALUES ({placeholders})
        ON CONFLICT (item_id) DO UPDATE
           SET {updates};
        """,
        tuple(values),
    )


def delete_spec_row(cur, spec_type: str, item_id: int) -> None:
    """Remove the specification row for item_id from spec_type table."""
    if spec_type in _SPEC_WRITE_COLUMNS:
        cur.execute(f"DELETE FROM {spec_type} WHERE item_id = %s;", (item_id,))


def _extract_raw_specs_from_payload(data: dict) -> dict:
    merged: dict = {}
    nested = data.get("specs")
    if isinstance(nested, dict):
        merged.update(nested)
    spec_keys = {
        "model", "package_size", "size", "mounting_type", "voltage", "material",
        "diameter", "length", "spacer_type", "head_type", "drive_type",
        "washer_type", "inner_diameter", "outer_diameter",
    }
    for key in spec_keys:
        if key in data and key not in merged:
            merged[key] = data[key]
    return merged


def _validate_general_item_fields(data: dict) -> dict:
    item_code = clean_text(data.get("item_code"), max_len=80)
    if not item_code:
        raise AppError("Item code is required.")

    category_id = parse_optional_int(data.get("category_id"), "category_id")
    if category_id is None:
        raise AppError("Category is required.")

    location = clean_text(data.get("location"), max_len=150)
    if not location:
        raise AppError("Storage location is required.")

    return {
        "item_code": item_code,
        "category_id": category_id,
        "location": location,
        "description": clean_text(data.get("description")),
    }


def create_item(data: dict) -> dict:
    """Create a new item record and its matching specification row inside one transaction."""
    general = _validate_general_item_fields(data)
    raw_specs = _extract_raw_specs_from_payload(data)

    db = get_db()
    try:
        with db.transaction() as cur:
            spec_type = resolve_category_spec_for_write(cur, general["category_id"])
            clean_specs = validate_specs(spec_type, raw_specs)

            cur.execute(
                """
                INSERT INTO item (item_code, category_id, location, description)
                VALUES (%s, %s, %s, %s)
                RETURNING id;
                """,
                (
                    general["item_code"],
                    general["category_id"],
                    general["location"],
                    general["description"],
                ),
            )
            item_id = cur.fetchone()["id"]
            upsert_spec_row(cur, spec_type, item_id, clean_specs)
    except psycopg2.Error as exc:
        raise translate_pg_error(exc) from exc

    return get_item_detail(item_id, tx_limit=10)


def update_item(item_id: int, data: dict) -> dict:
    """Update item general info and specifications safely across category changes."""
    general = _validate_general_item_fields(data)
    raw_specs = _extract_raw_specs_from_payload(data)

    db = get_db()
    try:
        with db.transaction() as cur:
            cur.execute(
                """
                SELECT
                    i.id,
                    i.category_id,
                    fn_resolve_category_spec_type(i.category_id) AS old_spec_type
                  FROM item i
                 WHERE i.id = %s
                   FOR UPDATE;
                """,
                (item_id,),
            )
            existing = cur.fetchone()
            if not existing:
                raise AppError("Item not found.", status_code=404)

            old_spec_type = existing["old_spec_type"]
            new_spec_type = resolve_category_spec_for_write(cur, general["category_id"])
            clean_specs = validate_specs(new_spec_type, raw_specs)

            if old_spec_type and old_spec_type != new_spec_type:
                # Delete incompatible spec row BEFORE updating item.category_id
                # so database consistency triggers never observe cross-type state.
                delete_spec_row(cur, old_spec_type, item_id)

            cur.execute(
                """
                UPDATE item
                   SET item_code = %s,
                       category_id = %s,
                       location = %s,
                       description = %s
                 WHERE id = %s;
                """,
                (
                    general["item_code"],
                    general["category_id"],
                    general["location"],
                    general["description"],
                    item_id,
                ),
            )
            upsert_spec_row(cur, new_spec_type, item_id, clean_specs)
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
                    SELECT DISTINCT mounting_type FROM electronic_item
                     WHERE mounting_type IS NOT NULL ORDER BY mounting_type
                ) AS mounting_types,
                ARRAY(
                    SELECT DISTINCT material FROM electronic_item
                     WHERE material IS NOT NULL ORDER BY material
                ) AS electronic_materials,
                ARRAY(
                    SELECT DISTINCT voltage FROM electronic_item
                     WHERE voltage IS NOT NULL ORDER BY voltage
                ) AS voltages,
                ARRAY(
                    SELECT DISTINCT location FROM item
                     WHERE location IS NOT NULL ORDER BY location
                ) AS locations,
                ARRAY(
                    SELECT DISTINCT package_size FROM electronic_item
                     WHERE package_size IS NOT NULL ORDER BY package_size
                ) AS package_sizes;
            """
        )
        row = cur.fetchone()
    return dict(row) if row else {
        "mounting_types": [],
        "electronic_materials": [],
        "voltages": [],
        "locations": [],
        "package_sizes": [],
    }
