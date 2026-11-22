import { apiFetch, buildQuery, downloadExcel } from "../api.js";
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
      <td class="text-muted">${escapeHtml(fmtDate(t.created_at))}</td>
      <td>${txTypeBadge(t.transaction_type)}</td>
      <td class="mono"><strong>${escapeHtml(t.item_code)}</strong></td>
      <td>${escapeHtml(t.model)}</td>
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

async function loadAnalytics() {
  const params = {
    date_from: document.getElementById("r-from").value,
    date_to: document.getElementById("r-to").value,
  };

  try {
    const data = await apiFetch(`/api/reports/analytics${buildQuery(params)}`);
    const txBody = document.getElementById("r-tx-tbody");
    const moves = data.movement_summary || [];
    if (!moves.length) {
      txBody.innerHTML = `<tr><td colspan="5" class="empty-state">تراکنشی در بازه انتخابی ثبت نشده است.</td></tr>`;
    } else {
      txBody.innerHTML = moves
        .map(
          (m) => `
        <tr>
          <td>${txTypeBadge(m.transaction_type)}</td>
          <td class="text-right num">${fmtQty(m.tx_count)}</td>
          <td class="text-right num"><strong>${fmtQty(m.total_units)}</strong></td>
          <td class="text-right num">${fmtPriceHtml(m.known_cost_total)}</td>
          <td>${
            m.cost_complete
              ? `<span class="badge badge-success">کامل</span>`
              : `<span class="badge badge-warning">${fmtQty(m.unknown_cost_tx_count)} بدون قیمت</span>`
          }</td>
        </tr>`
        )
        .join("");
    }
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
    const exSel = document.getElementById("extx-user");
    (userData.users || []).forEach((u) => {
      const label = `${u.first_name} ${u.last_name} (@${u.user_name})`;
      const opt1 = document.createElement("option");
      opt1.value = u.id;
      opt1.textContent = label;
      sel.appendChild(opt1);

      const opt2 = document.createElement("option");
      opt2.value = u.id;
      opt2.textContent = label;
      exSel.appendChild(opt2);
    });
  } catch (err) {
    toast(err.message, "error");
  }

  document.getElementById("h-apply-btn").addEventListener("click", () => loadTransactions(true));
  document.getElementById("h-search").addEventListener("keydown", (e) => {
    if (e.key === "Enter") loadTransactions(true);
  });
  document.getElementById("h-reset-btn").addEventListener("click", () => {
    ["h-search", "h-type", "h-user", "h-from", "h-to"].forEach((id) => {
      document.getElementById(id).value = "";
    });
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
      toast("گزارش اکسل تراکنش‌ها دانلود شد.", "success");
    } catch (err) {
      toast(err.message, "error");
    }
  });

  document.getElementById("r-apply-btn").addEventListener("click", loadAnalytics);
  document.getElementById("r-reset-btn").addEventListener("click", () => {
    document.getElementById("r-from").value = "";
    document.getElementById("r-to").value = "";
    loadAnalytics();
  });

  document.getElementById("r-dl-tx").addEventListener("click", async () => {
    const qs = buildQuery({
      date_from: document.getElementById("r-from").value,
      date_to: document.getElementById("r-to").value,
    });
    try {
      await downloadExcel(`/api/export/transactions${qs}`, {}, "transactions_report.xlsx");
      toast("فایل اکسل گردش‌های بازه انتخابی دانلود شد.", "success");
    } catch (err) {
      toast(err.message, "error");
    }
  });

  document.getElementById("ex-tx-dl-btn").addEventListener("click", async () => {
    const qs = buildQuery({
      date_from: document.getElementById("extx-from").value,
      date_to: document.getElementById("extx-to").value,
      transaction_type: document.getElementById("extx-type").value,
      user_id: document.getElementById("extx-user").value,
      search: document.getElementById("extx-search").value,
    });
    try {
      await downloadExcel(`/api/export/transactions${qs}`, {}, "transactions_report.xlsx");
      toast("گزارش اکسل گردش‌ها دریافت شد.", "success");
    } catch (err) {
      toast(err.message, "error");
    }
  });

  loadTransactions(true);
  loadAnalytics();
});
