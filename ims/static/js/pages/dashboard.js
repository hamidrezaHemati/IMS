import { apiFetch, buildQuery } from "../api.js";
import {
  escapeHtml,
  fmtDate,
  fmtPriceHtml,
  fmtPriceInline,
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
    ? `<span class="kpi-note text-success">کامل برای تمام اقلام موجود</span>`
    : `<span class="kpi-note text-warning">ناقص: قیمت ${fmtQty(m.wac_missing_cost_items)} قلم کالا نامشخص است</span>`;

  const lpcNote = m.lpc_complete
    ? `<span class="kpi-note text-success">کامل برای تمام اقلام موجود</span>`
    : `<span class="kpi-note text-warning">ناقص: قیمت ${fmtQty(m.lpc_missing_cost_items)} قلم کالا نامشخص است</span>`;

  container.innerHTML = `
    <div class="card kpi-card">
      <span class="kpi-label">تعداد اقلام متمایز</span>
      <span class="kpi-value">${fmtQty(m.distinct_items)}</span>
      <span class="kpi-note">${fmtQty(m.zero_stock_count)} قلم با موجودی صفر</span>
    </div>
    <div class="card kpi-card">
      <span class="kpi-label">مجموع واحدهای موجود</span>
      <span class="kpi-value">${fmtQty(m.total_quantity)}</span>
      <span class="kpi-note">مجموع کل موجودی فیزیکی قطعات</span>
    </div>
    <div class="card kpi-card kpi-card-accent">
      <span class="kpi-label">ارزش انبار (قیمت میانگین)</span>
      <div class="kpi-value" style="font-size:1.25rem;">${fmtPriceHtml(m.wac_known_value, "۰ ریال")}</div>
      ${wacNote}
    </div>
    <div class="card kpi-card kpi-card-accent">
      <span class="kpi-label">ارزش انبار (آخرین خرید)</span>
      <div class="kpi-value" style="font-size:1.25rem;">${fmtPriceHtml(m.lpc_known_value, "۰ ریال")}</div>
      ${lpcNote}
    </div>
    <div class="card kpi-card">
      <span class="kpi-label">اقلام ناموجود (صفر)</span>
      <span class="kpi-value ${m.zero_stock_count > 0 ? "text-danger" : ""}">${fmtQty(m.zero_stock_count)}</span>
      <span class="kpi-note">قطعات بدون موجودی در انبار</span>
    </div>
    <div class="card kpi-card">
      <span class="kpi-label">کل تراکنش‌های انبار</span>
      <span class="kpi-value">${fmtQty(m.total_tx_count)}</span>
      <span class="kpi-note"><strong class="num">${fmtQty(m.incoming_tx_count)}</strong> ورود / <strong class="num">${fmtQty(m.outgoing_tx_count)}</strong> خروج</span>
    </div>
  `;
}

function renderRecentMovements(list) {
  const box = document.getElementById("dash-recent-tx");
  if (!list.length) {
    box.innerHTML = `<div class="empty-state">هنوز هیچ تراکنشی در انبار ثبت نشده است.</div>`;
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
            <div class="text-muted ltr" style="font-size:0.78rem;">${fmtQty(tx.stock_before)} → ${fmtQty(tx.stock_after)}</div>
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
    box.innerHTML = `<div class="empty-state">هنوز هیچ قطعه‌ای ثبت نشده است.</div>`;
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
            <div class="text-muted" style="font-size:0.78rem;">${escapeHtml(it.category_path)} • محل: ${escapeHtml(it.location)}</div>
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
  tbody.innerHTML = `<tr><td colspan="9" class="empty-state">در حال بارگذاری...</td></tr>`;
  mobile.innerHTML = "";

  try {
    const data = await apiFetch(`/api/items${buildQuery(getFilterParams(page))}`);
    const items = data.items || [];

    if (!items.length) {
      tbody.innerHTML = `<tr><td colspan="9" class="empty-state">هیچ قطعه‌ای با فیلترهای انتخابی یافت نشد.</td></tr>`;
      mobile.innerHTML = `<div class="empty-state">هیچ قطعه‌ای با فیلترهای انتخابی یافت نشد.</div>`;
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
          <td class="text-right num">${fmtPriceHtml(it.weighted_avg_cost, "نامشخص")}</td>
          <td class="text-right num">${fmtPriceHtml(it.last_purchase_cost, "نامشخص")}</td>
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
            <div><span class="text-muted">محل:</span> ${escapeHtml(it.location)}</div>
            <div><span class="text-muted">نصب/سایز:</span> ${escapeHtml(it.mounting_type || "—")} / ${escapeHtml(it.size || "—")}</div>
            <div><span class="text-muted">قیمت میانگین:</span> <span class="num">${fmtPriceInline(it.weighted_avg_cost, "نامشخص")}</span></div>
            <div><span class="text-muted">آخرین خرید:</span> <span class="num">${fmtPriceInline(it.last_purchase_cost, "نامشخص")}</span></div>
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
