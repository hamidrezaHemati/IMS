import { apiFetch, buildQuery, downloadExcel } from "../api.js";
import {
  escapeHtml,
  fmtPriceHtml,
  fmtPriceInline,
  fmtQty,
  openItemDetailModal,
  populateCategorySelects,
  stockBadge,
  toast,
} from "../ui.js";

const PREVIEW_PAGE_SIZE = 24;

let previewPage = 1;
let previewTotalPages = 1;
let previewTotal = 0;
let previewLoaded = 0;
let isLoadingPreview = false;
let previewRequestSeq = 0;

function getInventoryExportFilters() {
  const parentCat = document.getElementById("ex-parent-cat").value;
  const subCat = document.getElementById("ex-sub-cat").value;
  return {
    search: document.getElementById("ex-search").value,
    category_id: subCat || parentCat,
    item_code: document.getElementById("ex-item-code").value,
    model: document.getElementById("ex-model").value,
    size: document.getElementById("ex-size").value,
    mounting_type: document.getElementById("ex-mounting").value,
    material: document.getElementById("ex-material").value,
    voltage: document.getElementById("ex-voltage").value,
    location: document.getElementById("ex-location").value,
    min_quantity: document.getElementById("ex-min-qty").value,
    max_quantity: document.getElementById("ex-max-qty").value,
    below_threshold: document.getElementById("ex-below").value,
    zero_stock: document.getElementById("ex-zero").checked ? "true" : "",
  };
}

function renderPreviewRow(it) {
  const vm = [it.voltage, it.material].filter(Boolean).join(" / ") || "—";
  return `
    <tr class="clickable" data-item-id="${it.id}">
      <td class="mono"><strong>${escapeHtml(it.item_code)}</strong></td>
      <td>${escapeHtml(it.category_path)}</td>
      <td>${escapeHtml(it.model)}</td>
      <td>${escapeHtml(it.size || "—")}</td>
      <td>${escapeHtml(it.mounting_type || "—")}</td>
      <td>${escapeHtml(vm)}</td>
      <td>${escapeHtml(it.location)}</td>
      <td class="text-right">${stockBadge(it.quantity)}</td>
      <td class="text-right num">${fmtPriceHtml(it.weighted_avg_cost, "نامشخص")}</td>
      <td class="text-right num">${fmtPriceHtml(it.last_purchase_cost, "نامشخص")}</td>
    </tr>`;
}

function renderPreviewMobileCard(it) {
  return `
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
    </div>`;
}

function bindPreviewClicks(container) {
  container.querySelectorAll("[data-item-id]").forEach((el) => {
    if (el.dataset.bound) return;
    el.dataset.bound = "1";
    el.addEventListener("click", () => openItemDetailModal(Number(el.dataset.itemId)));
  });
}

function updatePreviewCounters() {
  const matchEl = document.getElementById("ex-match-count");
  const statusEl = document.getElementById("ex-preview-status");
  if (matchEl) {
    matchEl.textContent = `${fmtQty(previewTotal)} مورد منطبق`;
  }
  if (statusEl) {
    statusEl.textContent = `بارگذاری‌شده: ${fmtQty(previewLoaded)} از ${fmtQty(previewTotal)} قطعه`;
  }
}

async function loadPreview(reset = true) {
  if (!reset && (isLoadingPreview || previewPage >= previewTotalPages)) {
    return;
  }

  const seq = ++previewRequestSeq;
  const desktopScroll = document.getElementById("ex-table-scroll");
  const tbody = document.getElementById("ex-preview-tbody");
  const mobile = document.getElementById("ex-preview-mobile");

  if (reset) {
    previewPage = 1;
    previewTotalPages = 1;
    previewTotal = 0;
    previewLoaded = 0;
    if (desktopScroll) desktopScroll.scrollTop = 0;
    if (mobile) mobile.scrollTop = 0;
    tbody.innerHTML = `<tr><td colspan="10" class="empty-state">در حال بارگذاری موجودی...</td></tr>`;
    mobile.innerHTML = "";
  } else {
    previewPage += 1;
  }

  isLoadingPreview = true;
  try {
    const params = {
      ...getInventoryExportFilters(),
      page: previewPage,
      page_size: PREVIEW_PAGE_SIZE,
    };
    const data = await apiFetch(`/api/items${buildQuery(params)}`);
    if (seq !== previewRequestSeq) return;

    const rows = data.items || [];
    previewTotal = data.total || 0;
    previewTotalPages = data.total_pages || 1;
    previewLoaded += rows.length;

    if (reset) {
      if (!rows.length) {
        tbody.innerHTML = `<tr><td colspan="10" class="empty-state">هیچ قطعه‌ای مطابق فیلترهای انتخابی یافت نشد.</td></tr>`;
        mobile.innerHTML = `<div class="empty-state">هیچ قطعه‌ای مطابق فیلترهای انتخابی یافت نشد.</div>`;
      } else {
        tbody.innerHTML = rows.map(renderPreviewRow).join("");
        mobile.innerHTML = rows.map(renderPreviewMobileCard).join("");
        bindPreviewClicks(tbody);
        bindPreviewClicks(mobile);
      }
    } else if (rows.length) {
      tbody.insertAdjacentHTML("beforeend", rows.map(renderPreviewRow).join(""));
      mobile.insertAdjacentHTML("beforeend", rows.map(renderPreviewMobileCard).join(""));
      bindPreviewClicks(tbody);
      bindPreviewClicks(mobile);
    }

    updatePreviewCounters();
  } catch (err) {
    if (seq === previewRequestSeq) {
      toast(err.message, "error");
    }
  } finally {
    if (seq === previewRequestSeq) {
      isLoadingPreview = false;
    }
  }
}

document.addEventListener("DOMContentLoaded", async () => {
  const toggleBtn = document.getElementById("ex-filter-toggle");
  const filterPanel = document.getElementById("ex-filters");
  if (toggleBtn && filterPanel) {
    toggleBtn.addEventListener("click", () => filterPanel.classList.toggle("open"));
  }

  document.getElementById("r-dl-inv").addEventListener("click", async () => {
    try {
      await downloadExcel("/api/export/inventory", {}, "inventory_report.xlsx");
      toast("فایل اکسل کامل موجودی دانلود شد.", "success");
    } catch (err) {
      toast(err.message, "error");
    }
  });

  try {
    const catData = await apiFetch("/api/categories");
    populateCategorySelects(
      document.getElementById("ex-parent-cat"),
      document.getElementById("ex-sub-cat"),
      catData.categories || [],
      true
    );
  } catch (err) {
    toast(err.message, "error");
  }

  // Register change listeners after populateCategorySelects so sub-category resets first
  ["ex-parent-cat", "ex-sub-cat", "ex-mounting", "ex-zero"].forEach((id) => {
    document.getElementById(id).addEventListener("change", () => loadPreview(true));
  });

  document.getElementById("ex-inv-apply-btn").addEventListener("click", () => loadPreview(true));

  document
    .querySelectorAll('#ex-filters input[type="text"], #ex-filters input[type="search"], #ex-filters input[type="number"]')
    .forEach((inp) => {
      inp.addEventListener("keydown", (e) => {
        if (e.key === "Enter") loadPreview(true);
      });
    });

  document.getElementById("ex-inv-dl-btn").addEventListener("click", async () => {
    try {
      const qs = buildQuery(getInventoryExportFilters());
      await downloadExcel(`/api/export/inventory${qs}`, {}, "inventory_report.xlsx");
      toast("فایل اکسل موجودی دریافت شد.", "success");
    } catch (err) {
      toast(err.message, "error");
    }
  });

  document.getElementById("ex-inv-reset-btn").addEventListener("click", () => {
    [
      "ex-search", "ex-item-code", "ex-model", "ex-size", "ex-material",
      "ex-voltage", "ex-location", "ex-min-qty", "ex-max-qty", "ex-below",
    ].forEach((id) => { document.getElementById(id).value = ""; });
    document.getElementById("ex-mounting").value = "";
    document.getElementById("ex-zero").checked = false;
    document.getElementById("ex-parent-cat").value = "";
    document.getElementById("ex-parent-cat").dispatchEvent(new Event("change"));
  });

  const desktopScroll = document.getElementById("ex-table-scroll");
  if (desktopScroll) {
    desktopScroll.addEventListener("scroll", () => {
      if (desktopScroll.scrollTop + desktopScroll.clientHeight >= desktopScroll.scrollHeight - 120) {
        loadPreview(false);
      }
    });
  }

  const mobileScroll = document.getElementById("ex-preview-mobile");
  if (mobileScroll) {
    mobileScroll.addEventListener("scroll", () => {
      if (mobileScroll.scrollTop + mobileScroll.clientHeight >= mobileScroll.scrollHeight - 120) {
        loadPreview(false);
      }
    });
  }

  loadPreview(true);
});
