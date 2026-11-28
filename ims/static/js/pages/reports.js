import { apiFetch, buildQuery, downloadExcel } from "../api.js";
import {
  collectDynamicFilterParams,
  getSpecSchema,
  inferFilterModeFromSelects,
  itemTypeBadge,
  renderDynamicFilterFields,
  resetDynamicFilterFields,
} from "../spec_ui.js";
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

let allCategories = [];
let previewPage = 1;
let previewTotalPages = 1;
let previewTotal = 0;
let previewLoaded = 0;
let isLoadingPreview = false;
let previewRequestSeq = 0;

function populateItemTypeSelect(selectEl, schema) {
  if (!selectEl || !schema || !schema.order) return;
  const current = selectEl.value;
  selectEl.innerHTML = [
    `<option value="">همه انواع</option>`,
    ...schema.order.map((key) => {
      const def = schema.types[key];
      return `<option value="${escapeHtml(key)}">${escapeHtml(def.label_fa)}</option>`;
    }),
  ].join("");
  if (current) selectEl.value = current;
}

function syncExportSpecFilters() {
  const itemTypeVal = document.getElementById("ex-item-type").value;
  const parentCatId = document.getElementById("ex-parent-cat").value;
  const subCatId = document.getElementById("ex-sub-cat").value;
  const filterMode = inferFilterModeFromSelects({
    itemTypeVal,
    parentCatId,
    subCatId,
    categories: allCategories,
  });
  renderDynamicFilterFields(document.getElementById("ex-spec-filters"), filterMode, "ex-dyn");
}

function getInventoryExportFilters() {
  const parentCat = document.getElementById("ex-parent-cat").value;
  const subCat = document.getElementById("ex-sub-cat").value;
  return {
    search: document.getElementById("ex-search").value,
    item_type: document.getElementById("ex-item-type").value,
    category_id: subCat || parentCat,
    item_code: document.getElementById("ex-item-code").value,
    location: document.getElementById("ex-location").value,
    min_quantity: document.getElementById("ex-min-qty").value,
    max_quantity: document.getElementById("ex-max-qty").value,
    below_threshold: document.getElementById("ex-below").value,
    zero_stock: document.getElementById("ex-zero").checked ? "true" : "",
    ...collectDynamicFilterParams(document.getElementById("ex-spec-filters")),
  };
}

function renderPreviewRow(it) {
  return `
    <tr class="clickable" data-item-id="${it.id}">
      <td class="mono"><strong>${escapeHtml(it.item_code)}</strong></td>
      <td>${itemTypeBadge(it.item_type, it.item_type_label_fa)}</td>
      <td>${escapeHtml(it.category_path)}</td>
      <td>${escapeHtml(it.spec_summary || it.display_name || "—")}</td>
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
          <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
            ${itemTypeBadge(it.item_type, it.item_type_label_fa)}
            <strong class="mono">${escapeHtml(it.item_code)}</strong>
          </div>
          ${
            it.display_name && it.display_name !== it.item_code
              ? `<div style="font-weight:600;margin-top:2px;">${escapeHtml(it.display_name)}</div>`
              : ""
          }
          <div class="text-muted" style="font-size:0.78rem;">${escapeHtml(it.category_path)}</div>
        </div>
        ${stockBadge(it.quantity)}
      </div>
      <div class="mobile-item-meta">
        <div><span class="text-muted">محل:</span> ${escapeHtml(it.location)}</div>
        <div><span class="text-muted">مشخصات:</span> ${escapeHtml(it.spec_summary || "—")}</div>
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
    tbody.innerHTML = `<tr><td colspan="8" class="empty-state">در حال بارگذاری موجودی...</td></tr>`;
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
        tbody.innerHTML = `<tr><td colspan="8" class="empty-state">هیچ قطعه‌ای مطابق فیلترهای انتخابی یافت نشد.</td></tr>`;
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
    const [schema, catData] = await Promise.all([getSpecSchema(), apiFetch("/api/categories")]);
    allCategories = catData.categories || [];
    populateItemTypeSelect(document.getElementById("ex-item-type"), schema);
    populateCategorySelects(
      document.getElementById("ex-parent-cat"),
      document.getElementById("ex-sub-cat"),
      allCategories,
      true
    );
  } catch (err) {
    toast(err.message, "error");
  }

  // Register change listeners after populateCategorySelects so sub-category resets first
  ["ex-item-type", "ex-parent-cat", "ex-sub-cat"].forEach((id) => {
    document.getElementById(id).addEventListener("change", () => {
      syncExportSpecFilters();
      loadPreview(true);
    });
  });
  document.getElementById("ex-zero").addEventListener("change", () => loadPreview(true));

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
      "ex-search", "ex-item-code", "ex-location", "ex-min-qty", "ex-max-qty", "ex-below",
    ].forEach((id) => { document.getElementById(id).value = ""; });
    document.getElementById("ex-item-type").value = "";
    document.getElementById("ex-zero").checked = false;
    document.getElementById("ex-parent-cat").value = "";
    document.getElementById("ex-parent-cat").dispatchEvent(new Event("change"));
    resetDynamicFilterFields(document.getElementById("ex-spec-filters"));
    syncExportSpecFilters();
    loadPreview(true);
  });

  syncExportSpecFilters();

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
