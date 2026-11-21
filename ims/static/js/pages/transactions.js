import { apiFetch, buildQuery, downloadExcel } from "../api.js";
import {
  escapeHtml,
  fmtCost,
  fmtDate,
  fmtQty,
  openItemDetailModal,
  renderPagination,
  toast,
  txTypeBadge,
} from "../ui.js";

function getFilters(page = 1) {
  return {
    page,
    page_size: 25,
    search: document.getElementById("h-search").value,
    transaction_type: document.getElementById("h-type").value,
    user_id: document.getElementById("h-user").value,
    date_from: document.getElementById("h-from").value,
    date_to: document.getElementById("h-to").value,
  };
}

async function loadTransactions(page = 1) {
  const tbody = document.getElementById("h-tbody");
  const mobile = document.getElementById("h-mobile");
  tbody.innerHTML = `<tr><td colspan="11" class="empty-state">در حال بارگذاری...</td></tr>`;
  mobile.innerHTML = "";

  try {
    const data = await apiFetch(`/api/transactions${buildQuery(getFilters(page))}`);
    const rows = data.transactions || [];

    if (!rows.length) {
      tbody.innerHTML = `<tr><td colspan="11" class="empty-state">تراکنشی مطابق فیلترهای انتخابی یافت نشد.</td></tr>`;
      mobile.innerHTML = `<div class="empty-state">تراکنشی یافت نشد.</div>`;
    } else {
      tbody.innerHTML = rows
        .map(
          (t) => `
        <tr class="clickable" data-item-id="${t.item_id}">
          <td class="text-muted">${escapeHtml(fmtDate(t.created_at))}</td>
          <td>${txTypeBadge(t.transaction_type)}</td>
          <td class="mono"><strong>${escapeHtml(t.item_code)}</strong></td>
          <td>${escapeHtml(t.model)}</td>
          <td>${escapeHtml(t.user_name)}</td>
          <td class="text-right num"><strong>${fmtQty(t.quantity)}</strong></td>
          <td class="text-right num ltr">${fmtQty(t.stock_before)} → <strong>${fmtQty(t.stock_after)}</strong></td>
          <td class="text-right num">${fmtCost(t.price, "—")}</td>
          <td class="text-right num">${fmtCost(t.unit_cost_snapshot, "نامشخص")}</td>
          <td class="text-right num">${fmtCost(t.transaction_cost_snapshot, "نامشخص")}</td>
          <td class="text-secondary">${escapeHtml(t.description || "—")}</td>
        </tr>`
        )
        .join("");

      mobile.innerHTML = rows
        .map(
          (t) => `
        <div class="mobile-item-card" data-item-id="${t.item_id}">
          <div class="mobile-item-head">
            <div>
              ${txTypeBadge(t.transaction_type)}
              <strong class="mono">${escapeHtml(t.item_code)}</strong>
              <div>${escapeHtml(t.model)}</div>
            </div>
            <div class="text-right num">
              <strong>${fmtQty(t.quantity)}</strong>
              <div class="text-muted ltr" style="font-size:0.78rem;">${fmtQty(t.stock_before)} → ${fmtQty(t.stock_after)}</div>
            </div>
          </div>
          <div class="mobile-item-meta">
            <div><span class="text-muted">کاربر:</span> ${escapeHtml(t.user_name)}</div>
            <div><span class="text-muted">تاریخ:</span> ${escapeHtml(fmtDate(t.created_at))}</div>
            <div><span class="text-muted">بهای واحد:</span> <span class="num">${fmtCost(t.unit_cost_snapshot, "نامشخص")}</span></div>
            <div><span class="text-muted">جمع ارزش:</span> <span class="num">${fmtCost(t.transaction_cost_snapshot, "نامشخص")}</span></div>
          </div>
          ${t.description ? `<div class="text-secondary" style="font-size:0.82rem;">${escapeHtml(t.description)}</div>` : ""}
        </div>`
        )
        .join("");

      document.querySelectorAll("#h-tbody [data-item-id], #h-mobile [data-item-id]").forEach((el) => {
        el.addEventListener("click", () => openItemDetailModal(Number(el.dataset.itemId)));
      });
    }

    renderPagination(
      document.getElementById("h-pagination"),
      data.page,
      data.total_pages,
      data.total,
      (p) => loadTransactions(p)
    );
  } catch (err) {
    toast(err.message, "error");
  }
}

document.addEventListener("DOMContentLoaded", async () => {
  document.getElementById("hist-filter-toggle").addEventListener("click", () => {
    document.getElementById("hist-filters").classList.toggle("open");
  });

  try {
    const userData = await apiFetch("/api/users");
    const sel = document.getElementById("h-user");
    (userData.users || []).forEach((u) => {
      const opt = document.createElement("option");
      opt.value = u.id;
      opt.textContent = `${u.first_name} ${u.last_name} (@${u.user_name})`;
      sel.appendChild(opt);
    });
  } catch (err) {
    toast(err.message, "error");
  }

  document.getElementById("h-apply-btn").addEventListener("click", () => loadTransactions(1));
  document.getElementById("h-search").addEventListener("keydown", (e) => {
    if (e.key === "Enter") loadTransactions(1);
  });
  document.getElementById("h-reset-btn").addEventListener("click", () => {
    ["h-search", "h-type", "h-user", "h-from", "h-to"].forEach((id) => {
      document.getElementById(id).value = "";
    });
    loadTransactions(1);
  });

  document.getElementById("tx-export-btn").addEventListener("click", async () => {
    const f = getFilters(1);
    delete f.page;
    delete f.page_size;
    try {
      await downloadExcel(`/api/export/transactions${buildQuery(f)}`, {}, "transactions_report.xlsx");
      toast("گزارش اکسل تراکنش‌ها دانلود شد.", "success");
    } catch (err) {
      toast(err.message, "error");
    }
  });

  loadTransactions(1);
});
