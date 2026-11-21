"""Dashboard metrics and inventory analytics service."""

from ims.db import get_db
from ims.services.item_service import CAT_INFO_CTE
from ims.utils import clean_text


def get_dashboard_summary() -> dict:
    """Compute core dashboard inventory metrics, valuations, and recent activity.

    Low-stock threshold is intentionally omitted per current requirements.
    """
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT
                COUNT(*)::INT AS distinct_items,
                COALESCE(SUM(inv.quantity), 0)::BIGINT AS total_quantity,
                COUNT(*) FILTER (WHERE inv.quantity = 0)::INT AS zero_stock_count,
                COALESCE(
                    SUM(inv.quantity::NUMERIC * inv.weighted_avg_cost)
                    FILTER (WHERE inv.quantity > 0 AND inv.weighted_avg_cost IS NOT NULL),
                    0
                ) AS wac_known_value,
                COUNT(*) FILTER (
                    WHERE inv.quantity > 0 AND inv.weighted_avg_cost IS NULL
                )::INT AS wac_missing_cost_items,
                COALESCE(
                    SUM(inv.quantity::NUMERIC * inv.last_purchase_cost)
                    FILTER (WHERE inv.quantity > 0 AND inv.last_purchase_cost IS NOT NULL),
                    0
                ) AS lpc_known_value,
                COUNT(*) FILTER (
                    WHERE inv.quantity > 0 AND inv.last_purchase_cost IS NULL
                )::INT AS lpc_missing_cost_items
            FROM inventory inv;
            """
        )
        inv_metrics = dict(cur.fetchone())

        cur.execute(
            """
            SELECT
                COUNT(*) FILTER (
                    WHERE transaction_type IN ('OPENING', 'PURCHASE_IN', 'ADJUSTMENT_IN')
                )::INT AS incoming_tx_count,
                COUNT(*) FILTER (
                    WHERE transaction_type IN ('OUT', 'ADJUSTMENT_OUT')
                )::INT AS outgoing_tx_count,
                COUNT(*)::INT AS total_tx_count
            FROM inventory_transaction;
            """
        )
        tx_metrics = dict(cur.fetchone())

        cur.execute(
            f"""
            {CAT_INFO_CTE}
            SELECT
                t.id,
                t.item_id,
                i.item_code,
                i.model,
                ci.category_path,
                t.transaction_type,
                t.quantity,
                t.stock_before,
                t.stock_after,
                t.unit_cost_snapshot,
                t.transaction_cost_snapshot,
                t.created_at,
                u.user_name
            FROM inventory_transaction t
            JOIN item i ON i.id = t.item_id
            JOIN cat_info ci ON ci.id = i.category_id
            JOIN app_user u ON u.id = t.user_id
            ORDER BY t.created_at DESC, t.id DESC
            LIMIT 10;
            """
        )
        recent_movements = [dict(r) for r in cur.fetchall()]

        cur.execute(
            f"""
            {CAT_INFO_CTE}
            SELECT
                i.id,
                i.item_code,
                i.model,
                i.location,
                i.mounting_type,
                i.size,
                ci.category_name,
                ci.subcategory_name,
                ci.category_path,
                inv.quantity,
                inv.weighted_avg_cost,
                inv.last_purchase_cost,
                i.created_at
            FROM item i
            JOIN inventory inv ON inv.item_id = i.id
            JOIN cat_info ci ON ci.id = i.category_id
            ORDER BY i.created_at DESC, i.id DESC
            LIMIT 8;
            """
        )
        recent_items = [dict(r) for r in cur.fetchall()]

    wac_complete = inv_metrics["wac_missing_cost_items"] == 0
    lpc_complete = inv_metrics["lpc_missing_cost_items"] == 0

    return {
        "metrics": {
            "distinct_items": inv_metrics["distinct_items"],
            "total_quantity": inv_metrics["total_quantity"],
            "zero_stock_count": inv_metrics["zero_stock_count"],
            "wac_known_value": inv_metrics["wac_known_value"],
            "wac_missing_cost_items": inv_metrics["wac_missing_cost_items"],
            "wac_complete": wac_complete,
            "lpc_known_value": inv_metrics["lpc_known_value"],
            "lpc_missing_cost_items": inv_metrics["lpc_missing_cost_items"],
            "lpc_complete": lpc_complete,
            "incoming_tx_count": tx_metrics["incoming_tx_count"],
            "outgoing_tx_count": tx_metrics["outgoing_tx_count"],
            "total_tx_count": tx_metrics["total_tx_count"],
        },
        "recent_movements": recent_movements,
        "recent_items": recent_items,
    }


def get_analytics(date_from: str | None = None, date_to: str | None = None) -> dict:
    """Compute category valuation breakdown and transaction movement summaries."""
    clean_from = clean_text(date_from)
    clean_to = clean_text(date_to)

    tx_clauses = []
    tx_params: list = []
    if clean_from:
        tx_clauses.append("t.created_at >= %s::date")
        tx_params.append(clean_from)
    if clean_to:
        tx_clauses.append("t.created_at < (%s::date + INTERVAL '1 day')")
        tx_params.append(clean_to)
    tx_where = f"WHERE {' AND '.join(tx_clauses)}" if tx_clauses else ""

    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            f"""
            {CAT_INFO_CTE}
            SELECT
                ci.category_name,
                ci.subcategory_name,
                ci.category_path,
                COUNT(i.id)::INT AS distinct_items,
                COALESCE(SUM(inv.quantity), 0)::BIGINT AS total_quantity,
                COUNT(*) FILTER (WHERE inv.quantity = 0)::INT AS zero_stock_count,
                COALESCE(
                    SUM(inv.quantity::NUMERIC * inv.weighted_avg_cost)
                    FILTER (WHERE inv.quantity > 0 AND inv.weighted_avg_cost IS NOT NULL),
                    0
                ) AS wac_known_value,
                COUNT(*) FILTER (
                    WHERE inv.quantity > 0 AND inv.weighted_avg_cost IS NULL
                )::INT AS wac_missing_cost_items,
                COALESCE(
                    SUM(inv.quantity::NUMERIC * inv.last_purchase_cost)
                    FILTER (WHERE inv.quantity > 0 AND inv.last_purchase_cost IS NOT NULL),
                    0
                ) AS lpc_known_value,
                COUNT(*) FILTER (
                    WHERE inv.quantity > 0 AND inv.last_purchase_cost IS NULL
                )::INT AS lpc_missing_cost_items
            FROM item i
            JOIN inventory inv ON inv.item_id = i.id
            JOIN cat_info ci ON ci.id = i.category_id
            GROUP BY ci.category_name, ci.subcategory_name, ci.category_path
            ORDER BY LOWER(ci.category_path);
            """
        )
        category_breakdown = []
        for r in cur.fetchall():
            row = dict(r)
            row["wac_complete"] = row["wac_missing_cost_items"] == 0
            row["lpc_complete"] = row["lpc_missing_cost_items"] == 0
            category_breakdown.append(row)

        cur.execute(
            f"""
            SELECT
                t.transaction_type,
                COUNT(*)::INT AS tx_count,
                COALESCE(SUM(t.quantity), 0)::BIGINT AS total_units,
                COALESCE(
                    SUM(t.transaction_cost_snapshot)
                    FILTER (WHERE t.transaction_cost_snapshot IS NOT NULL),
                    0
                ) AS known_cost_total,
                COUNT(*) FILTER (
                    WHERE t.transaction_cost_snapshot IS NULL
                )::INT AS unknown_cost_tx_count
            FROM inventory_transaction t
            {tx_where}
            GROUP BY t.transaction_type
            ORDER BY t.transaction_type;
            """,
            tuple(tx_params),
        )
        movement_summary = []
        for r in cur.fetchall():
            row = dict(r)
            row["cost_complete"] = row["unknown_cost_tx_count"] == 0
            movement_summary.append(row)

    return {
        "category_breakdown": category_breakdown,
        "movement_summary": movement_summary,
    }
