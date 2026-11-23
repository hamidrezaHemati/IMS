"""Type-aware Excel initial inventory upload, template generation, validation, and import."""

from collections import Counter
from io import BytesIO
from pathlib import Path
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
import psycopg2
from ims.db import AppError, get_db, translate_pg_error
from ims.item_specs import (
    SPEC_DEFINITIONS,
    build_spec_summary,
    compute_o_ring_cross_section,
    get_spec_definition,
    resolve_spec_type,
    validate_specs,
)
from ims.services.category_service import resolve_category_for_spec_type
from ims.services.item_service import upsert_spec_row
from ims.utils import (
    clean_text,
    parse_nonnegative_int,
    parse_optional_price,
    resolve_uploaded_xlsx,
)

COMMON_FIELD_ALIASES = {
    "item_code": ("item_code", "item code", "code", "sku", "part_number", "part number"),
    "category": ("category", "main_category", "main category"),
    "sub_category": ("sub_category", "subcategory", "sub category", "type_name", "component_type"),
    "location": ("location", "drawer", "drawer_number", "bin", "shelf"),
    "quantity": ("quantity", "qty", "stock", "initial_quantity", "opening_qty"),
    "price": ("price", "unit_price", "unit price", "cost", "unit_cost", "unit cost"),
    "description": ("description", "desc", "notes", "note"),
}

ALLOWED_POLICIES = ("skip", "update_metadata")


def _build_type_fields_meta(item_type: str) -> list[dict]:
    """Return ordered column-mapping metadata for item_type."""
    defn = get_spec_definition(item_type)
    is_electronic = item_type == "electronic_item"
    fields = [
        {"key": "item_code", "label": "کد قطعه", "required": True, "aliases": COMMON_FIELD_ALIASES["item_code"]},
        {"key": "category", "label": "دسته‌بندی اصلی", "required": False, "aliases": COMMON_FIELD_ALIASES["category"]},
        {"key": "sub_category", "label": "زیردسته", "required": is_electronic, "aliases": COMMON_FIELD_ALIASES["sub_category"]},
    ]
    for f in defn["fields"]:
        if f["kind"] == "computed_mm":
            continue
        label = f["label_fa"]
        if f.get("unit"):
            label = f"{label} ({f['unit']})"
        fields.append({
            "key": f["name"],
            "label": label,
            "required": bool(f.get("required")),
            "aliases": f.get("excel_aliases", (f["name"],)),
        })
    fields.extend([
        {"key": "location", "label": "محل نگهداری / کشو", "required": True, "aliases": COMMON_FIELD_ALIASES["location"]},
        {"key": "quantity", "label": "موجودی اولیه", "required": True, "aliases": COMMON_FIELD_ALIASES["quantity"]},
        {"key": "price", "label": "قیمت واحد (ریال)", "required": False, "aliases": COMMON_FIELD_ALIASES["price"]},
        {"key": "description", "label": "توضیحات", "required": False, "aliases": COMMON_FIELD_ALIASES["description"]},
    ])
    return fields


def _suggest_mapping_for_type(headers: list[str], item_type: str) -> dict[str, str | None]:
    normalized_headers = {h.strip().lower(): h for h in headers}
    mapping: dict[str, str | None] = {}
    for field in _build_type_fields_meta(item_type):
        matched = None
        for alias in field["aliases"]:
            if alias in normalized_headers:
                matched = normalized_headers[alias]
                break
        mapping[field["key"]] = matched
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


def generate_import_template_xlsx(item_type: str) -> bytes:
    """Generate a downloadable .xlsx template workbook with exact columns and field guide."""
    defn = get_spec_definition(item_type)
    fields_meta = _build_type_fields_meta(item_type)

    headers = [f["key"] for f in fields_meta]
    example_values = {
        "electronic_item": {
            "item_code": "RES-1K-0603",
            "category": "Electronic",
            "sub_category": "Resistor",
            "model": "1K 1%",
            "package_size": "0603",
            "mounting_type": "SMD",
            "voltage": "50V",
            "material": "Thick Film",
            "location": "E1-01",
            "quantity": 100,
            "price": 5000,
            "description": "Sample electronic resistor",
        },
        "screw": {
            "item_code": "SCR-4X12-HEX",
            "category": "Mechanical",
            "sub_category": "Screw",
            "diameter": 4,
            "length": 12,
            "material": "STAINLESS_STEEL",
            "head_type": "آلنی",
            "drive_type": "آلنی",
            "location": "M2-01",
            "quantity": 250,
            "price": 12000,
            "description": "Dimensions in mm; do not use M4/M5 strings",
        },
        "nut": {
            "item_code": "NUT-4-SS",
            "category": "Mechanical",
            "sub_category": "Nut",
            "diameter": 4,
            "material": "STAINLESS_STEEL",
            "location": "M2-02",
            "quantity": 300,
            "price": 6000,
            "description": "Diameter in mm",
        },
        "spacer": {
            "item_code": "SPC-3X15-F",
            "category": "Mechanical",
            "sub_category": "Spacer",
            "diameter": 3,
            "length": 15,
            "material": "STAINLESS_STEEL",
            "spacer_type": "F",
            "location": "M1-01",
            "quantity": 80,
            "price": 25000,
            "description": "F = male-female, H = female-female",
        },
        "washer": {
            "item_code": "WSH-5-PLAIN",
            "category": "Mechanical",
            "sub_category": "Washer",
            "diameter": 5,
            "washer_type": "PLAIN",
            "material": "IRON",
            "location": "M3-01",
            "quantity": 500,
            "price": 3000,
            "description": "PLAIN or SPRING",
        },
        "o_ring": {
            "item_code": "OR-54X60-VIT",
            "category": "Mechanical",
            "sub_category": "O-Ring",
            "inner_diameter": 54,
            "outer_diameter": 60,
            "material": "VITON",
            "location": "M4-01",
            "quantity": 40,
            "price": 90000,
            "description": "cross_section = (outer - inner)/2 is calculated automatically",
        },
    }[item_type]

    wb = Workbook()
    ws = wb.active
    ws.title = defn["sheet_name"]
    ws.append(headers)

    header_fill = PatternFill("solid", fgColor="1E293B")
    header_font = Font(color="FFFFFF", bold=True)
    for col_idx in range(1, len(headers) + 1):
        c = ws.cell(row=1, column=col_idx)
        c.fill = header_fill
        c.font = header_font
        c.alignment = Alignment(horizontal="left", vertical="center")

    ws.append([example_values.get(h, "") for h in headers])
    ws.freeze_panes = "A2"

    for col in ws.columns:
        max_len = max((len(str(cell.value or "")) for cell in col), default=10)
        ws.column_dimensions[col[0].column_letter].width = min(max(max_len + 4, 14), 38)

    ws_guide = wb.create_sheet("Field Guide")
    ws_guide.append(["Column", "Required", "Rule / Allowed Values"])
    for col_idx in range(1, 4):
        c = ws_guide.cell(row=1, column=col_idx)
        c.fill = header_fill
        c.font = header_font

    spec_by_name = {f["name"]: f for f in defn["fields"]}
    for f in fields_meta:
        k = f["key"]
        req_str = "Yes" if f["required"] else "No"
        if k in spec_by_name and spec_by_name[k].get("options"):
            opts = ", ".join(o["value"] for o in spec_by_name[k]["options"])
            rule = f"Allowed values: {opts}"
        elif k in spec_by_name and spec_by_name[k]["kind"] == "mm":
            rule = "Positive number in millimeters (mm); do not enter M5/M6 strings."
        elif k == "price":
            rule = "Optional unit cost in Iranian Rial (IRR)"
        elif k == "sub_category":
            rule = (
                "Required subcategory under Electronic (e.g. Resistor, Capacitor, Microcontroller)"
                if item_type == "electronic_item"
                else f"Optional; must match '{defn['default_subcategory']}' if provided"
            )
        elif k == "category":
            rule = (
                f"Optional; must be '{defn['root_category']}' if provided"
            )
        else:
            rule = f["label"]
        ws_guide.append([k, req_str, rule])

    if item_type == "o_ring":
        ws_guide.append([
            "cross_section",
            "Auto-calculated",
            "Do NOT enter manually. Database calculates (outer_diameter - inner_diameter) / 2.",
        ])

    for col in ws_guide.columns:
        max_len = max((len(str(cell.value or "")) for cell in col), default=12)
        ws_guide.column_dimensions[col[0].column_letter].width = min(max(max_len + 4, 16), 60)

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue()


def inspect_import_upload(
    upload_id: str,
    upload_dir: str | Path,
    item_type: str,
    sheet_name: str | None = None,
) -> dict:
    """Inspect uploaded Excel headers, sheet names, sample rows, and type-specific mapping."""
    defn = get_spec_definition(item_type)
    path = resolve_uploaded_xlsx(upload_id, upload_dir)
    sheet_names, selected_sheet, headers, data_rows = _read_workbook_sheet(path, sheet_name)
    fields_meta = _build_type_fields_meta(item_type)
    mapping = _suggest_mapping_for_type(headers, item_type)

    sample_rows = [
        {
            "row_number": entry["row_number"],
            "values": {h: clean_text(entry["raw"].get(h)) for h in headers},
        }
        for entry in data_rows[:5]
    ]

    return {
        "upload_id": upload_id,
        "item_type": item_type,
        "item_type_label_fa": defn["label_fa"],
        "item_type_label_en": defn["label_en"],
        "fields": [{"key": f["key"], "label": f["label"], "required": f["required"]} for f in fields_meta],
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
            "New item codes are created with their specification record and OPENING stock transaction. "
            "Existing items of the same type update metadata and specs ONLY — stock, costs, and OPENING history are never overwritten."
        )
    return (
        "Safe default policy: Only new item codes are created with their specification record and OPENING transaction. "
        "Existing item codes are skipped without changing specifications, stock, or costs."
    )


def _validate_import_category_preview(
    item_type: str,
    category_name: str | None,
    sub_category_name: str | None,
) -> tuple[str, str]:
    """Validate category/sub_category compatibility for item_type without touching DB."""
    defn = get_spec_definition(item_type)
    if item_type == "electronic_item":
        root = category_name
        if root and root.strip().lower() in ("electronics", "electronic"):
            root = "Electronic"

        if sub_category_name:
            if root and root.strip().lower() != "electronic":
                raise AppError(
                    f"Electronic import requires root category 'Electronic' (found '{root}')."
                )
            return "Electronic", sub_category_name
        if root and root.strip().lower() != "electronic":
            if resolve_spec_type("Mechanical", root, is_leaf=True) is not None or root.strip().lower() == "mechanical":
                raise AppError(
                    f"Category '{root}' belongs to Mechanical components and cannot be imported as Electronic Items."
                )
            return "Electronic", root
        raise AppError(
            "Missing sub_category: electronic items require a subcategory (e.g. Resistor, Capacitor)."
        )

    expected_leaf = defn["default_subcategory"]
    if category_name:
        cat_key = category_name.strip().lower()
        if cat_key in ("electronic", "electronics"):
            raise AppError(
                f"Category '{category_name}' belongs to Electronic components and cannot be imported as {defn['label_en']}."
            )
        if cat_key != "mechanical" and resolve_spec_type("Mechanical", category_name, is_leaf=True) != item_type:
            raise AppError(
                f"Category '{category_name}' is incompatible with {defn['label_en']} import."
            )

    if sub_category_name and resolve_spec_type("Mechanical", sub_category_name, is_leaf=True) != item_type:
        raise AppError(
            f"Subcategory '{sub_category_name}' is incompatible with {defn['label_en']} import (expected '{expected_leaf}')."
        )

    return "Mechanical", expected_leaf


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
            fn_resolve_category_spec_type(i.category_id) AS existing_item_type,
            inv.quantity AS current_quantity,
            EXISTS(
                SELECT 1 FROM inventory_transaction t
                 WHERE t.item_id = i.id AND t.transaction_type = 'OPENING'
            ) AS has_opening_tx
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
    item_type: str,
    sheet_name: str | None = None,
    column_mapping: dict | None = None,
    existing_policy: str = "skip",
) -> dict:
    """Validate Excel rows for a specific item_type and return dry-run preview."""
    defn = get_spec_definition(item_type)
    policy = (existing_policy or "skip").strip()
    if policy not in ALLOWED_POLICIES:
        raise AppError(f"Unsupported existing_policy '{existing_policy}'.")

    path = resolve_uploaded_xlsx(upload_id, upload_dir)
    sheet_names, selected_sheet, headers, data_rows = _read_workbook_sheet(path, sheet_name)
    mapping = (
        column_mapping
        if isinstance(column_mapping, dict) and column_mapping
        else _suggest_mapping_for_type(headers, item_type)
    )

    fields_meta = _build_type_fields_meta(item_type)
    missing_cols = [
        f["key"]
        for f in fields_meta
        if f["required"] and not mapping.get(f["key"])
    ]
    if item_type == "electronic_item" and not (mapping.get("sub_category") or mapping.get("category")):
        missing_cols.append("sub_category")
    if missing_cols:
        raise AppError(
            f"Required column mapping missing for {defn['label_en']}: {', '.join(dict.fromkeys(missing_cols))}."
        )

    parsed_rows = []
    code_occurrences: dict[str, list[int]] = {}
    spec_field_names = [f["name"] for f in defn["fields"] if f["kind"] != "computed_mm"]

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
            raw_cat = clean_text(get_col("category"), max_len=100)
        except AppError as exc:
            raw_cat = None
            errors.append(f"category: {exc.message}")

        try:
            raw_sub = clean_text(get_col("sub_category"), max_len=100)
        except AppError as exc:
            raw_sub = None
            errors.append(f"sub_category: {exc.message}")

        resolved_cat = None
        resolved_sub = None
        try:
            resolved_cat, resolved_sub = _validate_import_category_preview(
                item_type, raw_cat, raw_sub
            )
        except AppError as exc:
            missing_category_flag = True
            errors.append(exc.message)

        raw_specs = {fname: get_col(fname) for fname in spec_field_names}
        clean_specs = {}
        try:
            clean_specs = validate_specs(item_type, raw_specs)
            if item_type == "o_ring":
                clean_specs["cross_section"] = compute_o_ring_cross_section(
                    clean_specs["inner_diameter"],
                    clean_specs["outer_diameter"],
                )
        except AppError as exc:
            errors.append(exc.message)

        try:
            location = clean_text(get_col("location"), max_len=150)
            if not location:
                errors.append("Missing location.")
        except AppError as exc:
            location = None
            errors.append(f"location: {exc.message}")

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
            "category": resolved_cat,
            "sub_category": resolved_sub,
            "specs": clean_specs,
            "spec_summary": build_spec_summary(item_type, clean_specs) if clean_specs else "—",
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
    category_pairs_to_apply: list[tuple[str, str]] = []

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
            existing_type = existing_info["existing_item_type"]
            if existing_type and existing_type != item_type and policy == "update_metadata":
                status = "invalid"
                action = "blocked"
                invalid_rows += 1
                errors.append(
                    f"Existing item '{code}' is registered as '{existing_type}' and cannot be updated via '{item_type}' import."
                )
            else:
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
            "specs": row["specs"],
            "spec_summary": row["spec_summary"],
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
        "item_type": item_type,
        "item_type_label_fa": defn["label_fa"],
        "item_type_label_en": defn["label_en"],
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
    item_type: str,
    sheet_name: str | None = None,
    column_mapping: dict | None = None,
    existing_policy: str = "skip",
) -> dict:
    """Populate categories, items, type-specific spec records, and OPENING transactions."""
    preview = preview_import(
        upload_id=upload_id,
        upload_dir=upload_dir,
        item_type=item_type,
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

    if applicable_rows:
        try:
            with db.transaction() as cur:
                for row in applicable_rows:
                    cat_key = row["category"].strip().lower()
                    sub_key = (row["sub_category"] or "").strip().lower()
                    pair_key = (cat_key, sub_key)
                    if pair_key in resolved_category_ids:
                        continue
                    cat_id, created_parent, created_child = resolve_category_for_spec_type(
                        cur,
                        item_type,
                        row["category"],
                        row["sub_category"],
                    )
                    resolved_category_ids[pair_key] = cat_id
                    if created_parent:
                        categories_created += 1
                    if created_child:
                        subcategories_created += 1
        except psycopg2.Error as exc:
            raise translate_pg_error(exc) from exc

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
                "spec_summary": row["spec_summary"],
                "status": "failed",
                "reason": "; ".join(row["errors"]),
            })
            continue

        if status == "existing" and policy == "skip":
            skipped_count += 1
            results.append({
                "row_number": row["row_number"],
                "item_code": row["item_code"],
                "spec_summary": row["spec_summary"],
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
                        INSERT INTO item (item_code, category_id, location, description)
                        VALUES (%s, %s, %s, %s)
                        RETURNING id;
                        """,
                        (
                            row["item_code"],
                            category_id,
                            row["location"],
                            row["description"],
                        ),
                    )
                    item_id = cur.fetchone()["id"]
                    upsert_spec_row(cur, item_type, item_id, row["specs"])

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
                        "spec_summary": row["spec_summary"],
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
                               location = %s,
                               description = %s
                         WHERE item_code = %s
                        RETURNING id;
                        """,
                        (
                            category_id,
                            row["location"],
                            row["description"],
                            row["item_code"],
                        ),
                    )
                    item_id = cur.fetchone()["id"]
                    upsert_spec_row(cur, item_type, item_id, row["specs"])
                    updated_count += 1
                    results.append({
                        "row_number": row["row_number"],
                        "item_code": row["item_code"],
                        "spec_summary": row["spec_summary"],
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
                "spec_summary": row["spec_summary"],
                "status": "failed",
                "reason": err.message,
            })

    try:
        resolve_uploaded_xlsx(upload_id, upload_dir).unlink(missing_ok=True)
    except Exception:
        pass

    return {
        "item_type": item_type,
        "item_type_label_fa": preview["item_type_label_fa"],
        "item_type_label_en": preview["item_type_label_en"],
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
