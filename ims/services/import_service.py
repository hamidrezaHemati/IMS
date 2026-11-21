"""Initial inventory Excel upload, validation preview, and import execution service."""

from collections import Counter
from decimal import Decimal
from pathlib import Path
from openpyxl import load_workbook
import psycopg2
from ims.db import AppError, get_db, translate_pg_error
from ims.services.category_service import resolve_or_create_category_pair
from ims.utils import (
    clean_text,
    normalize_mounting_type,
    parse_nonnegative_int,
    parse_optional_price,
    resolve_uploaded_xlsx,
)


IMPORT_FIELD_ALIASES = {
    "item_code": ("item_code", "item code", "code", "sku", "part_number", "part number"),
    "category": ("category", "main_category", "main category"),
    "sub_category": ("sub_category", "subcategory", "sub category"),
    "model": ("model", "part", "name", "item_name", "item name"),
    "size": ("size", "package", "footprint"),
    "mounting_type": ("mounting_type", "mounting type", "mounting", "mount"),
    "voltage": ("voltage", "volt", "rated_voltage"),
    "material": ("material",),
    "location": ("location", "drawer", "drawer_number", "bin", "shelf"),
    "quantity": ("quantity", "qty", "stock", "initial_quantity", "opening_qty"),
    "price": ("price", "unit_price", "unit price", "cost", "unit_cost", "unit cost"),
    "description": ("description", "desc", "notes", "note"),
}

ALLOWED_POLICIES = ("skip", "update_metadata")


def _suggest_mapping(headers: list[str]) -> dict[str, str | None]:
    normalized_headers = {h.strip().lower(): h for h in headers}
    mapping: dict[str, str | None] = {}
    for target, aliases in IMPORT_FIELD_ALIASES.items():
        matched = None
        for alias in aliases:
            if alias in normalized_headers:
                matched = normalized_headers[alias]
                break
        mapping[target] = matched
    return mapping


def _read_workbook_sheet(path: Path, sheet_name: str | None = None) -> tuple[list[str], str, list[str], list[dict]]:
    try:
        wb = load_workbook(filename=path, data_only=True, read_only=False)
    except Exception as exc:
        raise AppError(f"Failed to read Excel file: {exc}") from exc

    try:
        sheet_names = list(wb.sheetnames)
        if not sheet_names:
            raise AppError("The uploaded Excel workbook contains no worksheets.")

        selected_sheet = sheet_name if sheet_name and sheet_name in sheet_names else sheet_names[0]
        if sheet_name and sheet_name not in sheet_names:
            raise AppError(f"Worksheet '{sheet_name}' not found in workbook.")

        ws = wb[selected_sheet]
        raw_rows = list(ws.iter_rows(values_only=True))
    finally:
        wb.close()

    if not raw_rows:
        raise AppError("The selected worksheet is empty.")

    header_row = raw_rows[0]
    col_indices: list[tuple[int, str]] = []
    seen_headers: Counter = Counter()
    for idx, cell in enumerate(header_row):
        header_text = clean_text(cell)
        if not header_text:
            continue
        seen_headers[header_text] += 1
        unique_header = header_text if seen_headers[header_text] == 1 else f"{header_text} ({seen_headers[header_text]})"
        col_indices.append((idx, unique_header))

    if not col_indices:
        raise AppError("Row 1 of the worksheet must contain column headers.")

    headers = [h for _, h in col_indices]
    data_rows = []
    for row_idx, row_vals in enumerate(raw_rows[1:], start=2):
        row_dict = {}
        has_any_value = False
        for col_idx, header_name in col_indices:
            val = row_vals[col_idx] if col_idx < len(row_vals) else None
            if clean_text(val) is not None:
                has_any_value = True
            row_dict[header_name] = val
        if has_any_value:
            data_rows.append({"row_number": row_idx, "raw": row_dict})

    return sheet_names, selected_sheet, headers, data_rows


def inspect_import_upload(upload_id: str, upload_dir: str | Path, sheet_name: str | None = None) -> dict:
    """Inspect uploaded Excel headers, sheet names, sample rows, and suggested mapping."""
    path = resolve_uploaded_xlsx(upload_id, upload_dir)
    sheet_names, selected_sheet, headers, data_rows = _read_workbook_sheet(path, sheet_name)
    mapping = _suggest_mapping(headers)

    sample_rows = []
    for entry in data_rows[:5]:
        sample_rows.append({
            "row_number": entry["row_number"],
            "values": {h: clean_text(entry["raw"].get(h)) for h in headers},
        })

    return {
        "upload_id": upload_id,
        "sheet_names": sheet_names,
        "selected_sheet": selected_sheet,
        "headers": headers,
        "suggested_mapping": mapping,
        "total_data_rows": len(data_rows),
        "sample_rows": sample_rows,
    }


def _policy_explanation(policy: str) -> str:
    if policy == "update_metadata":
        return (
            "New items are created and their initial stock is recorded via OPENING transactions "
            "(populating weighted average cost and last purchase cost when price is supplied). "
            "Existing item codes update item specifications ONLY — existing inventory quantities, "
            "costs, and historical OPENING transactions are NEVER overwritten."
        )
    return (
        "Safe default policy: Only new item codes are created and initialized via OPENING transactions "
        "(populating weighted average cost and last purchase cost when price is supplied). "
        "Any item code already present in the database is skipped with zero changes to items, stock, or costs."
    )


def _load_existing_categories_map(cur) -> tuple[dict[str, dict], dict[tuple[int, str], dict]]:
    cur.execute("SELECT id, parent_id, name FROM category;")
    roots: dict[str, dict] = {}
    children: dict[tuple[int, str], dict] = {}
    for row in cur.fetchall():
        key = row["name"].strip().lower()
        if row["parent_id"] is None:
            roots[key] = dict(row)
        else:
            children[(row["parent_id"], key)] = dict(row)
    return roots, children


def _load_existing_items_map(cur, item_codes: list[str]) -> dict[str, dict]:
    if not item_codes:
        return {}
    cur.execute(
        """
        SELECT
            i.id AS item_id,
            i.item_code,
            i.model,
            inv.quantity AS current_quantity,
            EXISTS(
                SELECT 1 FROM inventory_transaction t
                 WHERE t.item_id = i.id AND t.transaction_type = 'OPENING'
            ) AS has_opening_tx,
            (
                SELECT COUNT(*)::INT FROM inventory_transaction t
                 WHERE t.item_id = i.id
            ) AS tx_count
        FROM item i
        JOIN inventory inv ON inv.item_id = i.id
        WHERE i.item_code = ANY(%s);
        """,
        (item_codes,),
    )
    return {row["item_code"]: dict(row) for row in cur.fetchall()}


def preview_import(
    upload_id: str,
    upload_dir: str | Path,
    sheet_name: str | None = None,
    column_mapping: dict | None = None,
    existing_policy: str = "skip",
) -> dict:
    """Validate Excel rows, build category population plan, and return dry-run preview."""
    policy = (existing_policy or "skip").strip()
    if policy not in ALLOWED_POLICIES:
        raise AppError(f"Unsupported existing_policy '{existing_policy}'.")

    path = resolve_uploaded_xlsx(upload_id, upload_dir)
    sheet_names, selected_sheet, headers, data_rows = _read_workbook_sheet(path, sheet_name)
    mapping = column_mapping if isinstance(column_mapping, dict) and column_mapping else _suggest_mapping(headers)

    required_mappings = ("item_code", "category", "model", "location", "quantity")
    missing_mapped_cols = [f for f in required_mappings if not mapping.get(f)]
    if missing_mapped_cols:
        raise AppError(
            f"Required column mapping missing for: {', '.join(missing_mapped_cols)}."
        )

    parsed_rows = []
    code_occurrences: dict[str, list[int]] = {}

    for entry in data_rows:
        row_num = entry["row_number"]
        raw = entry["raw"]
        errors = []
        warnings = []
        missing_category_flag = False

        def get_col(field: str):
            col_name = mapping.get(field)
            return raw.get(col_name) if col_name else None

        try:
            item_code = clean_text(get_col("item_code"), max_len=80)
            if not item_code:
                errors.append("Missing item_code.")
        except AppError as exc:
            item_code = None
            errors.append(f"item_code: {exc.message}")

        try:
            category = clean_text(get_col("category"), max_len=100)
            if not category:
                missing_category_flag = True
                errors.append("Missing category.")
        except AppError as exc:
            category = None
            missing_category_flag = True
            errors.append(f"category: {exc.message}")

        try:
            sub_category = clean_text(get_col("sub_category"), max_len=100)
        except AppError as exc:
            sub_category = None
            errors.append(f"sub_category: {exc.message}")

        try:
            model = clean_text(get_col("model"), max_len=150)
            if not model:
                errors.append("Missing model.")
        except AppError as exc:
            model = None
            errors.append(f"model: {exc.message}")

        try:
            location = clean_text(get_col("location"), max_len=150)
            if not location:
                errors.append("Missing location.")
        except AppError as exc:
            location = None
            errors.append(f"location: {exc.message}")

        try:
            size = clean_text(get_col("size"), max_len=50)
        except AppError as exc:
            size = None
            errors.append(f"size: {exc.message}")

        try:
            mounting_type = normalize_mounting_type(get_col("mounting_type"))
        except AppError as exc:
            mounting_type = clean_text(get_col("mounting_type"))
            errors.append(exc.message)

        try:
            voltage = clean_text(get_col("voltage"), max_len=80)
        except AppError as exc:
            voltage = None
            errors.append(f"voltage: {exc.message}")

        try:
            material = clean_text(get_col("material"), max_len=100)
        except AppError as exc:
            material = None
            errors.append(f"material: {exc.message}")

        try:
            description = clean_text(get_col("description"))
        except AppError as exc:
            description = None
            errors.append(f"description: {exc.message}")

        quantity = None
        try:
            quantity = parse_nonnegative_int(get_col("quantity"), "quantity")
            if quantity == 0:
                warnings.append("Quantity is 0: item will be created with 0 stock and no OPENING transaction.")
        except AppError as exc:
            errors.append(exc.message)

        price = None
        try:
            price = parse_optional_price(get_col("price"), "price")
            if quantity == 0 and price is not None:
                warnings.append("Price will not apply because quantity is 0 (no OPENING transaction created).")
        except AppError as exc:
            errors.append(exc.message)

        if item_code:
            code_occurrences.setdefault(item_code, []).append(row_num)

        parsed_rows.append({
            "row_number": row_num,
            "item_code": item_code,
            "category": category,
            "sub_category": sub_category,
            "model": model,
            "size": size,
            "mounting_type": mounting_type,
            "voltage": voltage,
            "material": material,
            "location": location,
            "quantity": quantity,
            "price": price,
            "description": description,
            "errors": errors,
            "warnings": warnings,
            "_missing_category": missing_category_flag,
        })

    duplicate_codes = {code for code, rows in code_occurrences.items() if len(rows) > 1}
    candidate_codes = [
        r["item_code"]
        for r in parsed_rows
        if r["item_code"] and r["item_code"] not in duplicate_codes and not r["errors"]
    ]

    db = get_db()
    with db.cursor() as cur:
        existing_items = _load_existing_items_map(cur, candidate_codes)
        existing_roots, existing_children = _load_existing_categories_map(cur)

    preview_rows = []
    category_pairs_to_apply: list[tuple[str, str | None]] = []

    valid_new_rows = 0
    existing_rows = 0
    existing_skipped_rows = 0
    existing_updated_rows = 0
    existing_with_opening_count = 0
    duplicate_rows = 0
    invalid_rows = 0
    missing_category_rows = 0
    zero_quantity_new_rows = 0

    for row in parsed_rows:
        code = row["item_code"]
        errors = list(row["errors"])
        warnings = list(row["warnings"])
        existing_info = None

        if code and code in duplicate_codes:
            dup_list = ", ".join(str(n) for n in code_occurrences[code])
            errors.append(f"Duplicate item_code '{code}' appears on Excel rows: {dup_list}.")
            status = "duplicate"
            action = "blocked"
            duplicate_rows += 1
            if row["_missing_category"]:
                missing_category_rows += 1
        elif errors:
            status = "invalid"
            action = "blocked"
            invalid_rows += 1
            if row["_missing_category"]:
                missing_category_rows += 1
        elif code in existing_items:
            existing_info = existing_items[code]
            status = "existing"
            existing_rows += 1
            if existing_info["has_opening_tx"]:
                existing_with_opening_count += 1
            if policy == "update_metadata":
                action = "update_metadata"
                existing_updated_rows += 1
                warnings.append(
                    f"Existing stock ({existing_info['current_quantity']}) and transactions will NOT be altered."
                )
                category_pairs_to_apply.append((row["category"], row["sub_category"]))
            else:
                action = "skip"
                existing_skipped_rows += 1
                warnings.append(
                    f"Already exists (stock: {existing_info['current_quantity']}); row will be skipped."
                )
        else:
            status = "new"
            valid_new_rows += 1
            if row["quantity"] == 0:
                action = "create_zero_stock"
                zero_quantity_new_rows += 1
            else:
                action = "create_and_open"
            category_pairs_to_apply.append((row["category"], row["sub_category"]))

        preview_rows.append({
            "row_number": row["row_number"],
            "item_code": row["item_code"],
            "category": row["category"],
            "sub_category": row["sub_category"],
            "model": row["model"],
            "size": row["size"],
            "mounting_type": row["mounting_type"],
            "voltage": row["voltage"],
            "material": row["material"],
            "location": row["location"],
            "quantity": row["quantity"],
            "price": row["price"],
            "description": row["description"],
            "status": status,
            "action": action,
            "errors": errors,
            "warnings": warnings,
            "existing_stock": existing_info["current_quantity"] if existing_info else None,
            "has_opening_tx": existing_info["has_opening_tx"] if existing_info else False,
        })

    # Compute unique parent & child category resolution plan
    category_plan_map: dict[str, dict] = {}
    categories_to_create = 0
    subcategories_to_create = 0

    for parent_name, child_name in category_pairs_to_apply:
        p_key = parent_name.strip().lower()
        if p_key not in category_plan_map:
            existing_root = existing_roots.get(p_key)
            if not existing_root:
                categories_to_create += 1
            category_plan_map[p_key] = {
                "name": existing_root["name"] if existing_root else parent_name.strip(),
                "status": "existing" if existing_root else "new",
                "existing_id": existing_root["id"] if existing_root else None,
                "subcategories": {},
            }

        if child_name:
            c_key = child_name.strip().lower()
            sub_map = category_plan_map[p_key]["subcategories"]
            if c_key not in sub_map:
                parent_id = category_plan_map[p_key]["existing_id"]
                existing_child = existing_children.get((parent_id, c_key)) if parent_id else None
                if not existing_child:
                    subcategories_to_create += 1
                sub_map[c_key] = {
                    "name": existing_child["name"] if existing_child else child_name.strip(),
                    "status": "existing" if existing_child else "new",
                    "existing_id": existing_child["id"] if existing_child else None,
                }

    category_plan = []
    for parent_entry in sorted(category_plan_map.values(), key=lambda x: x["name"].lower()):
        subs = sorted(parent_entry["subcategories"].values(), key=lambda x: x["name"].lower())
        category_plan.append({
            "name": parent_entry["name"],
            "status": parent_entry["status"],
            "existing_id": parent_entry["existing_id"],
            "subcategories": subs,
        })

    return {
        "upload_id": upload_id,
        "sheet_names": sheet_names,
        "selected_sheet": selected_sheet,
        "column_mapping": mapping,
        "existing_policy": policy,
        "policy_explanation": _policy_explanation(policy),
        "summary": {
            "total_rows": len(preview_rows),
            "valid_new_rows": valid_new_rows,
            "will_import_rows": valid_new_rows + existing_updated_rows,
            "existing_rows": existing_rows,
            "existing_skipped_rows": existing_skipped_rows,
            "existing_updated_rows": existing_updated_rows,
            "existing_with_opening_count": existing_with_opening_count,
            "duplicate_rows": duplicate_rows,
            "duplicate_code_count": len(duplicate_codes),
            "invalid_rows": invalid_rows,
            "missing_category_rows": missing_category_rows,
            "zero_quantity_new_rows": zero_quantity_new_rows,
            "categories_to_create": categories_to_create,
            "subcategories_to_create": subcategories_to_create,
        },
        "category_plan": category_plan,
        "rows": preview_rows,
    }


def confirm_import(
    upload_id: str,
    upload_dir: str | Path,
    user_id: int,
    sheet_name: str | None = None,
    column_mapping: dict | None = None,
    existing_policy: str = "skip",
) -> dict:
    """Populate categories first, then create items and OPENING transactions."""
    preview = preview_import(
        upload_id=upload_id,
        upload_dir=upload_dir,
        sheet_name=sheet_name,
        column_mapping=column_mapping,
        existing_policy=existing_policy,
    )

    rows = preview["rows"]
    policy = preview["existing_policy"]
    applicable_rows = [
        r for r in rows
        if r["status"] == "new" or (r["status"] == "existing" and policy == "update_metadata")
    ]

    db = get_db()
    resolved_category_ids: dict[tuple[str, str], int] = {}
    categories_created = 0
    subcategories_created = 0

    # Step A: Scan category and sub_category columns and populate category table first.
    if applicable_rows:
        try:
            with db.transaction() as cur:
                for row in applicable_rows:
                    cat_key = row["category"].strip().lower()
                    sub_key = (row["sub_category"] or "").strip().lower()
                    pair_key = (cat_key, sub_key)
                    if pair_key in resolved_category_ids:
                        continue
                    cat_id, created_parent, created_child = resolve_or_create_category_pair(
                        cur, row["category"], row["sub_category"]
                    )
                    resolved_category_ids[pair_key] = cat_id
                    if created_parent:
                        categories_created += 1
                    if created_child:
                        subcategories_created += 1
        except psycopg2.Error as exc:
            raise translate_pg_error(exc) from exc

    # Step B: Process items & OPENING transactions independently per row.
    created_count = 0
    updated_count = 0
    skipped_count = 0
    failed_count = 0
    opening_tx_count = 0
    results = []

    for row in rows:
        status = row["status"]
        if status in ("invalid", "duplicate"):
            failed_count += 1
            results.append({
                "row_number": row["row_number"],
                "item_code": row["item_code"],
                "model": row["model"],
                "status": "failed",
                "reason": "; ".join(row["errors"]),
            })
            continue

        if status == "existing" and policy == "skip":
            skipped_count += 1
            results.append({
                "row_number": row["row_number"],
                "item_code": row["item_code"],
                "model": row["model"],
                "status": "skipped",
                "reason": "Existing item skipped per import policy.",
            })
            continue

        cat_key = row["category"].strip().lower()
        sub_key = (row["sub_category"] or "").strip().lower()
        category_id = resolved_category_ids[(cat_key, sub_key)]

        try:
            with db.transaction() as cur:
                if status == "new":
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
                            row["item_code"],
                            category_id,
                            row["model"],
                            row["size"],
                            row["mounting_type"],
                            row["voltage"],
                            row["material"],
                            row["location"],
                            row["description"],
                        ),
                    )
                    item_id = cur.fetchone()["id"]
                    tx_id = None

                    if row["quantity"] > 0:
                        cur.execute(
                            """
                            INSERT INTO inventory_transaction (
                                user_id, item_id, quantity, transaction_type, price, description
                            )
                            VALUES (%s, %s, %s, 'OPENING', %s, %s)
                            RETURNING id;
                            """,
                            (
                                user_id,
                                item_id,
                                row["quantity"],
                                row["price"],
                                "Initial inventory import",
                            ),
                        )
                        tx_id = cur.fetchone()["id"]
                        opening_tx_count += 1

                    created_count += 1
                    results.append({
                        "row_number": row["row_number"],
                        "item_code": row["item_code"],
                        "model": row["model"],
                        "status": "created",
                        "item_id": item_id,
                        "category_id": category_id,
                        "opening_transaction_id": tx_id,
                        "quantity": row["quantity"],
                        "price": row["price"],
                    })

                elif status == "existing" and policy == "update_metadata":
                    cur.execute(
                        """
                        UPDATE item
                           SET category_id = %s,
                               model = %s,
                               size = %s,
                               mounting_type = %s,
                               voltage = %s,
                               material = %s,
                               location = %s,
                               description = %s
                         WHERE item_code = %s
                        RETURNING id;
                        """,
                        (
                            category_id,
                            row["model"],
                            row["size"],
                            row["mounting_type"],
                            row["voltage"],
                            row["material"],
                            row["location"],
                            row["description"],
                            row["item_code"],
                        ),
                    )
                    item_id = cur.fetchone()["id"]
                    updated_count += 1
                    results.append({
                        "row_number": row["row_number"],
                        "item_code": row["item_code"],
                        "model": row["model"],
                        "status": "updated",
                        "item_id": item_id,
                        "category_id": category_id,
                        "reason": "Specifications updated; stock and transactions unchanged.",
                    })
        except (AppError, psycopg2.Error) as exc:
            err = exc if isinstance(exc, AppError) else translate_pg_error(exc)
            failed_count += 1
            results.append({
                "row_number": row["row_number"],
                "item_code": row["item_code"],
                "model": row["model"],
                "status": "failed",
                "reason": err.message,
            })

    # Cleanup temp upload once confirmed
    try:
        resolve_uploaded_xlsx(upload_id, upload_dir).unlink(missing_ok=True)
    except Exception:
        pass

    return {
        "existing_policy": policy,
        "summary": {
            "total_rows": preview["summary"]["total_rows"],
            "imported_items": created_count + updated_count,
            "created_items": created_count,
            "updated_items": updated_count,
            "skipped_items": skipped_count,
            "failed_rows": failed_count,
            "duplicate_rows": preview["summary"]["duplicate_rows"],
            "invalid_or_missing_rows": preview["summary"]["invalid_rows"],
            "missing_category_rows": preview["summary"]["missing_category_rows"],
            "opening_transactions_created": opening_tx_count,
            "categories_created": categories_created,
            "subcategories_created": subcategories_created,
        },
        "results": results,
    }
