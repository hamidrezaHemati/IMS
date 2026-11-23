"""Category hierarchy service."""

import psycopg2
from ims.db import AppError, get_db, translate_pg_error
from ims.item_specs import get_spec_definition, resolve_spec_type
from ims.utils import clean_text, parse_optional_int


_CATEGORY_TREE_SQL = """
WITH RECURSIVE cat_tree AS (
    SELECT
        c.id,
        c.parent_id,
        c.name,
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


def create_category(data: dict) -> dict:
    """Create a category or subcategory."""
    name = clean_text(data.get("name"), max_len=100)
    if not name:
        raise AppError("Category name is required.")

    parent_id = parse_optional_int(data.get("parent_id"), "parent_id")
    description = clean_text(data.get("description"))

    db = get_db()
    try:
        with db.transaction() as cur:
            _ensure_parent_exists(cur, parent_id)
            _check_duplicate_sibling(cur, name, parent_id)
            cur.execute(
                """
                INSERT INTO category (parent_id, name, description)
                VALUES (%s, %s, %s)
                RETURNING id;
                """,
                (parent_id, name, description),
            )
            cat_id = cur.fetchone()["id"]
    except psycopg2.Error as exc:
        raise translate_pg_error(exc) from exc

    return get_category_by_id(cat_id)


def update_category(category_id: int, data: dict) -> dict:
    """Update a category's name, parent, or description.

    Cycle detection is enforced by PostgreSQL trigger trg_validate_category_hierarchy.
    """
    name = clean_text(data.get("name"), max_len=100)
    if not name:
        raise AppError("Category name is required.")

    parent_id = parse_optional_int(data.get("parent_id"), "parent_id")
    description = clean_text(data.get("description"))

    db = get_db()
    try:
        with db.transaction() as cur:
            cur.execute("SELECT id FROM category WHERE id = %s;", (category_id,))
            if not cur.fetchone():
                raise AppError("Category not found.", status_code=404)

            _ensure_parent_exists(cur, parent_id)
            _check_duplicate_sibling(cur, name, parent_id, exclude_id=category_id)
            cur.execute(
                """
                UPDATE category
                   SET parent_id = %s,
                       name = %s,
                       description = %s
                 WHERE id = %s;
                """,
                (parent_id, name, description, category_id),
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
) -> tuple[int, bool, bool]:
    """Find or create a (category, optional sub_category) pair inside an open cursor.

    Returns (resolved_category_id, created_parent, created_child).
    """
    clean_parent = clean_text(category_name, max_len=100)
    if not clean_parent:
        raise AppError("Main category name is required.")

    created_parent = False
    created_child = False

    cur.execute(
        """
        SELECT id
          FROM category
         WHERE parent_id IS NULL
           AND LOWER(TRIM(name)) = LOWER(TRIM(%s))
         ORDER BY id
         LIMIT 1;
        """,
        (clean_parent,),
    )
    row = cur.fetchone()
    if row:
        parent_id = row["id"]
    else:
        cur.execute(
            """
            INSERT INTO category (parent_id, name)
            VALUES (NULL, %s)
            RETURNING id;
            """,
            (clean_parent,),
        )
        parent_id = cur.fetchone()["id"]
        created_parent = True

    clean_sub = clean_text(sub_category_name, max_len=100)
    if not clean_sub:
        return parent_id, created_parent, created_child

    cur.execute(
        """
        SELECT id
          FROM category
         WHERE parent_id = %s
           AND LOWER(TRIM(name)) = LOWER(TRIM(%s))
         ORDER BY id
         LIMIT 1;
        """,
        (parent_id, clean_sub),
    )
    sub_row = cur.fetchone()
    if sub_row:
        return sub_row["id"], created_parent, created_child

    cur.execute(
        """
        INSERT INTO category (parent_id, name)
        VALUES (%s, %s)
        RETURNING id;
        """,
        (parent_id, clean_sub),
    )
    sub_id = cur.fetchone()["id"]
    created_child = True
    return sub_id, created_parent, created_child


def resolve_category_for_spec_type(
    cur,
    spec_type: str,
    category_name: str | None = None,
    sub_category_name: str | None = None,
) -> tuple[int, bool, bool]:
    """Resolve and validate a leaf category ID strictly compatible with spec_type."""
    defn = get_spec_definition(spec_type)
    clean_cat = clean_text(category_name, max_len=100)
    clean_sub = clean_text(sub_category_name, max_len=100)

    if spec_type == "electronic_item":
        if clean_cat and clean_cat.strip().lower() in ("electronics", "electronic"):
            clean_cat = "Electronic"

        if clean_sub:
            if clean_cat and clean_cat.strip().lower() != "electronic":
                raise AppError(
                    f"Electronic import requires root category 'Electronic' (found '{clean_cat}')."
                )
            resolved_sub = clean_sub
        elif clean_cat and clean_cat.strip().lower() != "electronic":
            if resolve_spec_type("Mechanical", clean_cat, is_leaf=True) is not None or clean_cat.strip().lower() == "mechanical":
                raise AppError(
                    f"Category '{clean_cat}' belongs to Mechanical components and cannot be imported as Electronic Items."
                )
            resolved_sub = clean_cat
        else:
            raise AppError(
                "Electronic items require a sub_category (e.g. Resistor, Capacitor, Microcontroller)."
            )

        return resolve_or_create_category_pair(cur, "Electronic", resolved_sub)

    expected_leaf = defn["default_subcategory"]
    if clean_cat:
        cat_key = clean_cat.strip().lower()
        if cat_key == "electronic" or cat_key == "electronics":
            raise AppError(
                f"Category '{clean_cat}' belongs to Electronic components and cannot be imported as {defn['label_en']}."
            )
        if cat_key != "mechanical" and resolve_spec_type("Mechanical", clean_cat, is_leaf=True) != spec_type:
            raise AppError(
                f"Category '{clean_cat}' is incompatible with {defn['label_en']} import (expected Mechanical)."
            )

    if clean_sub:
        if resolve_spec_type("Mechanical", clean_sub, is_leaf=True) != spec_type:
            raise AppError(
                f"Subcategory '{clean_sub}' is incompatible with {defn['label_en']} import (expected '{expected_leaf}')."
            )

    return resolve_or_create_category_pair(cur, "Mechanical", expected_leaf)
