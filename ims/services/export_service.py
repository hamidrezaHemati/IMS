"""Filtered Inventory and Movement History Excel export service."""

from decimal import Decimal
from io import BytesIO
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from ims.services.item_service import list_items
from ims.services.transaction_service import list_transactions


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


def export_inventory_xlsx(filters: dict) -> bytes:
    """Generate a styled Excel export matching the requested inventory filters."""
    result = list_items(filters, paginate=False)
    items = result["items"]

    wb = Workbook()
    ws = wb.active
    ws.title = "Inventory Report"

    headers = [
        "Item Code",
        "Category",
        "Subcategory",
        "Model",
        "Size",
        "Mounting Type",
        "Material",
        "Voltage",
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
        "Description",
    ]
    ws.append(headers)
    _style_header(ws, 1, len(headers))

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

        ws.append([
            item["item_code"],
            item["category_name"] or "",
            item["subcategory_name"] or "",
            item["model"],
            item["size"] or "",
            item["mounting_type"] or "",
            item["material"] or "",
            item["voltage"] or "",
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
            item["description"] or "",
        ])

    for r_idx in range(2, len(items) + 2):
        ws.cell(row=r_idx, column=10).number_format = "#,##0"
        for c_idx in range(11, 19):
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
        "",
        "",
        "",
        "",
        "",
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
        "Unit: Rial (IRR) & Toman (Rial / 10)",
    ])
    for c_idx in range(1, len(headers) + 1):
        ws.cell(row=summary_row, column=c_idx).font = Font(bold=True)
    ws.cell(row=summary_row, column=10).number_format = "#,##0"
    if wac_missing == 0:
        ws.cell(row=summary_row, column=15).number_format = "#,##0.0000"
        ws.cell(row=summary_row, column=16).number_format = "#,##0.0000"
    if lpc_missing == 0:
        ws.cell(row=summary_row, column=17).number_format = "#,##0.0000"
        ws.cell(row=summary_row, column=18).number_format = "#,##0.0000"

    ws.freeze_panes = "A2"
    _auto_fit(ws)

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
        "Timestamp (UTC)",
        "Type",
        "Item Code",
        "Category",
        "Subcategory",
        "Model",
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
        created_str = tx["created_at"].strftime("%Y-%m-%d %H:%M:%S") if tx["created_at"] else ""
        ws.append([
            tx["id"],
            created_str,
            tx["transaction_type"],
            tx["item_code"],
            tx["category_name"] or "",
            tx["subcategory_name"] or "",
            tx["model"],
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
        for c_idx in (9, 10, 11):
            ws.cell(row=r_idx, column=c_idx).number_format = "#,##0"
        for c_idx in range(12, 18):
            cell = ws.cell(row=r_idx, column=c_idx)
            if cell.value is not None:
                cell.number_format = "#,##0.0000"

    ws.freeze_panes = "A2"
    _auto_fit(ws)

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue()
