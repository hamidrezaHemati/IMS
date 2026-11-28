"""Category hierarchy service."""

import psycopg2
from ims.db import AppError, get_db, translate_pg_error
from ims.item_specs import (
    SPEC_DEFINITIONS,
    get_spec_definition,
    is_electronic_root_name,
    resolve_spec_type,
)
from ims.utils import clean_text, normalize_persian_text, parse_optional_int


def _norm_cat_name(val) -> str | None:
    return normalize_persian_text(clean_text(val, max_len=100))


def _norm_cat_key(val: str | None) -> str:
    return (normalize_persian_text(val) or "").strip().lower()


_CATEGORY_TREE_SQL = """
WITH RECURSIVE cat_tree AS (
    SELECT
        c.id,
        c.parent_id,
        c.name,
        c.spec_type,
        c.description,
        NULL::VARCHAR(100) AS parent_name,
        c.id AS root_id,
        c.name AS root_name,
        0 AS depth,
        c.name::TEXT AS full_path
    FROM category c
    WHERE c.parent_id IS NULL

    UNION ALL

    SELECT
        c.id,
        c.parent_id,
        c.name,
        c.spec_type,
        c.description,
        ct.name AS parent_name,
        ct.root_id,
        ct.root_name,
        ct.depth + 1 AS depth,
        (ct.full_path || ' > ' || c.name) AS full_path
    FROM category c
    JOIN cat_tree ct ON c.parent_id = ct.id
),
cat_closure AS (
    SELECT id AS ancestor_id, id AS descendant_id
      FROM category
    UNION ALL
    SELECT cc.ancestor_id, c.id AS descendant_id
      FROM cat_closure cc
      JOIN category c ON c.parent_id = cc.descendant_id
),
direct_counts AS (
    SELECT category_id, COUNT(*)::INT AS cnt
      FROM item
     GROUP BY category_id
),
subtree_counts AS (
    SELECT cc.ancestor_id AS category_id, COUNT(i.id)::INT AS cnt
      FROM cat_closure cc
      LEFT JOIN item i ON i.category_id = cc.descendant_id
     GROUP BY cc.ancestor_id
),
child_counts AS (
    SELECT parent_id AS category_id, COUNT(*)::INT AS cnt
      FROM category
     WHERE parent_id IS NOT NULL
     GROUP BY parent_id
)
SELECT
    ct.id,
    ct.parent_id,
    ct.name,
    ct.spec_type,
    ct.description,
    ct.parent_name,
    ct.root_id,
    ct.root_name,
    ct.depth,
    ct.full_path,
    COALESCE(dc.cnt, 0) AS direct_item_count,
    COALESCE(sc.cnt, 0) AS subtree_item_count,
    COALESCE(chc.cnt, 0) AS child_count
FROM cat_tree ct
LEFT JOIN direct_counts dc ON dc.category_id = ct.id
LEFT JOIN subtree_counts sc ON sc.category_id = ct.id
LEFT JOIN child_counts chc ON chc.category_id = ct.id
ORDER BY LOWER(ct.full_path), ct.id;
"""


def list_categories() -> list[dict]:
    """Return all categories enriched with hierarchy metadata, spec_type, and item counts."""
    db = get_db()
    with db.cursor() as cur:
        cur.execute(_CATEGORY_TREE_SQL)
        rows = []
        for raw in cur.fetchall():
            row = dict(raw)
            is_leaf = bool(row["parent_id"] is not None and row["child_count"] == 0)
            row["is_leaf"] = is_leaf
            row["spec_type"] = resolve_spec_type(
                row.get("root_name"),
                row.get("name"),
                is_leaf=is_leaf,
                explicit_spec_type=row.get("spec_type"),
            )
            rows.append(row)
        return rows


def get_category_tree() -> list[dict]:
    """Return categories nested as a tree alongside flat list metadata."""
    flat = list_categories()
    nodes = {}
    roots = []
    for row in flat:
        node = dict(row)
        node["children"] = []
        nodes[node["id"]] = node

    for row in flat:
        node = nodes[row["id"]]
        pid = node["parent_id"]
        if pid is not None and pid in nodes:
            nodes[pid]["children"].append(node)
        else:
            roots.append(node)
    return roots


def get_category_by_id(category_id: int) -> dict | None:
    """Fetch a single category by ID."""
    for cat in list_categories():
        if cat["id"] == category_id:
            return cat
    return None


def _ensure_parent_exists(cur, parent_id: int | None) -> None:
    if parent_id is None:
        return
    cur.execute("SELECT id FROM category WHERE id = %s;", (parent_id,))
    if not cur.fetchone():
        raise AppError("Selected parent category does not exist.", status_code=404)
    cur.execute("SELECT 1 FROM item WHERE category_id = %s LIMIT 1;", (parent_id,))
    if cur.fetchone():
        raise AppError(
            "Cannot add a subcategory under a category that already has items assigned.",
            status_code=409,
        )


def _check_duplicate_sibling(cur, name: str, parent_id: int | None, exclude_id: int | None = None) -> None:
    if parent_id is None:
        sql = """
            SELECT id FROM category
             WHERE parent_id IS NULL
               AND LOWER(TRIM(name)) = LOWER(TRIM(%s))
        """
        params = [name]
    else:
        sql = """
            SELECT id FROM category
             WHERE parent_id = %s
               AND LOWER(TRIM(name)) = LOWER(TRIM(%s))
        """
        params = [parent_id, name]

    if exclude_id is not None:
        sql += " AND id <> %s"
        params.append(exclude_id)

    cur.execute(sql + ";", tuple(params))
    if cur.fetchone():
        raise AppError(
            f"A category named '{name}' already exists under the selected parent.",
            status_code=409,
            code="duplicate_category",
        )


def _resolve_root_name_for_parent(cur, parent_id: int) -> str | None:
    cur.execute(
        """
        WITH RECURSIVE anc AS (
            SELECT id, parent_id, name
              FROM category
             WHERE id = %s
            UNION ALL
            SELECT p.id, p.parent_id, p.name
              FROM category p
              JOIN anc a ON a.parent_id = p.id
        )
        SELECT name
          FROM anc
         WHERE parent_id IS NULL
         LIMIT 1;
        """,
        (parent_id,),
    )
    row = cur.fetchone()
    return row["name"] if row else None


def _resolve_category_spec_input(
    cur,
    parent_id: int | None,
    name: str,
    raw_spec_type,
) -> str | None:
    if parent_id is None:
        return None
    cleaned = clean_text(raw_spec_type, max_len=30)
    if cleaned:
        get_spec_definition(cleaned)
        return cleaned
    root_name = _resolve_root_name_for_parent(cur, parent_id)
    return resolve_spec_type(root_name, name, is_leaf=True)


def create_category(data: dict) -> dict:
    """Create a category or subcategory."""
    name = _norm_cat_name(data.get("name"))
    if not name:
        raise AppError("Category name is required.")

    parent_id = parse_optional_int(data.get("parent_id"), "parent_id")
    description = clean_text(data.get("description"))

    db = get_db()
    try:
        with db.transaction() as cur:
            _ensure_parent_exists(cur, parent_id)
            _check_duplicate_sibling(cur, name, parent_id)
            spec_type = _resolve_category_spec_input(cur, parent_id, name, data.get("spec_type"))
            cur.execute(
                """
                INSERT INTO category (parent_id, name, spec_type, description)
                VALUES (%s, %s, %s, %s)
                RETURNING id;
                """,
                (parent_id, name, spec_type, description),
            )
            cat_id = cur.fetchone()["id"]
    except psycopg2.Error as exc:
        raise translate_pg_error(exc) from exc

    return get_category_by_id(cat_id)


def update_category(category_id: int, data: dict) -> dict:
    """Update a category's name, parent, spec_type, or description.

    Cycle and populated-category checks are enforced both here and in PostgreSQL triggers.
    """
    name = _norm_cat_name(data.get("name"))
    if not name:
        raise AppError("Category name is required.")

    parent_id = parse_optional_int(data.get("parent_id"), "parent_id")
    description = clean_text(data.get("description"))

    db = get_db()
    try:
        with db.transaction() as cur:
            cur.execute(
                "SELECT id, parent_id, spec_type FROM category WHERE id = %s FOR UPDATE;",
                (category_id,),
            )
            existing = cur.fetchone()
            if not existing:
                raise AppError("Category not found.", status_code=404)

            _ensure_parent_exists(cur, parent_id)
            _check_duplicate_sibling(cur, name, parent_id, exclude_id=category_id)

            if parent_id is None:
                spec_type = None
            elif "spec_type" in data:
                cleaned_spec = clean_text(data.get("spec_type"), max_len=30)
                if cleaned_spec:
                    get_spec_definition(cleaned_spec)
                    spec_type = cleaned_spec
                else:
                    spec_type = None
            else:
                spec_type = existing["spec_type"] or resolve_spec_type(
                    _resolve_root_name_for_parent(cur, parent_id), name, is_leaf=True
                )

            if spec_type != existing["spec_type"]:
                cur.execute("SELECT 1 FROM item WHERE category_id = %s LIMIT 1;", (category_id,))
                if cur.fetchone():
                    raise AppError(
                        "Cannot change spec_type of a category that already contains items.",
                        status_code=409,
                    )

            cur.execute(
                """
                UPDATE category
                   SET parent_id = %s,
                       name = %s,
                       spec_type = %s,
                       description = %s
                 WHERE id = %s;
                """,
                (parent_id, name, spec_type, description, category_id),
            )
    except psycopg2.Error as exc:
        raise translate_pg_error(exc) from exc

    return get_category_by_id(category_id)


def delete_category(category_id: int) -> None:
    """Delete a category if not referenced by subcategories or items."""
    db = get_db()
    try:
        with db.transaction() as cur:
            cur.execute("DELETE FROM category WHERE id = %s RETURNING id;", (category_id,))
            if not cur.fetchone():
                raise AppError("Category not found.", status_code=404)
    except psycopg2.Error as exc:
        raise translate_pg_error(exc) from exc


def resolve_or_create_category_pair(
    cur,
    category_name: str,
    sub_category_name: str | None = None,
    spec_type: str | None = None,
) -> tuple[int, bool, bool]:
    """Find or create a (category, optional sub_category) pair inside an open cursor.

    Returns (resolved_category_id, created_parent, created_child).
    """
    clean_parent = _norm_cat_name(category_name)
    if not clean_parent:
        raise AppError("Main category name is required.")

    if spec_type is not None:
        get_spec_definition(spec_type)

    created_parent = False
    created_child = False

    cur.execute(
        """
        SELECT id, name
          FROM category
         WHERE parent_id IS NULL
           AND REPLACE(REPLACE(LOWER(TRIM(name)), 'ي', 'ی'), 'ك', 'ک') = LOWER(TRIM(%s))
         ORDER BY id
         LIMIT 1;
        """,
        (clean_parent,),
    )
    row = cur.fetchone()
    if row:
        parent_id = row["id"]
        parent_actual_name = row["name"]
    else:
        cur.execute(
            """
            INSERT INTO category (parent_id, name, spec_type)
            VALUES (NULL, %s, NULL)
            RETURNING id;
            """,
            (clean_parent,),
        )
        parent_id = cur.fetchone()["id"]
        parent_actual_name = clean_parent
        created_parent = True

    clean_sub = _norm_cat_name(sub_category_name)
    if not clean_sub:
        return parent_id, created_parent, created_child

    cur.execute(
        """
        SELECT id, name, spec_type
          FROM category
         WHERE parent_id = %s
           AND REPLACE(REPLACE(LOWER(TRIM(name)), 'ي', 'ی'), 'ك', 'ک') = LOWER(TRIM(%s))
         ORDER BY id
         LIMIT 1;
        """,
        (parent_id, clean_sub),
    )
    sub_row = cur.fetchone()
    if sub_row:
        sub_id = sub_row["id"]
        cur.execute("SELECT 1 FROM category WHERE parent_id = %s LIMIT 1;", (sub_id,))
        if cur.fetchone():
            raise AppError(
                f"Subcategory '{clean_sub}' under '{parent_actual_name}' has child categories and cannot directly hold items.",
                status_code=409,
            )

        effective_spec = sub_row["spec_type"] or resolve_spec_type(
            parent_actual_name, sub_row["name"], is_leaf=True
        )
        if spec_type is not None and effective_spec is not None and effective_spec != spec_type:
            raise AppError(
                f"Subcategory '{clean_sub}' under '{parent_actual_name}' is already assigned to '{effective_spec}' and cannot be used for '{spec_type}'.",
                status_code=409,
            )
        if sub_row["spec_type"] is None and spec_type is not None:
            cur.execute("UPDATE category SET spec_type = %s WHERE id = %s;", (spec_type, sub_id))

        return sub_id, created_parent, created_child

    cur.execute(
        """
        INSERT INTO category (parent_id, name, spec_type)
        VALUES (%s, %s, %s)
        RETURNING id;
        """,
        (parent_id, clean_sub, spec_type),
    )
    sub_id = cur.fetchone()["id"]
    created_child = True
    return sub_id, created_parent, created_child


def resolve_category_plan_names(
    spec_type: str,
    category_name: str | None = None,
    sub_category_name: str | None = None,
) -> tuple[str, str]:
    """Resolve user-provided (category, sub_category) names in any language for spec_type."""
    defn = get_spec_definition(spec_type)
    clean_cat = _norm_cat_name(category_name)
    clean_sub = _norm_cat_name(sub_category_name)

    if clean_cat and clean_sub:
        return clean_cat, clean_sub

    if clean_cat:
        if spec_type == "electronic_item":
            if is_electronic_root_name(clean_cat):
                raise AppError(
                    "Missing sub_category: electronic items require a subcategory (e.g. Resistor, Capacitor, مقاومت)."
                )
            return defn["root_category"], clean_cat
        return clean_cat, defn["default_subcategory"]

    if clean_sub:
        return defn["root_category"], clean_sub

    if spec_type == "electronic_item":
        raise AppError(
            "Missing category/sub_category: electronic items require a subcategory (e.g. Resistor, Capacitor, مقاومت)."
        )
    return defn["root_category"], defn["default_subcategory"]


def resolve_category_for_spec_type(
    cur,
    spec_type: str,
    category_name: str | None = None,
    sub_category_name: str | None = None,
) -> tuple[int, bool, bool]:
    """Resolve or create a leaf category ID labeled as written and bound to spec_type."""
    resolved_cat, resolved_sub = resolve_category_plan_names(
        spec_type,
        category_name,
        sub_category_name,
    )
    return resolve_or_create_category_pair(
        cur,
        resolved_cat,
        resolved_sub,
        spec_type=spec_type,
    )
