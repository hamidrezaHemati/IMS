import { apiFetch, buildQuery } from "../api.js";
import { openCategoryModal, openItemModal } from "../modals.js";
import {
  escapeHtml,
  fmtPriceHtml,
  fmtPriceInline,
  fmtQty,
  isCurrentUserAdmin,
  openItemDetailModal,
  populateCategorySelects,
  renderPagination,
  stockBadge,
  toast,
} from "../ui.js";

let allCategories = [];
let currentPage = 1;

async function refreshCategories() {
  const data = await apiFetch("/api/categories");
  allCategories = data.categories || [];
  populateCategorySelects(
    document.getElementById("f-parent-cat"),
    document.getElementById("f-sub-cat"),
    allCategories,
    true
  );
  renderCategoryTable();
}

function renderCategoryTable() {
  const tbody = document.getElementById("cat-tbody");
  if (!allCategories.length) {
    tbody.innerHTML = `<tr><td colspan="6" class="empty-state">هنوز هیچ دسته‌بندی ثبت نشده است. فایل اکسل را وارد کنید یا به صورت دستی دسته‌بندی بسازید.</td></tr>`;
    return;
  }

  const canManage = isCurrentUserAdmin();

  tbody.innerHTML = allCategories
    .map((c) => {
      const indent = "&nbsp;&nbsp;&nbsp;&nbsp;".repeat(c.depth || 0);
      const prefix = c.depth > 0 ? "↳ " : "";
      const adminBtns = canManage
        ? `<button type="button" class="btn btn-sm" data-cat-edit="${c.id}">ویرایش</button>
           <button type="button" class="btn btn-sm" data-cat-del="${c.id}">حذف</button>`
        : "";
      return `
      <tr>
        <td>${indent}${prefix}<strong>${escapeHtml(c.name)}</strong></td>
        <td class="text-secondary">${escapeHtml(c.parent_name || "— (دسته اصلی)")}</td>
        <td class="text-right num">${fmtQty(c.direct_item_count)}</td>
        <td class="text-right num">${fmtQty(c.subtree_item_count)}</td>
        <td class="text-secondary">${escapeHtml(c.description || "—")}</td>
        <td class="text-right" style="white-space:nowrap;">
          <button type="button" class="btn btn-sm" data-cat-add-sub="${c.id}">+ زیردسته</button>
          ${adminBtns}
        </td>
      </tr>`;
    })
    .join("");

  tbody.querySelectorAll("[data-cat-add-sub]").forEach((btn) => {
    btn.addEventListener("click", () => launchCategoryModal(null, Number(btn.dataset.catAddSub)));
  });
  tbody.querySelectorAll("[data-cat-edit]").forEach((btn) => {
    const cat = allCategories.find((x) => x.id === Number(btn.dataset.catEdit));
    btn.addEventListener("click", () => launchCategoryModal(cat));
  });
  tbody.querySelectorAll("[data-cat-del]").forEach((btn) => {
    btn.addEventListener("click", () => deleteCategory(Number(btn.dataset.catDel)));
  });
}

function launchCategoryModal(existing = null, defaultParentId = null) {
  openCategoryModal({
    allCategories,
    existing,
    defaultParentId,
    onSaved: async () => {
      await refreshCategories();
      await loadItems(currentPage);
    },
  });
}

function launchItemModal(existing = null) {
  openItemModal({
    allCategories,
    existing,
    onNeedCategory: () => launchCategoryModal(),
    onSaved: async () => {
      await loadItems(existing ? currentPage : 1);
      await refreshCategories();
    },
  });
}

async function deleteCategory(id) {
  const cat = allCategories.find((x) => x.id === id);
  if (!confirm(`آیا از حذف دسته‌بندی "${cat ? cat.full_path : id}" مطمئن هستید؟`)) return;
  try {
    await apiFetch(`/api/categories/${id}`, { method: "DELETE" });
    toast("دسته‌بندی حذف شد.", "success");
    await refreshCategories();
    await loadItems(currentPage);
  } catch (err) {
    toast(err.message, "error");
  }
}

function getFilterParams(page = 1) {
  const parentCat = document.getElementById("f-parent-cat").value;
  const subCat = document.getElementById("f-sub-cat").value;
  return {
    page,
    page_size: 25,
    search: document.getElementById("f-search").value,
    category_id: subCat || parentCat,
    item_code: document.getElementById("f-item-code").value,
    location: document.getElementById("f-location").value,
    below_threshold: document.getElementById("f-below").value,
    zero_stock: document.getElementById("f-zero").checked ? "true" : "",
    model: document.getElementById("f-model").value,
    size: document.getElementById("f-size").value,
    mounting_type: document.getElementById("f-mounting").value,
    voltage: document.getElementById("f-voltage").value,
    material: document.getElementById("f-material").value,
    sort_by: document.getElementById("f-sort").value,
    sort_dir: document.getElementById("f-sort-dir").value,
  };
}

async function loadItems(page = 1) {
  currentPage = page;
  const tbody = document.getElementById("inv-tbody");
  const mobile = document.getElementById("inv-mobile");
  tbody.innerHTML = `<tr><td colspan="10" class="empty-state">در حال بارگذاری...</td></tr>`;
  mobile.innerHTML = "";

  try {
    const data = await apiFetch(`/api/items${buildQuery(getFilterParams(page))}`);
    const items = data.items || [];

    if (!items.length) {
      tbody.innerHTML = `<tr><td colspan="10" class="empty-state">هیچ قطعه‌ای مطابق فیلترها یافت نشد.</td></tr>`;
      mobile.innerHTML = `<div class="empty-state">هیچ قطعه‌ای مطابق فیلترها یافت نشد.</div>`;
    } else {
      tbody.innerHTML = items
        .map(
          (it) => `
        <tr class="clickable" data-row-item="${it.id}">
          <td class="mono"><strong>${escapeHtml(it.item_code)}</strong></td>
          <td>${escapeHtml(it.category_path)}</td>
          <td>${escapeHtml(it.model || "—")}</td>
          <td>${escapeHtml(it.size || "—")} / ${escapeHtml(it.mounting_type || "—")}</td>
          <td>${escapeHtml(it.voltage || "—")} / ${escapeHtml(it.material || "—")}</td>
          <td>${escapeHtml(it.location)}</td>
          <td class="text-right">${stockBadge(it.quantity)}</td>
          <td class="text-right num">${fmtPriceHtml(it.weighted_avg_cost, "نامشخص")}</td>
          <td class="text-right num">${fmtPriceHtml(it.last_purchase_cost, "نامشخص")}</td>
          <td class="text-right" style="white-space:nowrap;">
            <button type="button" class="btn btn-sm" data-edit-item="${it.id}">ویرایش</button>
          </td>
        </tr>`
        )
        .join("");

      mobile.innerHTML = items
        .map(
          (it) => `
        <div class="mobile-item-card" data-row-item="${it.id}">
          <div class="mobile-item-head">
            <div>
              <strong class="mono">${escapeHtml(it.item_code)}</strong>${it.model ? ` — <strong>${escapeHtml(it.model)}</strong>` : ""}
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
          <div style="display:flex;gap:8px;justify-content:flex-end;">
            <button type="button" class="btn btn-sm" data-view-item="${it.id}">جزئیات</button>
            <button type="button" class="btn btn-sm" data-edit-item="${it.id}">ویرایش</button>
          </div>
        </div>`
        )
        .join("");

      const bindItem = (id) => items.find((x) => x.id === id);

      document.querySelectorAll("[data-edit-item]").forEach((btn) => {
        btn.addEventListener("click", (e) => {
          e.stopPropagation();
          launchItemModal(bindItem(Number(btn.dataset.editItem)));
        });
      });

      document.querySelectorAll("[data-view-item]").forEach((btn) => {
        btn.addEventListener("click", (e) => {
          e.stopPropagation();
          openItemDetailModal(Number(btn.dataset.viewItem));
        });
      });

      document.querySelectorAll("#inv-tbody tr[data-row-item]").forEach((row) => {
        row.addEventListener("click", () => openItemDetailModal(Number(row.dataset.rowItem)));
      });
    }

    renderPagination(
      document.getElementById("inv-pagination"),
      data.page,
      data.total_pages,
      data.total,
      (p) => loadItems(p)
    );
  } catch (err) {
    toast(err.message, "error");
  }
}

document.addEventListener("DOMContentLoaded", async () => {
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      const target = btn.dataset.tab;
      document.getElementById("tab-items").classList.toggle("hidden", target !== "items");
      document.getElementById("tab-categories").classList.toggle("hidden", target !== "categories");
    });
  });

  const moreBtn = document.getElementById("inv-more-filters-btn");
  const secFilters = document.getElementById("inv-secondary-filters");
  moreBtn.addEventListener("click", () => {
    const isHidden = secFilters.classList.toggle("hidden");
    moreBtn.textContent = isHidden ? "نمایش فیلترهای بیشتر" : "بستن فیلترهای بیشتر";
    moreBtn.setAttribute("aria-expanded", String(!isHidden));
  });

  document.getElementById("btn-new-item").addEventListener("click", () => launchItemModal());
  document.getElementById("btn-new-category").addEventListener("click", () => launchCategoryModal());
  document.getElementById("btn-cat-add-inline").addEventListener("click", () => launchCategoryModal());

  document.getElementById("inv-apply-btn").addEventListener("click", () => loadItems(1));
  document.getElementById("f-search").addEventListener("keydown", (e) => {
    if (e.key === "Enter") loadItems(1);
  });
  document.getElementById("inv-reset-btn").addEventListener("click", () => {
    [
      "f-search", "f-item-code", "f-location", "f-below",
      "f-model", "f-size", "f-voltage", "f-material",
    ].forEach((id) => { document.getElementById(id).value = ""; });
    document.getElementById("f-mounting").value = "";
    document.getElementById("f-parent-cat").value = "";
    document.getElementById("f-parent-cat").dispatchEvent(new Event("change"));
    document.getElementById("f-zero").checked = false;
    document.getElementById("f-sort").value = "item_code";
    document.getElementById("f-sort-dir").value = "asc";
    loadItems(1);
  });

  try {
    await refreshCategories();
    await loadItems(1);
  } catch (err) {
    toast(err.message, "error");
  }
});
