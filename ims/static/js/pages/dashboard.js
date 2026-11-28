import { apiFetch } from "../api.js";
import { getSpecSchema, itemTypeBadge } from "../spec_ui.js";
import {
  escapeHtml,
  fmtDate,
  fmtPriceHtml,
  fmtQty,
  openItemDetailModal,
  stockBadge,
  toast,
  txTypeBadge,
} from "../ui.js";

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
              ${tx.item_type ? itemTypeBadge(tx.item_type, tx.item_type_label_fa) : ""}
              <strong class="mono">${escapeHtml(tx.item_code)}</strong>
              ${
                tx.display_name && tx.display_name !== tx.item_code
                  ? `<span class="text-secondary">${escapeHtml(tx.display_name)}</span>`
                  : ""
              }
            </div>
            <div class="text-muted" style="font-size:0.78rem;margin-top:2px;">
              ${escapeHtml(tx.user_name)} • <span class="ltr">${escapeHtml(fmtDate(tx.created_at_jalali || tx.created_at))}</span>
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
            <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
              ${itemTypeBadge(it.item_type, it.item_type_label_fa)}
              <strong class="mono">${escapeHtml(it.item_code)}</strong>
              ${
                it.display_name && it.display_name !== it.item_code
                  ? `<span class="text-secondary">— ${escapeHtml(it.display_name)}</span>`
                  : ""
              }
            </div>
            <div class="text-muted" style="font-size:0.78rem;margin-top:2px;">${escapeHtml(it.category_path)} • محل: ${escapeHtml(it.location)}</div>
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

document.addEventListener("DOMContentLoaded", async () => {
  try {
    const dashData = await apiFetch("/api/dashboard/summary");
    renderKpis(dashData.metrics);
    renderRecentMovements(dashData.recent_movements || []);
    renderRecentItems(dashData.recent_items || []);
  } catch (err) {
    toast(err.message, "error");
  }
});
