import { apiFetch, buildQuery } from "../api.js";
import {
  closeModal,
  escapeHtml,
  fmtCost,
  fmtQty,
  openItemDetailModal,
  openModal,
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
    tbody.innerHTML = `<tr><td colspan="6" class="empty-state">No categories created yet. Import an Excel file or add one manually.</td></tr>`;
    return;
  }

  tbody.innerHTML = allCategories
    .map((c) => {
      const indent = "&nbsp;&nbsp;&nbsp;&nbsp;".repeat(c.depth || 0);
      const prefix = c.depth > 0 ? "↳ " : "";
      return `
      <tr>
        <td>${indent}${prefix}<strong>${escapeHtml(c.name)}</strong></td>
        <td class="text-secondary">${escapeHtml(c.parent_name || "— (Main)")}</td>
        <td class="text-right num">${fmtQty(c.direct_item_count)}</td>
        <td class="text-right num">${fmtQty(c.subtree_item_count)}</td>
        <td class="text-secondary">${escapeHtml(c.description || "—")}</td>
        <td class="text-right" style="white-space:nowrap;">
          <button type="button" class="btn btn-sm" data-cat-add-sub="${c.id}">+ Sub</button>
          <button type="button" class="btn btn-sm" data-cat-edit="${c.id}">Edit</button>
          <button type="button" class="btn btn-sm" data-cat-del="${c.id}">Delete</button>
        </td>
      </tr>`;
    })
    .join("");

  tbody.querySelectorAll("[data-cat-add-sub]").forEach((btn) => {
    btn.addEventListener("click", () => openCategoryModal(null, Number(btn.dataset.catAddSub)));
  });
  tbody.querySelectorAll("[data-cat-edit]").forEach((btn) => {
    const cat = allCategories.find((x) => x.id === Number(btn.dataset.catEdit));
    btn.addEventListener("click", () => openCategoryModal(cat));
  });
  tbody.querySelectorAll("[data-cat-del]").forEach((btn) => {
    btn.addEventListener("click", () => deleteCategory(Number(btn.dataset.catDel)));
  });
}

async function deleteCategory(id) {
  const cat = allCategories.find((x) => x.id === id);
  if (!confirm(`Delete category "${cat ? cat.full_path : id}"?`)) return;
  try {
    await apiFetch(`/api/categories/${id}`, { method: "DELETE" });
    toast("Category deleted.", "success");
    await refreshCategories();
    await loadItems(currentPage);
  } catch (err) {
    toast(err.message, "error");
  }
}

function openCategoryModal(existing = null, defaultParentId = null) {
  const selectedParent = existing ? existing.parent_id : defaultParentId;
  const parentOptions = [
    `<option value="">None (Main / Top-Level Category)</option>`,
    ...allCategories
      .filter((c) => !existing || c.id !== existing.id)
      .map(
        (c) =>
          `<option value="${c.id}" ${selectedParent === c.id ? "selected" : ""}>${escapeHtml(
            c.full_path
          )}</option>`
      ),
  ].join("");

  const modal = openModal({
    title: existing ? "Edit Category" : "New Category",
    bodyHtml: `
      <form id="cat-modal-form" style="display:flex;flex-direction:column;gap:12px;">
        <div class="field">
          <label for="m-cat-name">Category Name *</label>
          <input id="m-cat-name" class="input" required maxlength="100" value="${escapeHtml(existing ? existing.name : "")}">
        </div>
        <div class="field">
          <label for="m-cat-parent">Parent Category</label>
          <select id="m-cat-parent" class="select">${parentOptions}</select>
        </div>
        <div class="field">
          <label for="m-cat-desc">Description</label>
          <textarea id="m-cat-desc" class="textarea">${escapeHtml(existing ? existing.description || "" : "")}</textarea>
        </div>
      </form>
    `,
    footerHtml: `
      <button type="button" class="btn" data-modal-close>Cancel</button>
      <button type="submit" form="cat-modal-form" class="btn btn-primary">Save Category</button>
    `,
  });

  modal.querySelector("#cat-modal-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const payload = {
      name: document.getElementById("m-cat-name").value,
      parent_id: document.getElementById("m-cat-parent").value || null,
      description: document.getElementById("m-cat-desc").value,
    };
    try {
      if (existing) {
        await apiFetch(`/api/categories/${existing.id}`, { method: "PUT", body: payload });
        toast("Category updated.", "success");
      } else {
        await apiFetch("/api/categories", { method: "POST", body: payload });
        toast("Category created.", "success");
      }
      closeModal();
      await refreshCategories();
      await loadItems(currentPage);
    } catch (err) {
      toast(err.message, "error");
    }
  });
}

function openItemModal(existing = null) {
  if (!allCategories.length) {
    toast("Create at least one category before adding items.", "warning");
    openCategoryModal();
    return;
  }

  const catOptions = allCategories
    .map(
      (c) =>
        `<option value="${c.id}" ${existing && existing.category_id === c.id ? "selected" : ""}>${escapeHtml(
          c.full_path
        )}</option>`
    )
    .join("");

  const modal = openModal({
    title: existing ? `Edit Item: ${existing.item_code}` : "Add New Component",
    large: true,
    bodyHtml: `
      <div class="alert alert-info" style="margin-bottom:12px;">
        ${
          existing
            ? "Editing updates component specifications only. Stock quantities and costs can only change through transactions."
            : "Creating a new item initializes an empty inventory record (quantity 0) via PostgreSQL trigger. Record stock via New Transaction or Excel Import."
        }
      </div>
      <form id="item-modal-form" class="form-grid">
        <div class="field">
          <label for="m-item-code">Item Code *</label>
          <input id="m-item-code" class="input" required maxlength="80" value="${escapeHtml(existing ? existing.item_code : "")}">
        </div>
        <div class="field">
          <label for="m-item-cat">Category / Subcategory *</label>
          <select id="m-item-cat" class="select" required>${catOptions}</select>
        </div>
        <div class="field">
          <label for="m-item-model">Model *</label>
          <input id="m-item-model" class="input" required maxlength="150" value="${escapeHtml(existing ? existing.model : "")}">
        </div>
        <div class="field">
          <label for="m-item-location">Location / Drawer *</label>
          <input id="m-item-location" class="input" required maxlength="150" value="${escapeHtml(existing ? existing.location : "")}">
        </div>
        <div class="field">
          <label for="m-item-size">Size / Package</label>
          <input id="m-item-size" class="input" maxlength="50" value="${escapeHtml(existing ? existing.size || "" : "")}">
        </div>
        <div class="field">
          <label for="m-item-mount">Mounting Type</label>
          <select id="m-item-mount" class="select">
            <option value="">Unspecified</option>
            <option value="SMD" ${existing && existing.mounting_type === "SMD" ? "selected" : ""}>SMD</option>
            <option value="DIP" ${existing && existing.mounting_type === "DIP" ? "selected" : ""}>DIP</option>
          </select>
        </div>
        <div class="field">
          <label for="m-item-voltage">Voltage</label>
          <input id="m-item-voltage" class="input" maxlength="80" value="${escapeHtml(existing ? existing.voltage || "" : "")}">
        </div>
        <div class="field">
          <label for="m-item-material">Material</label>
          <input id="m-item-material" class="input" maxlength="100" value="${escapeHtml(existing ? existing.material || "" : "")}">
        </div>
        <div class="field" style="grid-column: 1 / -1;">
          <label for="m-item-desc">Description / Notes</label>
          <textarea id="m-item-desc" class="textarea">${escapeHtml(existing ? existing.description || "" : "")}</textarea>
        </div>
      </form>
    `,
    footerHtml: `
      <button type="button" class="btn" data-modal-close>Cancel</button>
      <button type="submit" form="item-modal-form" class="btn btn-primary">${existing ? "Save Changes" : "Create Item"}</button>
    `,
  });

  modal.querySelector("#item-modal-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const payload = {
      item_code: document.getElementById("m-item-code").value,
      category_id: document.getElementById("m-item-cat").value,
      model: document.getElementById("m-item-model").value,
      location: document.getElementById("m-item-location").value,
      size: document.getElementById("m-item-size").value,
      mounting_type: document.getElementById("m-item-mount").value || null,
      voltage: document.getElementById("m-item-voltage").value,
      material: document.getElementById("m-item-material").value,
      description: document.getElementById("m-item-desc").value,
    };

    try {
      if (existing) {
        await apiFetch(`/api/items/${existing.id}`, { method: "PUT", body: payload });
        toast("Item updated.", "success");
      } else {
        await apiFetch("/api/items", { method: "POST", body: payload });
        toast("Item created with empty inventory record.", "success");
      }
      closeModal();
      await loadItems(existing ? currentPage : 1);
      await refreshCategories();
    } catch (err) {
      toast(err.message, "error");
    }
  });
}

function getFilterParams(page = 1) {
  const parentCat = document.getElementById("f-parent-cat").value;
  const subCat = document.getElementById("f-sub-cat").value;
  return {
    page,
    page_size: 25,
    search: document.getElementById("f-search").value,
    category_id: subCat || parentCat,
    mounting_type: document.getElementById("f-mounting").value,
    item_code: document.getElementById("f-item-code").value,
    model: document.getElementById("f-model").value,
    size: document.getElementById("f-size").value,
    material: document.getElementById("f-material").value,
    voltage: document.getElementById("f-voltage").value,
    location: document.getElementById("f-location").value,
    min_quantity: document.getElementById("f-min-qty").value,
    max_quantity: document.getElementById("f-max-qty").value,
    below_threshold: document.getElementById("f-below").value,
    zero_stock: document.getElementById("f-zero").checked ? "true" : "",
    sort_by: document.getElementById("f-sort").value,
    sort_dir: document.getElementById("f-sort-dir").value,
  };
}

async function loadItems(page = 1) {
  currentPage = page;
  const tbody = document.getElementById("inv-tbody");
  const mobile = document.getElementById("inv-mobile");
  tbody.innerHTML = `<tr><td colspan="10" class="empty-state">Loading...</td></tr>`;
  mobile.innerHTML = "";

  try {
    const data = await apiFetch(`/api/items${buildQuery(getFilterParams(page))}`);
    const items = data.items || [];

    if (!items.length) {
      tbody.innerHTML = `<tr><td colspan="10" class="empty-state">No components match your criteria.</td></tr>`;
      mobile.innerHTML = `<div class="empty-state">No components match your criteria.</div>`;
    } else {
      tbody.innerHTML = items
        .map(
          (it) => `
        <tr class="clickable" data-row-item="${it.id}">
          <td class="mono"><strong>${escapeHtml(it.item_code)}</strong></td>
          <td>${escapeHtml(it.category_path)}</td>
          <td>${escapeHtml(it.model)}</td>
          <td>${escapeHtml(it.size || "—")} / ${escapeHtml(it.mounting_type || "—")}</td>
          <td>${escapeHtml(it.voltage || "—")} / ${escapeHtml(it.material || "—")}</td>
          <td>${escapeHtml(it.location)}</td>
          <td class="text-right">${stockBadge(it.quantity)}</td>
          <td class="text-right num">${fmtCost(it.weighted_avg_cost, "Unknown")}</td>
          <td class="text-right num">${fmtCost(it.last_purchase_cost, "Unknown")}</td>
          <td class="text-right" style="white-space:nowrap;">
            <button type="button" class="btn btn-sm" data-edit-item="${it.id}">Edit</button>
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
              <strong class="mono">${escapeHtml(it.item_code)}</strong> — <strong>${escapeHtml(it.model)}</strong>
              <div class="text-muted" style="font-size:0.78rem;">${escapeHtml(it.category_path)}</div>
            </div>
            ${stockBadge(it.quantity)}
          </div>
          <div class="mobile-item-meta">
            <div><span class="text-muted">Loc:</span> ${escapeHtml(it.location)}</div>
            <div><span class="text-muted">Mount/Size:</span> ${escapeHtml(it.mounting_type || "—")} / ${escapeHtml(it.size || "—")}</div>
            <div><span class="text-muted">WAC:</span> <span class="num">${fmtCost(it.weighted_avg_cost, "Unknown")}</span></div>
            <div><span class="text-muted">LPC:</span> <span class="num">${fmtCost(it.last_purchase_cost, "Unknown")}</span></div>
          </div>
          <div style="display:flex;gap:8px;justify-content:flex-end;">
            <button type="button" class="btn btn-sm" data-view-item="${it.id}">Details</button>
            <button type="button" class="btn btn-sm" data-edit-item="${it.id}">Edit</button>
          </div>
        </div>`
        )
        .join("");

      const bindItem = (id) => items.find((x) => x.id === id);

      document.querySelectorAll("[data-edit-item]").forEach((btn) => {
        btn.addEventListener("click", (e) => {
          e.stopPropagation();
          openItemModal(bindItem(Number(btn.dataset.editItem)));
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
  // Tabs
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      const target = btn.dataset.tab;
      document.getElementById("tab-items").classList.toggle("hidden", target !== "items");
      document.getElementById("tab-categories").classList.toggle("hidden", target !== "categories");
    });
  });

  const toggleBtn = document.getElementById("inv-filter-toggle");
  const advPanel = document.getElementById("inv-adv-filters");
  if (toggleBtn && advPanel) {
    toggleBtn.addEventListener("click", () => advPanel.classList.toggle("open"));
  }

  document.getElementById("btn-new-item").addEventListener("click", () => openItemModal());
  document.getElementById("btn-new-category").addEventListener("click", () => openCategoryModal());
  document.getElementById("btn-cat-add-inline").addEventListener("click", () => openCategoryModal());

  document.getElementById("inv-apply-btn").addEventListener("click", () => loadItems(1));
  document.getElementById("f-search").addEventListener("keydown", (e) => {
    if (e.key === "Enter") loadItems(1);
  });
  document.getElementById("inv-reset-btn").addEventListener("click", () => {
    [
      "f-search", "f-item-code", "f-model", "f-size", "f-material",
      "f-voltage", "f-location", "f-min-qty", "f-max-qty", "f-below",
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
