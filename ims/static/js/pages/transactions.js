import { apiFetch, buildQuery, downloadExcel } from "../api.js";
import { itemTypeBadge } from "../spec_ui.js";
import {
  escapeHtml,
  fmtDate,
  fmtPriceHtml,
  fmtPriceInline,
  fmtQty,
  openItemDetailModal,
  toast,
  txTypeBadge,
} from "../ui.js";

const TX_PAGE_SIZE = 30;
const DEFAULT_TX_TYPE_FILTER = "PURCHASE_IN,OUT,ADJUSTMENT_IN,ADJUSTMENT_OUT";

let txPage = 1;
let txTotalPages = 1;
let txTotal = 0;
let txLoaded = 0;
let isLoadingTx = false;
let txRequestSeq = 0;

function getFilters(page = 1) {
  return {
    page,
    page_size: TX_PAGE_SIZE,
    search: document.getElementById("h-search").value,
    transaction_type: document.getElementById("h-type").value,
    user_id: document.getElementById("h-user").value,
    date_from: document.getElementById("h-from").value,
    date_to: document.getElementById("h-to").value,
  };
}

function renderTxDesktopRow(t) {
  return `
    <tr class="clickable" data-item-id="${t.item_id}">
      <td class="text-muted ltr">${escapeHtml(fmtDate(t.created_at_jalali || t.created_at))}</td>
      <td>${txTypeBadge(t.transaction_type)}</td>
      <td class="mono"><strong>${escapeHtml(t.item_code)}</strong></td>
      <td>${t.item_type ? `${itemTypeBadge(t.item_type, t.item_type_label_fa)} ` : ""}${escapeHtml(t.spec_summary || t.display_name || "—")}</td>
      <td>${escapeHtml(t.user_name)}</td>
      <td class="text-right num"><strong>${fmtQty(t.quantity)}</strong></td>
      <td class="text-right num ltr">${fmtQty(t.stock_before)} → <strong>${fmtQty(t.stock_after)}</strong></td>
      <td class="text-right num">${fmtPriceHtml(t.price, "—")}</td>
      <td class="text-right num">${fmtPriceHtml(t.unit_cost_snapshot, "نامشخص")}</td>
      <td class="text-right num">${fmtPriceHtml(t.transaction_cost_snapshot, "نامشخص")}</td>
      <td class="text-secondary">${escapeHtml(t.description || "—")}</td>
    </tr>`;
}

function renderTxMobileCard(t) {
  return `
    <div class="mobile-item-card" data-item-id="${t.item_id}">
      <div class="mobile-item-head">
        <div>
          <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
            ${txTypeBadge(t.transaction_type)}
            ${t.item_type ? itemTypeBadge(t.item_type, t.item_type_label_fa) : ""}
            <strong class="mono">${escapeHtml(t.item_code)}</strong>
          </div>
          <div style="font-size:0.84rem;margin-top:2px;">${escapeHtml(t.spec_summary || t.display_name || "—")}</div>
        </div>
        <div class="text-right num">
          <strong>${fmtQty(t.quantity)}</strong>
          <div class="text-muted ltr" style="font-size:0.78rem;">${fmtQty(t.stock_before)} → ${fmtQty(t.stock_after)}</div>
        </div>
      </div>
      <div class="mobile-item-meta">
        <div><span class="text-muted">کاربر:</span> ${escapeHtml(t.user_name)}</div>
        <div><span class="text-muted">تاریخ:</span> <span class="ltr">${escapeHtml(fmtDate(t.created_at_jalali || t.created_at))}</span></div>
        <div><span class="text-muted">بهای واحد:</span> <span class="num">${fmtPriceInline(t.unit_cost_snapshot, "نامشخص")}</span></div>
        <div><span class="text-muted">جمع ارزش:</span> <span class="num">${fmtPriceInline(t.transaction_cost_snapshot, "نامشخص")}</span></div>
      </div>
      ${t.description ? `<div class="text-secondary" style="font-size:0.82rem;">${escapeHtml(t.description)}</div>` : ""}
    </div>`;
}

function bindTxRowClicks(container) {
  container.querySelectorAll("[data-item-id]").forEach((el) => {
    if (el.dataset.bound) return;
    el.dataset.bound = "1";
    el.addEventListener("click", () => openItemDetailModal(Number(el.dataset.itemId)));
  });
}

function updateTxCounters() {
  const matchBadge = document.getElementById("h-match-count");
  const statusEl = document.getElementById("h-list-status");
  if (matchBadge) {
    matchBadge.textContent = `${fmtQty(txTotal)} مورد منطبق`;
  }
  if (statusEl) {
    statusEl.textContent = `بارگذاری‌شده: ${fmtQty(txLoaded)} از ${fmtQty(txTotal)} تراکنش`;
  }
}

async function loadTransactions(reset = true) {
  if (!reset && (isLoadingTx || txPage >= txTotalPages)) {
    return;
  }

  const seq = ++txRequestSeq;
  const desktopScroll = document.getElementById("h-table-scroll");
  const tbody = document.getElementById("h-tbody");
  const mobile = document.getElementById("h-mobile");

  if (reset) {
    txPage = 1;
    txTotalPages = 1;
    txTotal = 0;
    txLoaded = 0;
    if (desktopScroll) desktopScroll.scrollTop = 0;
    if (mobile) mobile.scrollTop = 0;
    tbody.innerHTML = `<tr><td colspan="11" class="empty-state">در حال بارگذاری...</td></tr>`;
    mobile.innerHTML = "";
  } else {
    txPage += 1;
  }

  isLoadingTx = true;
  try {
    const data = await apiFetch(`/api/transactions${buildQuery(getFilters(txPage))}`);
    if (seq !== txRequestSeq) return;

    const rows = data.transactions || [];
    txTotal = data.total || 0;
    txTotalPages = data.total_pages || 1;
    txLoaded += rows.length;

    if (reset) {
      if (!rows.length) {
        tbody.innerHTML = `<tr><td colspan="11" class="empty-state">تراکنشی مطابق فیلترهای انتخابی یافت نشد.</td></tr>`;
        mobile.innerHTML = `<div class="empty-state">تراکنشی یافت نشد.</div>`;
      } else {
        tbody.innerHTML = rows.map(renderTxDesktopRow).join("");
        mobile.innerHTML = rows.map(renderTxMobileCard).join("");
        bindTxRowClicks(tbody);
        bindTxRowClicks(mobile);
      }
    } else if (rows.length) {
      tbody.insertAdjacentHTML("beforeend", rows.map(renderTxDesktopRow).join(""));
      mobile.insertAdjacentHTML("beforeend", rows.map(renderTxMobileCard).join(""));
      bindTxRowClicks(tbody);
      bindTxRowClicks(mobile);
    }

    updateTxCounters();
  } catch (err) {
    if (seq === txRequestSeq) {
      toast(err.message, "error");
    }
  } finally {
    if (seq === txRequestSeq) {
      isLoadingTx = false;
    }
  }
}

document.addEventListener("DOMContentLoaded", async () => {
  document.getElementById("hist-filter-toggle").addEventListener("click", () => {
    document.getElementById("hist-filters").classList.toggle("open");
  });

  document.getElementById("h-dl-all-btn").addEventListener("click", async () => {
    try {
      await downloadExcel("/api/export/transactions", {}, "transactions_report.xlsx");
      toast("فایل اکسل کامل تراکنش‌ها دانلود شد.", "success");
    } catch (err) {
      toast(err.message, "error");
    }
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

  ["h-type", "h-user", "h-from", "h-to"].forEach((id) => {
    document.getElementById(id).addEventListener("change", () => loadTransactions(true));
  });

  document.getElementById("h-apply-btn").addEventListener("click", () => loadTransactions(true));
  document.getElementById("h-search").addEventListener("keydown", (e) => {
    if (e.key === "Enter") loadTransactions(true);
  });
  document.getElementById("h-reset-btn").addEventListener("click", () => {
    ["h-search", "h-user", "h-from", "h-to"].forEach((id) => {
      document.getElementById(id).value = "";
    });
    document.getElementById("h-type").value = DEFAULT_TX_TYPE_FILTER;
    loadTransactions(true);
  });

  const desktopScroll = document.getElementById("h-table-scroll");
  if (desktopScroll) {
    desktopScroll.addEventListener("scroll", () => {
      if (desktopScroll.scrollTop + desktopScroll.clientHeight >= desktopScroll.scrollHeight - 120) {
        loadTransactions(false);
      }
    });
  }

  const mobileScroll = document.getElementById("h-mobile");
  if (mobileScroll) {
    mobileScroll.addEventListener("scroll", () => {
      if (mobileScroll.scrollTop + mobileScroll.clientHeight >= mobileScroll.scrollHeight - 120) {
        loadTransactions(false);
      }
    });
  }

  document.getElementById("tx-export-btn").addEventListener("click", async () => {
    const f = getFilters(1);
    delete f.page;
    delete f.page_size;
    try {
      await downloadExcel(`/api/export/transactions${buildQuery(f)}`, {}, "transactions_report.xlsx");
      toast("فایل اکسل تراکنش‌های منطبق دانلود شد.", "success");
    } catch (err) {
      toast(err.message, "error");
    }
  });

  loadTransactions(true);
});
