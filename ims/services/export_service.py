"""Single-sheet and multi-sheet Excel export service for multi-table inventory & transactions."""

from decimal import Decimal
from io import BytesIO
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from ims.item_specs import SPEC_DEFINITIONS, SPEC_TYPES_ORDER
from ims.jalali import format_jalali_datetime
from ims.services.item_service import list_items
from ims.services.transaction_service import list_transactions
from ims.utils import clean_text


def _style_header(ws, row_idx: int, col_count: int) -> None:
    fill = PatternFill("solid", fgColor="1E293B")
    font = Font(color="FFFFFF", bold=True)
    for col in range(1, col_count + 1):
        cell = ws.cell(row=row_idx, column=col)
        cell.fill = fill
        cell.font = font
        cell.alignment = Alignment(horizontal="left", vertical="center")


def _to_toman(val) -> float | None:
    """Convert a Rial numeric value to Toman (Rial / 10)."""
    if val is None:
        return None
    return float(Decimal(str(val)) / Decimal("10"))


def _auto_fit(ws) -> None:
    for col in ws.columns:
        max_len = 0
        col_letter = col[0].column_letter
        for cell in col:
            val_str = "" if cell.value is None else str(cell.value)
            max_len = max(max_len, len(val_str))
        ws.column_dimensions[col_letter].width = min(max(max_len + 4, 12), 44)


def _populate_inventory_worksheet(ws, spec_type: str | None, items: list[dict]) -> None:
    """Populate a single inventory worksheet tailored to spec_type's columns."""
    spec_fields = SPEC_DEFINITIONS[spec_type]["fields"] if spec_type in SPEC_DEFINITIONS else []
    spec_headers = [f["excel_header"] for f in spec_fields]

    headers = [
        "Item Code",
        "Category",
        "Subcategory",
        *spec_headers,
        "Location",
        "Current Quantity",
        "Weighted Avg Cost (Rial)",
        "Weighted Avg Cost (Toman)",
        "Last Purchase Cost (Rial)",
        "Last Purchase Cost (Toman)",
        "Total Value (WAC)",
        "Total Value (WAC) (Toman)",
        "Total Value (Last Purchase) (Rial)",
        "Total Value (Last Purchase) (Toman)",
        "Updated At (Jalali)",
        "Description",
    ]
    ws.append(headers)
    _style_header(ws, 1, len(headers))

    spec_offset = 3  # Item Code, Category, Subcategory
    loc_col = spec_offset + len(spec_fields) + 1
    qty_col = loc_col + 1
    cost_start_col = qty_col + 1
    cost_end_col = qty_col + 8  # inclusive (8 Rial/Toman columns)

    mm_col_indices = [
        spec_offset + idx + 1
        for idx, f in enumerate(spec_fields)
        if f["kind"] in ("mm", "computed_mm")
    ]

    total_qty = 0
    wac_subtotal = Decimal("0.0000")
    lpc_subtotal = Decimal("0.0000")
    wac_missing = 0
    lpc_missing = 0

    for item in items:
        qty = int(item["quantity"])
        total_qty += qty

        wac = item["weighted_avg_cost"]
        lpc = item["last_purchase_cost"]
        val_wac = item["total_wac_value"]
        val_lpc = item["total_lpc_value"]

        if qty > 0 and wac is None:
            wac_missing += 1
        elif val_wac is not None:
            wac_subtotal += Decimal(val_wac)

        if qty > 0 and lpc is None:
            lpc_missing += 1
        elif val_lpc is not None:
            lpc_subtotal += Decimal(val_lpc)

        specs = item.get("specs") or {}
        spec_cells = []
        for f in spec_fields:
            raw_v = specs.get(f["name"])
            if f["kind"] in ("mm", "computed_mm"):
                spec_cells.append(float(raw_v) if raw_v is not None else None)
            else:
                spec_cells.append(raw_v if raw_v is not None else "")

        ws.append([
            item["item_code"],
            item["category_name"] or "",
            item["subcategory_name"] or "",
            *spec_cells,
            item["location"],
            qty,
            float(wac) if wac is not None else None,
            _to_toman(wac),
            float(lpc) if lpc is not None else None,
            _to_toman(lpc),
            float(val_wac) if val_wac is not None else None,
            _to_toman(val_wac),
            float(val_lpc) if val_lpc is not None else None,
            _to_toman(val_lpc),
            item.get("inventory_updated_at_jalali")
            or format_jalali_datetime(item.get("inventory_updated_at")),
            item["description"] or "",
        ])

    for r_idx in range(2, len(items) + 2):
        for mm_col in mm_col_indices:
            mm_cell = ws.cell(row=r_idx, column=mm_col)
            if mm_cell.value is not None:
                mm_cell.number_format = "#,##0.###"
        ws.cell(row=r_idx, column=qty_col).number_format = "#,##0"
        for c_idx in range(cost_start_col, cost_end_col + 1):
            cell = ws.cell(row=r_idx, column=c_idx)
            if cell.value is not None:
                cell.number_format = "#,##0.0000"

    ws.append([])
    summary_row = ws.max_row + 1
    wac_toman_sub = wac_subtotal / Decimal("10")
    lpc_toman_sub = lpc_subtotal / Decimal("10")

    ws.append([
        f"TOTAL ({len(items)} items)",
        "",
        "",
        *([""] * len(spec_fields)),
        "",
        total_qty,
        "",
        "",
        "",
        "",
        float(wac_subtotal) if wac_missing == 0 else f"INCOMPLETE ({wac_subtotal}; {wac_missing} missing)",
        float(wac_toman_sub) if wac_missing == 0 else f"INCOMPLETE ({wac_toman_sub}; {wac_missing} missing)",
        float(lpc_subtotal) if lpc_missing == 0 else f"INCOMPLETE ({lpc_subtotal}; {lpc_missing} missing)",
        float(lpc_toman_sub) if lpc_missing == 0 else f"INCOMPLETE ({lpc_toman_sub}; {lpc_missing} missing)",
        "",
        "Unit: Rial (IRR) & Toman (Rial / 10)" + (" | Mechanical dims in mm" if mm_col_indices else ""),
    ])
    for c_idx in range(1, len(headers) + 1):
        ws.cell(row=summary_row, column=c_idx).font = Font(bold=True)
    ws.cell(row=summary_row, column=qty_col).number_format = "#,##0"
    if wac_missing == 0:
        ws.cell(row=summary_row, column=qty_col + 5).number_format = "#,##0.0000"
        ws.cell(row=summary_row, column=qty_col + 6).number_format = "#,##0.0000"
    if lpc_missing == 0:
        ws.cell(row=summary_row, column=qty_col + 7).number_format = "#,##0.0000"
        ws.cell(row=summary_row, column=qty_col + 8).number_format = "#,##0.0000"

    ws.freeze_panes = "A2"
    _auto_fit(ws)


def export_inventory_xlsx(filters: dict) -> bytes:
    """Generate a single-sheet (1 type) or multi-sheet (multiple types) inventory workbook."""
    result = list_items(filters, paginate=False)
    items = result["items"]

    grouped: dict[str, list[dict]] = {t: [] for t in SPEC_TYPES_ORDER}
    extra_items: list[dict] = []
    for item in items:
        t = item.get("item_type")
        if t in grouped:
            grouped[t].append(item)
        else:
            extra_items.append(item)

    active_types = [t for t in SPEC_TYPES_ORDER if grouped[t]]

    wb = Workbook()
    if not active_types and not extra_items:
        ws = wb.active
        req_type = clean_text(filters.get("item_type"))
        if req_type in SPEC_DEFINITIONS:
            ws.title = SPEC_DEFINITIONS[req_type]["sheet_name"]
            _populate_inventory_worksheet(ws, req_type, [])
        else:
            ws.title = "Inventory Report"
            _populate_inventory_worksheet(ws, None, [])
    else:
        first_sheet_used = False
        for t in active_types:
            sheet_title = SPEC_DEFINITIONS[t]["sheet_name"]
            if not first_sheet_used:
                ws = wb.active
                ws.title = sheet_title
                first_sheet_used = True
            else:
                ws = wb.create_sheet(sheet_title)
            _populate_inventory_worksheet(ws, t, grouped[t])

        if extra_items:
            ws = wb.active if not first_sheet_used else wb.create_sheet("Other Items")
            ws.title = "Other Items"
            _populate_inventory_worksheet(ws, None, extra_items)

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue()


def export_transactions_xlsx(filters: dict) -> bytes:
    """Generate a styled Excel movement report from filtered inventory transactions."""
    result = list_transactions(filters, paginate=False)
    rows = result["transactions"]

    wb = Workbook()
    ws = wb.active
    ws.title = "Movement Report"

    headers = [
        "Transaction ID",
        "Timestamp (Jalali)",
        "Type",
        "Item Code",
        "Item Type",
        "Category",
        "Subcategory",
        "Specifications",
        "User",
        "Quantity",
        "Stock Before",
        "Stock After",
        "Entered Price (Rial)",
        "Entered Price (Toman)",
        "Unit Cost Snapshot (Rial)",
        "Unit Cost Snapshot (Toman)",
        "Transaction Cost Snapshot (Rial)",
        "Transaction Cost Snapshot (Toman)",
        "Description",
    ]
    ws.append(headers)
    _style_header(ws, 1, len(headers))

    for tx in rows:
        created_str = tx.get("created_at_jalali") or format_jalali_datetime(tx.get("created_at"))
        ws.append([
            tx["id"],
            created_str,
            tx["transaction_type"],
            tx["item_code"],
            tx.get("item_type_label_en") or "",
            tx["category_name"] or "",
            tx["subcategory_name"] or "",
            tx.get("spec_summary") or tx.get("display_name") or "",
            tx["user_name"],
            int(tx["quantity"]),
            int(tx["stock_before"]),
            int(tx["stock_after"]),
            float(tx["price"]) if tx["price"] is not None else None,
            _to_toman(tx["price"]),
            float(tx["unit_cost_snapshot"]) if tx["unit_cost_snapshot"] is not None else None,
            _to_toman(tx["unit_cost_snapshot"]),
            float(tx["transaction_cost_snapshot"]) if tx["transaction_cost_snapshot"] is not None else None,
            _to_toman(tx["transaction_cost_snapshot"]),
            tx["description"] or "",
        ])

    for r_idx in range(2, len(rows) + 2):
        for c_idx in (10, 11, 12):
            ws.cell(row=r_idx, column=c_idx).number_format = "#,##0"
        for c_idx in range(13, 19):
            cell = ws.cell(row=r_idx, column=c_idx)
            if cell.value is not None:
                cell.number_format = "#,##0.0000"

    ws.freeze_panes = "A2"
    _auto_fit(ws)

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue()
