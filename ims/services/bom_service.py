"""Read-only BOM Excel analysis, availability checking, and dual-cost calculation."""

from collections import Counter
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from ims.db import AppError, get_db
from ims.services.item_service import CAT_INFO_CTE
from ims.utils import clean_text, parse_positive_int, resolve_uploaded_xlsx


BOM_FIELD_ALIASES = {
    "item_code": ("item_code", "item code", "code", "part_number", "part number", "sku"),
    "quantity": ("quantity", "qty", "required_qty", "required qty", "req_qty", "count", "amount"),
    "item_name": ("item_name", "item name", "name", "model", "part", "component", "description"),
}


def _suggest_bom_mapping(headers: list[str]) -> dict[str, str | None]:
    normalized = {h.strip().lower(): h for h in headers}
    mapping: dict[str, str | None] = {}
    for target, aliases in BOM_FIELD_ALIASES.items():
        matched = None
        for alias in aliases:
            if alias in normalized:
                matched = normalized[alias]
                break
        mapping[target] = matched
    return mapping


def _read_bom_sheet(path: Path, sheet_name: str | None = None) -> tuple[list[str], str, list[str], list[dict]]:
    try:
        wb = load_workbook(filename=path, data_only=True, read_only=False)
    except Exception as exc:
        raise AppError(f"Failed to read BOM Excel file: {exc}") from exc

    try:
        sheet_names = list(wb.sheetnames)
        if not sheet_names:
            raise AppError("The uploaded BOM workbook contains no worksheets.")
        selected = sheet_name if sheet_name and sheet_name in sheet_names else sheet_names[0]
        if sheet_name and sheet_name not in sheet_names:
            raise AppError(f"Worksheet '{sheet_name}' not found in BOM workbook.")
        raw_rows = list(wb[selected].iter_rows(values_only=True))
    finally:
        wb.close()

    if not raw_rows:
        raise AppError("The BOM worksheet is empty.")

    col_indices: list[tuple[int, str]] = []
    seen: Counter = Counter()
    for idx, cell in enumerate(raw_rows[0]):
        header_text = clean_text(cell)
        if not header_text:
            continue
        seen[header_text] += 1
        unique_h = header_text if seen[header_text] == 1 else f"{header_text} ({seen[header_text]})"
        col_indices.append((idx, unique_h))

    if not col_indices:
        raise AppError("Row 1 of the BOM worksheet must contain column headers.")

    headers = [h for _, h in col_indices]
    data_rows = []
    for row_idx, row_vals in enumerate(raw_rows[1:], start=2):
        row_dict = {}
        has_any = False
        for col_idx, header_name in col_indices:
            val = row_vals[col_idx] if col_idx < len(row_vals) else None
            if clean_text(val) is not None:
                has_any = True
            row_dict[header_name] = val
        if has_any:
            data_rows.append({"row_number": row_idx, "raw": row_dict})

    return sheet_names, selected, headers, data_rows


def inspect_bom_upload(upload_id: str, upload_dir: str | Path, sheet_name: str | None = None) -> dict:
    """Inspect BOM Excel headers and return suggested column mapping."""
    path = resolve_uploaded_xlsx(upload_id, upload_dir)
    sheet_names, selected, headers, data_rows = _read_bom_sheet(path, sheet_name)
    mapping = _suggest_bom_mapping(headers)
    sample_rows = [
        {"row_number": r["row_number"], "values": {h: clean_text(r["raw"].get(h)) for h in headers}}
        for r in data_rows[:5]
    ]
    return {
        "upload_id": upload_id,
        "sheet_names": sheet_names,
        "selected_sheet": selected,
        "headers": headers,
        "suggested_mapping": mapping,
        "total_data_rows": len(data_rows),
        "sample_rows": sample_rows,
    }


def calculate_bom(
    upload_id: str,
    upload_dir: str | Path,
    sheet_name: str | None = None,
    column_mapping: dict | None = None,
) -> dict:
    """Perform read-only BOM availability and dual-cost calculation."""
    path = resolve_uploaded_xlsx(upload_id, upload_dir)
    sheet_names, selected, headers, data_rows = _read_bom_sheet(path, sheet_name)
    mapping = column_mapping if isinstance(column_mapping, dict) and column_mapping else _suggest_bom_mapping(headers)

    if not mapping.get("item_code") or not mapping.get("quantity"):
        raise AppError("Column mapping must identify both Item Code and Quantity.")

    invalid_rows = []
    aggregated: dict[str, dict] = {}
    order_codes: list[str] = []
    merged_duplicate_rows = 0

    for entry in data_rows:
        row_num = entry["row_number"]
        raw = entry["raw"]
        code_raw = raw.get(mapping["item_code"])
        qty_raw = raw.get(mapping["quantity"])
        name_raw = raw.get(mapping.get("item_name")) if mapping.get("item_name") else None

        row_errors = []
        try:
            item_code = clean_text(code_raw, max_len=80)
            if not item_code:
                row_errors.append("Missing Item Code.")
        except AppError as exc:
            item_code = None
            row_errors.append(exc.message)

        qty = None
        try:
            qty = parse_positive_int(qty_raw, "quantity")
        except AppError as exc:
            row_errors.append(exc.message)

        bom_name = clean_text(name_raw)

        if row_errors:
            invalid_rows.append({
                "row_number": row_num,
                "item_code": clean_text(code_raw),
                "item_name": bom_name,
                "quantity": clean_text(qty_raw),
                "error": " ".join(row_errors),
            })
            continue

        if item_code not in aggregated:
            aggregated[item_code] = {
                "item_code": item_code,
                "bom_item_name": bom_name,
                "required_qty": 0,
                "row_numbers": [],
            }
            order_codes.append(item_code)
        else:
            merged_duplicate_rows += 1
            if not aggregated[item_code]["bom_item_name"] and bom_name:
                aggregated[item_code]["bom_item_name"] = bom_name

        aggregated[item_code]["required_qty"] += qty
        aggregated[item_code]["row_numbers"].append(row_num)

    db_items: dict[str, dict] = {}
    if order_codes:
        db = get_db()
        with db.cursor() as cur:
            cur.execute(
                f"""
                {CAT_INFO_CTE}
                SELECT
                    i.id,
                    i.item_code,
                    i.model,
                    i.size,
                    i.mounting_type,
                    i.location,
                    ci.category_name,
                    ci.subcategory_name,
                    ci.category_path,
                    inv.quantity AS available_qty,
                    inv.weighted_avg_cost,
                    inv.last_purchase_cost
                FROM item i
                JOIN inventory inv ON inv.item_id = i.id
                JOIN cat_info ci ON ci.id = i.category_id
                WHERE i.item_code = ANY(%s);
                """,
                (order_codes,),
            )
            db_items = {r["item_code"]: dict(r) for r in cur.fetchall()}

    availability_report = []
    cost_report = []

    available_count = 0
    insufficient_count = 0
    out_of_stock_count = 0
    unknown_count = 0

    wac_known_subtotal = Decimal("0.0000")
    lpc_known_subtotal = Decimal("0.0000")
    wac_missing_count = 0
    lpc_missing_count = 0

    for code in order_codes:
        bom_line = aggregated[code]
        req_qty = bom_line["required_qty"]
        db_row = db_items.get(code)
        merged_count = len(bom_line["row_numbers"])

        if db_row is None:
            unknown_count += 1
            wac_missing_count += 1
            lpc_missing_count += 1

            availability_report.append({
                "item_id": None,
                "item_code": code,
                "bom_item_name": bom_line["bom_item_name"],
                "model": None,
                "category_name": None,
                "subcategory_name": None,
                "location": None,
                "required_qty": req_qty,
                "available_qty": None,
                "shortage": req_qty,
                "status": "Unknown",
                "merged_rows": merged_count,
                "row_numbers": bom_line["row_numbers"],
            })
            cost_report.append({
                "item_id": None,
                "item_code": code,
                "item_name": bom_line["bom_item_name"] or "Unknown Component",
                "required_qty": req_qty,
                "weighted_avg_cost": None,
                "wac_line_total": None,
                "last_purchase_cost": None,
                "lpc_line_total": None,
                "wac_missing": True,
                "lpc_missing": True,
                "is_unknown": True,
            })
            continue

        avail_qty = int(db_row["available_qty"])
        if avail_qty == 0:
            avail_status = "Out of Stock"
            out_of_stock_count += 1
            shortage = req_qty
        elif avail_qty < req_qty:
            avail_status = "Insufficient"
            insufficient_count += 1
            shortage = req_qty - avail_qty
        else:
            avail_status = "Available"
            available_count += 1
            shortage = 0

        availability_report.append({
            "item_id": db_row["id"],
            "item_code": code,
            "bom_item_name": bom_line["bom_item_name"],
            "model": db_row["model"],
            "category_name": db_row["category_name"],
            "subcategory_name": db_row["subcategory_name"],
            "location": db_row["location"],
            "required_qty": req_qty,
            "available_qty": avail_qty,
            "shortage": shortage,
            "status": avail_status,
            "merged_rows": merged_count,
            "row_numbers": bom_line["row_numbers"],
        })

        wac = db_row["weighted_avg_cost"]
        lpc = db_row["last_purchase_cost"]
        req_dec = Decimal(req_qty)

        if wac is not None:
            wac_dec = Decimal(wac)
            wac_line = (req_dec * wac_dec).quantize(Decimal("0.0001"))
            wac_known_subtotal += wac_line
            wac_missing = False
        else:
            wac_line = None
            wac_missing = True
            wac_missing_count += 1

        if lpc is not None:
            lpc_dec = Decimal(lpc)
            lpc_line = (req_dec * lpc_dec).quantize(Decimal("0.0001"))
            lpc_known_subtotal += lpc_line
            lpc_missing = False
        else:
            lpc_line = None
            lpc_missing = True
            lpc_missing_count += 1

        display_name = db_row["model"]
        if bom_line["bom_item_name"] and bom_line["bom_item_name"] != db_row["model"]:
            display_name = f"{db_row['model']} ({bom_line['bom_item_name']})"

        cost_report.append({
            "item_id": db_row["id"],
            "item_code": code,
            "item_name": display_name,
            "required_qty": req_qty,
            "weighted_avg_cost": wac,
            "wac_line_total": wac_line,
            "last_purchase_cost": lpc,
            "lpc_line_total": lpc_line,
            "wac_missing": wac_missing,
            "lpc_missing": lpc_missing,
            "is_unknown": False,
        })

    wac_complete = (wac_missing_count == 0 and len(order_codes) > 0)
    lpc_complete = (lpc_missing_count == 0 and len(order_codes) > 0)

    return {
        "upload_id": upload_id,
        "sheet_names": sheet_names,
        "selected_sheet": selected,
        "column_mapping": mapping,
        "read_only": True,
        "availability_summary": {
            "total_data_rows": len(data_rows),
            "total_unique_items": len(order_codes),
            "available": available_count,
            "insufficient": insufficient_count,
            "out_of_stock": out_of_stock_count,
            "unknown": unknown_count,
            "invalid_rows": len(invalid_rows),
            "merged_duplicate_rows": merged_duplicate_rows,
        },
        "availability_report": availability_report,
        "cost_summary": {
            "wac_complete": wac_complete,
            "wac_missing_count": wac_missing_count,
            "wac_known_subtotal": wac_known_subtotal.quantize(Decimal("0.0001")),
            "wac_total": wac_known_subtotal.quantize(Decimal("0.0001")) if wac_complete else None,
            "lpc_complete": lpc_complete,
            "lpc_missing_count": lpc_missing_count,
            "lpc_known_subtotal": lpc_known_subtotal.quantize(Decimal("0.0001")),
            "lpc_total": lpc_known_subtotal.quantize(Decimal("0.0001")) if lpc_complete else None,
            "has_invalid_rows": len(invalid_rows) > 0,
        },
        "cost_report": cost_report,
        "invalid_rows": invalid_rows,
    }


def _style_header_row(ws, row_idx: int, col_count: int) -> None:
    fill = PatternFill("solid", fgColor="1E293B")
    font = Font(color="FFFFFF", bold=True)
    for col in range(1, col_count + 1):
        cell = ws.cell(row=row_idx, column=col)
        cell.fill = fill
        cell.font = font
        cell.alignment = Alignment(horizontal="left", vertical="center")


def _auto_fit_columns(ws) -> None:
    for col in ws.columns:
        max_len = 0
        col_letter = col[0].column_letter
        for cell in col:
            val_str = "" if cell.value is None else str(cell.value)
            max_len = max(max_len, len(val_str))
        ws.column_dimensions[col_letter].width = min(max(max_len + 4, 12), 42)


def _to_toman(val) -> float | None:
    if val is None:
        return None
    return float(Decimal(str(val)) / Decimal("10"))


def export_bom_report_xlsx(analysis: dict) -> bytes:
    """Generate a multi-sheet BOM Cost & Availability Excel report (Rial and Toman)."""
    wb = Workbook()

    # Sheet 1: BOM Cost Calculation
    ws_cost = wb.active
    ws_cost.title = "BOM Cost Summary"
    cost_headers = [
        "Item Code",
        "Item Name / Model",
        "Required Qty",
        "Weighted Avg Unit Cost (Rial)",
        "Weighted Avg Unit Cost (Toman)",
        "Weighted Avg Line Total (Rial)",
        "Weighted Avg Line Total (Toman)",
        "Last Purchase Unit Cost (Rial)",
        "Last Purchase Unit Cost (Toman)",
        "Last Purchase Line Total (Rial)",
        "Last Purchase Line Total (Toman)",
        "Cost Status",
    ]
    ws_cost.append(cost_headers)
    _style_header_row(ws_cost, 1, len(cost_headers))

    for row in analysis["cost_report"]:
        if row["is_unknown"]:
            status_note = "Unknown Item Code"
        elif row["wac_missing"] or row["lpc_missing"]:
            missing_parts = []
            if row["wac_missing"]:
                missing_parts.append("Average cost missing")
            if row["lpc_missing"]:
                missing_parts.append("Last Purchase missing")
            status_note = ", ".join(missing_parts)
        else:
            status_note = "Complete"

        ws_cost.append([
            row["item_code"],
            row["item_name"],
            row["required_qty"],
            float(row["weighted_avg_cost"]) if row["weighted_avg_cost"] is not None else "Unavailable",
            _to_toman(row["weighted_avg_cost"]) if row["weighted_avg_cost"] is not None else "Unavailable",
            float(row["wac_line_total"]) if row["wac_line_total"] is not None else "Unavailable",
            _to_toman(row["wac_line_total"]) if row["wac_line_total"] is not None else "Unavailable",
            float(row["last_purchase_cost"]) if row["last_purchase_cost"] is not None else "Unavailable",
            _to_toman(row["last_purchase_cost"]) if row["last_purchase_cost"] is not None else "Unavailable",
            float(row["lpc_line_total"]) if row["lpc_line_total"] is not None else "Unavailable",
            _to_toman(row["lpc_line_total"]) if row["lpc_line_total"] is not None else "Unavailable",
            status_note,
        ])

    cs = analysis["cost_summary"]
    ws_cost.append([])
    wac_toman_total = Decimal(str(cs["wac_total"])) / Decimal("10") if cs["wac_total"] is not None else None
    wac_toman_known = Decimal(str(cs["wac_known_subtotal"])) / Decimal("10")
    lpc_toman_total = Decimal(str(cs["lpc_total"])) / Decimal("10") if cs["lpc_total"] is not None else None
    lpc_toman_known = Decimal(str(cs["lpc_known_subtotal"])) / Decimal("10")
    ws_cost.append([
        "TOTAL (Weighted Average Cost)",
        "",
        "",
        "",
        "",
        float(cs["wac_total"]) if cs["wac_complete"] and cs["wac_total"] is not None
        else f"INCOMPLETE (known subtotal: {cs['wac_known_subtotal']} Rial, missing: {cs['wac_missing_count']})",
        float(wac_toman_total) if cs["wac_complete"] and wac_toman_total is not None
        else f"INCOMPLETE (known subtotal: {float(wac_toman_known)} Toman, missing: {cs['wac_missing_count']})",
        "",
        "",
        "",
        "",
        "Complete" if cs["wac_complete"] else "Incomplete",
    ])
    ws_cost.append([
        "TOTAL (Last Purchase Cost)",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        float(cs["lpc_total"]) if cs["lpc_complete"] and cs["lpc_total"] is not None
        else f"INCOMPLETE (known subtotal: {cs['lpc_known_subtotal']} Rial, missing: {cs['lpc_missing_count']})",
        float(lpc_toman_total) if cs["lpc_complete"] and lpc_toman_total is not None
        else f"INCOMPLETE (known subtotal: {float(lpc_toman_known)} Toman, missing: {cs['lpc_missing_count']})",
        "Complete" if cs["lpc_complete"] else "Incomplete",
    ])
    _auto_fit_columns(ws_cost)

    # Sheet 2: Inventory Availability
    ws_avail = wb.create_sheet("Inventory Availability")
    avail_headers = [
        "Item Code",
        "Model",
        "Category",
        "Subcategory",
        "Location",
        "Required Qty",
        "Available Qty",
        "Shortage",
        "Status",
        "Merged BOM Rows",
    ]
    ws_avail.append(avail_headers)
    _style_header_row(ws_avail, 1, len(avail_headers))

    for row in analysis["availability_report"]:
        ws_avail.append([
            row["item_code"],
            row["model"] or row["bom_item_name"] or "",
            row["category_name"] or "",
            row["subcategory_name"] or "",
            row["location"] or "",
            row["required_qty"],
            row["available_qty"] if row["available_qty"] is not None else "N/A",
            row["shortage"],
            row["status"],
            row["merged_rows"],
        ])
    _auto_fit_columns(ws_avail)

    # Sheet 3: Invalid Rows (if any)
    ws_inv = wb.create_sheet("Invalid Rows")
    inv_headers = ["Excel Row", "Item Code", "Item Name", "Raw Quantity", "Error"]
    ws_inv.append(inv_headers)
    _style_header_row(ws_inv, 1, len(inv_headers))
    for bad in analysis["invalid_rows"]:
        ws_inv.append([
            bad["row_number"],
            bad["item_code"] or "",
            bad["item_name"] or "",
            bad["quantity"] or "",
            bad["error"],
        ])
    _auto_fit_columns(ws_inv)

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue()
