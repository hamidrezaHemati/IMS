import { apiFetch, buildQuery } from "../api.js";
import {
  escapeHtml,
  fmtCost,
  fmtDate,
  fmtQty,
  openItemDetailModal,
  populateCategorySelects,
  renderPagination,
  stockBadge,
  toast,
  txTypeBadge,
} from "../ui.js";

let currentPage = 1;

function renderKpis(m) {
  const container = document.getElementById("dashboard-kpis");
  const wacNote = m.wac_complete
    ? `<span class="kpi-note text-success">Complete across all stocked items</span>`
    : `<span class="kpi-note text-warning">Incomplete: ${fmtQty(m.wac_missing_cost_items)} stocked item(s) missing WAC</span>`;

  const lpcNote = m.lpc_complete
    ? `<span class="kpi-note text-success">Complete across all stocked items</span>`
    : `<span class="kpi-note text-warning">Incomplete: ${fmtQty(m.lpc_missing_cost_items)} stocked item(s) missing LPC</span>`;

  container.innerHTML = `
    <div class="card kpi-card">
      <span class="kpi-label">Distinct Items</span>
      <span class="kpi-value">${fmtQty(m.distinct_items)}</span>
      <span class="kpi-note">${fmtQty(m.zero_stock_count)} item(s) at zero stock</span>
    </div>
    <div class="card kpi-card">
      <span class="kpi-label">Total Stock Units</span>
      <span class="kpi-value">${fmtQty(m.total_quantity)}</span>
      <span class="kpi-note">Total physical component count</span>
    </div>
    <div class="card kpi-card">
      <span class="kpi-label">Value (Weighted Avg)</span>
      <span class="kpi-value">${fmtCost(m.wac_known_value)}</span>
      ${wacNote}
    </div>
    <div class="card kpi-card">
      <span class="kpi-label">Value (Last Purchase)</span>
      <span class="kpi-value">${fmtCost(m.lpc_known_value)}</span>
      ${lpcNote}
    </div>
    <div class="card kpi-card">
      <span class="kpi-label">Zero-Stock Items</span>
      <span class="kpi-value ${m.zero_stock_count > 0 ? "text-danger" : ""}">${fmtQty(m.zero_stock_count)}</span>
      <span class="kpi-note">Out-of-stock components</span>
    </div>
    <div class="card kpi-card">
      <span class="kpi-label">Transactions</span>
      <span class="kpi-value">${fmtQty(m.total_tx_count)}</span>
      <span class="kpi-note"><strong class="num">${fmtQty(m.incoming_tx_count)}</strong> in / <strong class="num">${fmtQty(m.outgoing_tx_count)}</strong> out</span>
    </div>
  `;
}

function renderRecentMovements(list) {
  const box = document.getElementById("dash-recent-tx");
  if (!list.length) {
    box.innerHTML = `<div class="empty-state">No inventory movements recorded yet.</div>`;
    return;
  }
  box.innerHTML = `
    <div style="display:flex;flex-direction:column;gap:10px;">
      ${list
        .map(
          (tx) => `
        <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;padding-bottom:8px;border-bottom:1px solid var(--border-color);">
          <div style="min-width:0;">
            <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
              ${txTypeBadge(tx.transaction_type)}
              <strong class="mono">${escapeHtml(tx.item_code)}</strong>
              <span class="text-secondary">${escapeHtml(tx.model)}</span>
            </div>
            <div class="text-muted" style="font-size:0.78rem;margin-top:2px;">
              ${escapeHtml(tx.user_name)} • ${escapeHtml(fmtDate(tx.created_at))}
            </div>
          </div>
          <div class="text-right num" style="flex-shrink:0;">
            <div><strong>${fmtQty(tx.quantity)}</strong></div>
            <div class="text-muted" style="font-size:0.78rem;">${fmtQty(tx.stock_before)} → ${fmtQty(tx.stock_after)}</div>
          </div>
        </div>`
        )
        .join("")}
    </div>
  `;
}

function renderRecentItems(items) {
  const box = document.getElementById("dash-recent-items");
  if (!items.length) {
    box.innerHTML = `<div class="empty-state">No items registered yet.</div>`;
    return;
  }
  box.innerHTML = `
    <div style="display:flex;flex-direction:column;gap:10px;">
      ${items
        .map(
          (it) => `
        <div data-item-id="${it.id}" class="recent-item-row" style="cursor:pointer;display:flex;justify-content:space-between;align-items:center;gap:10px;padding-bottom:8px;border-bottom:1px solid var(--border-color);">
          <div style="min-width:0;">
            <div><strong class="mono">${escapeHtml(it.item_code)}</strong> — ${escapeHtml(it.model)}</div>
            <div class="text-muted" style="font-size:0.78rem;">${escapeHtml(it.category_path)} • Loc: ${escapeHtml(it.location)}</div>
          </div>
          <div>${stockBadge(it.quantity)}</div>
        </div>`
        )
        .join("")}
    </div>
  `;
  box.querySelectorAll(".recent-item-row").forEach((el) => {
    el.addEventListener("click", () => openItemDetailModal(Number(el.dataset.itemId)));
  });
}

function getFilterParams(page = 1) {
  const parentCat = document.getElementById("d-parent-cat").value;
  const subCat = document.getElementById("d-sub-cat").value;
  return {
    page,
    page_size: 15,
    search: document.getElementById("d-search").value,
    category_id: subCat || parentCat,
    mounting_type: document.getElementById("d-mounting").value,
    location: document.getElementById("d-location").value,
    zero_stock: document.getElementById("d-zero").checked ? "true" : "",
  };
}

async function loadInventoryTable(page = 1) {
  currentPage = page;
  const tbody = document.getElementById("dash-items-tbody");
  const mobile = document.getElementById("dash-items-mobile");
  tbody.innerHTML = `<tr><td colspan="9" class="empty-state">Loading...</td></tr>`;
  mobile.innerHTML = "";

  try {
    const data = await apiFetch(`/api/items${buildQuery(getFilterParams(page))}`);
    const items = data.items || [];

    if (!items.length) {
      tbody.innerHTML = `<tr><td colspan="9" class="empty-state">No components match your filters.</td></tr>`;
      mobile.innerHTML = `<div class="empty-state">No components match your filters.</div>`;
    } else {
      tbody.innerHTML = items
        .map(
          (it) => `
        <tr class="clickable" data-item-id="${it.id}">
          <td class="mono"><strong>${escapeHtml(it.item_code)}</strong></td>
          <td>${escapeHtml(it.category_path)}</td>
          <td>${escapeHtml(it.model)}</td>
          <td>${escapeHtml(it.size || "—")}</td>
          <td>${escapeHtml(it.mounting_type || "—")}</td>
          <td>${escapeHtml(it.location)}</td>
          <td class="text-right">${stockBadge(it.quantity)}</td>
          <td class="text-right num">${fmtCost(it.weighted_avg_cost, "Unknown")}</td>
          <td class="text-right num">${fmtCost(it.last_purchase_cost, "Unknown")}</td>
        </tr>`
        )
        .join("");

      mobile.innerHTML = items
        .map(
          (it) => `
        <div class="mobile-item-card" data-item-id="${it.id}" style="cursor:pointer;">
          <div class="mobile-item-head">
            <div>
              <strong class="mono">${escapeHtml(it.item_code)}</strong>
              <div style="font-weight:600;">${escapeHtml(it.model)}</div>
              <div class="text-muted" style="font-size:0.78rem;">${escapeHtml(it.category_path)}</div>
            </div>
            ${stockBadge(it.quantity)}
          </div>
          <div class="mobile-item-meta">
            <div><span class="text-muted">Location:</span> ${escapeHtml(it.location)}</div>
            <div><span class="text-muted">Mount/Size:</span> ${escapeHtml(it.mounting_type || "—")} / ${escapeHtml(it.size || "—")}</div>
            <div><span class="text-muted">WAC:</span> <span class="num">${fmtCost(it.weighted_avg_cost, "Unknown")}</span></div>
            <div><span class="text-muted">LPC:</span> <span class="num">${fmtCost(it.last_purchase_cost, "Unknown")}</span></div>
          </div>
        </div>`
        )
        .join("");

      document.querySelectorAll("#dash-items-tbody tr[data-item-id], #dash-items-mobile [data-item-id]").forEach((row) => {
        row.addEventListener("click", () => openItemDetailModal(Number(row.dataset.itemId)));
      });
    }

    renderPagination(
      document.getElementById("dash-pagination"),
      data.page,
      data.total_pages,
      data.total,
      (nextPage) => loadInventoryTable(nextPage)
    );
  } catch (err) {
    toast(err.message, "error");
  }
}

document.addEventListener("DOMContentLoaded", async () => {
  const toggleBtn = document.getElementById("dash-filter-toggle");
  const filterPanel = document.getElementById("dash-filters");
  if (toggleBtn && filterPanel) {
    toggleBtn.addEventListener("click", () => filterPanel.classList.toggle("open"));
  }

  try {
    const [dashData, catData] = await Promise.all([
      apiFetch("/api/dashboard/summary"),
      apiFetch("/api/categories"),
    ]);
    renderKpis(dashData.metrics);
    renderRecentMovements(dashData.recent_movements || []);
    renderRecentItems(dashData.recent_items || []);
    populateCategorySelects(
      document.getElementById("d-parent-cat"),
      document.getElementById("d-sub-cat"),
      catData.categories || [],
      true
    );
  } catch (err) {
    toast(err.message, "error");
  }

  document.getElementById("d-apply-btn").addEventListener("click", () => loadInventoryTable(1));
  document.getElementById("d-search").addEventListener("keydown", (e) => {
    if (e.key === "Enter") loadInventoryTable(1);
  });
  document.getElementById("d-reset-btn").addEventListener("click", () => {
    document.getElementById("d-search").value = "";
    document.getElementById("d-parent-cat").value = "";
    document.getElementById("d-parent-cat").dispatchEvent(new Event("change"));
    document.getElementById("d-mounting").value = "";
    document.getElementById("d-location").value = "";
    document.getElementById("d-zero").checked = false;
    loadInventoryTable(1);
  });

  loadInventoryTable(1);
});
