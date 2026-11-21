import { apiFetch, buildQuery, downloadExcel } from "../api.js";
import { escapeHtml, fmtCost, fmtQty, populateCategorySelects, toast } from "../ui.js";

const IMPORT_FIELDS = [
  { key: "item_code", label: "Item Code", required: true },
  { key: "category", label: "Main Category", required: true },
  { key: "sub_category", label: "Subcategory", required: false },
  { key: "model", label: "Model", required: true },
  { key: "location", label: "Location / Drawer", required: true },
  { key: "quantity", label: "Initial Quantity", required: true },
  { key: "price", label: "Unit Price", required: false },
  { key: "size", label: "Size / Package", required: false },
  { key: "mounting_type", label: "Mounting Type (SMD/DIP)", required: false },
  { key: "voltage", label: "Voltage", required: false },
  { key: "material", label: "Material", required: false },
  { key: "description", label: "Description", required: false },
];

let uploadId = null;
let lastPreview = null;
let rowFilterStatus = "ALL";

function switchExcelTab(tabName) {
  document.querySelectorAll("[data-excel-tab]").forEach((b) => {
    b.classList.toggle("active", b.dataset.excelTab === tabName);
  });
  document.getElementById("excel-tab-import").classList.toggle("hidden", tabName !== "import");
  document.getElementById("excel-tab-export").classList.toggle("hidden", tabName !== "export");
}

function renderMappingControls(info) {
  const sheetSel = document.getElementById("imp-sheet");
  sheetSel.innerHTML = (info.sheet_names || [])
    .map(
      (s) =>
        `<option value="${escapeHtml(s)}" ${s === info.selected_sheet ? "selected" : ""}>${escapeHtml(s)}</option>`
    )
    .join("");

  const headers = info.headers || [];
  const suggested = info.suggested_mapping || {};
  const grid = document.getElementById("imp-mapping-grid");

  grid.innerHTML = IMPORT_FIELDS.map((f) => {
    const opts = [
      `<option value="">${f.required ? "Select column..." : "(Not Mapped)"}</option>`,
      ...headers.map(
        (h) =>
          `<option value="${escapeHtml(h)}" ${suggested[f.key] === h ? "selected" : ""}>${escapeHtml(h)}</option>`
      ),
    ].join("");
    return `
      <div class="field">
        <label for="map-${f.key}">${escapeHtml(f.label)}${f.required ? " *" : ""}</label>
        <select id="map-${f.key}" class="select">${opts}</select>
      </div>`;
  }).join("");
}

function collectMapping() {
  const mapping = {};
  IMPORT_FIELDS.forEach((f) => {
    const val = document.getElementById(`map-${f.key}`).value;
    mapping[f.key] = val || null;
  });
  return mapping;
}

function statusBadge(status) {
  const map = {
    new: "badge-success",
    existing: "badge-info",
    duplicate: "badge-warning",
    invalid: "badge-danger",
    created: "badge-success",
    updated: "badge-info",
    skipped: "badge-neutral",
    failed: "badge-danger",
  };
  return `<span class="badge ${map[status] || "badge-neutral"}">${escapeHtml(status)}</span>`;
}

function renderPreview(preview) {
  lastPreview = preview;
  document.getElementById("imp-preview-section").classList.remove("hidden");
  document.getElementById("imp-result-section").classList.add("hidden");

  document.getElementById("imp-policy-banner").innerHTML = `
    <strong>Import Policy Notice:</strong> ${escapeHtml(preview.policy_explanation)}
  `;

  const s = preview.summary;
  document.getElementById("imp-preview-kpis").innerHTML = `
    <div class="card kpi-card"><span class="kpi-label">Total Rows</span><span class="kpi-value">${fmtQty(s.total_rows)}</span></div>
    <div class="card kpi-card"><span class="kpi-label">New Items Ready</span><span class="kpi-value text-success">${fmtQty(s.valid_new_rows)}</span><span class="kpi-note">${fmtQty(s.zero_quantity_new_rows)} at zero qty</span></div>
    <div class="card kpi-card"><span class="kpi-label">Existing Items</span><span class="kpi-value">${fmtQty(s.existing_rows)}</span><span class="kpi-note">Skipped: ${fmtQty(s.existing_skipped_rows)} • Spec update: ${fmtQty(s.existing_updated_rows)}</span></div>
    <div class="card kpi-card"><span class="kpi-label">Duplicate Codes</span><span class="kpi-value ${s.duplicate_rows > 0 ? "text-warning" : ""}">${fmtQty(s.duplicate_rows)}</span></div>
    <div class="card kpi-card"><span class="kpi-label">Invalid / Missing</span><span class="kpi-value ${s.invalid_rows > 0 ? "text-danger" : ""}">${fmtQty(s.invalid_rows)}</span><span class="kpi-note">${fmtQty(s.missing_category_rows)} missing category</span></div>
    <div class="card kpi-card"><span class="kpi-label">Categories To Create</span><span class="kpi-value">${fmtQty(s.categories_to_create)} / ${fmtQty(s.subcategories_to_create)}</span><span class="kpi-note">Main / Subcategories</span></div>
  `;

  const catPlanBox = document.getElementById("imp-cat-plan");
  if (!preview.category_plan || !preview.category_plan.length) {
    catPlanBox.innerHTML = `<span class="text-muted">No new categories or subcategories to populate from valid rows.</span>`;
  } else {
    catPlanBox.innerHTML = preview.category_plan
      .map((p) => {
        const subs = (p.subcategories || [])
          .map(
            (sub) =>
              `<span class="badge ${sub.status === "new" ? "badge-success" : "badge-neutral"}">${escapeHtml(
                sub.name
              )} (${sub.status})</span>`
          )
          .join(" ");
        return `
        <div style="padding:8px 0;border-bottom:1px solid var(--border-color);display:flex;flex-wrap:wrap;gap:8px;align-items:center;">
          <strong>${escapeHtml(p.name)}</strong>
          <span class="badge ${p.status === "new" ? "badge-info" : "badge-neutral"}">${p.status}</span>
          ${subs ? `<span class="text-muted">→</span> ${subs}` : ""}
        </div>`;
      })
      .join("");
  }

  renderPreviewRows();
  document.getElementById("imp-confirm-btn").disabled = s.will_import_rows === 0;
}

function renderPreviewRows() {
  if (!lastPreview) return;
  const rows = (lastPreview.rows || []).filter(
    (r) => rowFilterStatus === "ALL" || r.status === rowFilterStatus
  );
  const tbody = document.getElementById("imp-preview-tbody");
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="10" class="empty-state">No rows match selected status.</td></tr>`;
    return;
  }

  tbody.innerHTML = rows
    .map((r) => {
      const catText = r.sub_category ? `${r.category || "?"} > ${r.sub_category}` : r.category || "—";
      const msgs = [
        ...(r.errors || []).map((e) => `<div class="text-danger">${escapeHtml(e)}</div>`),
        ...(r.warnings || []).map((w) => `<div class="text-warning">${escapeHtml(w)}</div>`),
      ].join("");
      return `
      <tr>
        <td class="num">${r.row_number}</td>
        <td>${statusBadge(r.status)}</td>
        <td class="mono"><strong>${escapeHtml(r.item_code || "—")}</strong></td>
        <td>${escapeHtml(catText)}</td>
        <td>${escapeHtml(r.model || "—")}</td>
        <td>${escapeHtml(r.mounting_type || "—")} / ${escapeHtml(r.size || "—")}</td>
        <td>${escapeHtml(r.location || "—")}</td>
        <td class="text-right num">${r.quantity !== null && r.quantity !== undefined ? fmtQty(r.quantity) : "—"}</td>
        <td class="text-right num">${fmtCost(r.price, "—")}</td>
        <td style="font-size:0.82rem;">${msgs || `<span class="text-success">Ready</span>`}</td>
      </tr>`;
    })
    .join("");
}

function renderImportResults(res) {
  document.getElementById("imp-preview-section").classList.add("hidden");
  document.getElementById("imp-result-section").classList.remove("hidden");

  const s = res.summary;
  document.getElementById("imp-result-kpis").innerHTML = `
    <div class="card kpi-card"><span class="kpi-label">Total Excel Rows</span><span class="kpi-value">${fmtQty(s.total_rows)}</span></div>
    <div class="card kpi-card"><span class="kpi-label">Imported Items</span><span class="kpi-value text-success">${fmtQty(s.imported_items)}</span><span class="kpi-note">Created: ${fmtQty(s.created_items)} • Updated: ${fmtQty(s.updated_items)}</span></div>
    <div class="card kpi-card"><span class="kpi-label">OPENING Transactions</span><span class="kpi-value">${fmtQty(s.opening_transactions_created)}</span><span class="kpi-note">Populated WAC &amp; LPC</span></div>
    <div class="card kpi-card"><span class="kpi-label">Categories Created</span><span class="kpi-value">${fmtQty(s.categories_created)} / ${fmtQty(s.subcategories_created)}</span><span class="kpi-note">Main / Subcategories</span></div>
    <div class="card kpi-card"><span class="kpi-label">Skipped / Failed</span><span class="kpi-value ${s.failed_rows > 0 ? "text-danger" : ""}">${fmtQty(s.skipped_items)} / ${fmtQty(s.failed_rows)}</span><span class="kpi-note">Duplicates: ${fmtQty(s.duplicate_rows)} • Invalid: ${fmtQty(s.invalid_or_missing_rows)}</span></div>
  `;

  document.getElementById("imp-result-tbody").innerHTML = (res.results || [])
    .map(
      (r) => `
    <tr>
      <td class="num">${r.row_number}</td>
      <td class="mono"><strong>${escapeHtml(r.item_code || "—")}</strong></td>
      <td>${escapeHtml(r.model || "—")}</td>
      <td>${statusBadge(r.status)}</td>
      <td class="text-right num">${r.quantity !== undefined && r.quantity !== null ? fmtQty(r.quantity) : "—"}</td>
      <td class="text-right num">${fmtCost(r.price, "—")}</td>
      <td class="text-secondary">${escapeHtml(r.reason || (r.opening_transaction_id ? `OPENING Tx #${r.opening_transaction_id}` : "Item created (0 stock)"))}</td>
    </tr>`
    )
    .join("");
}

async function handleImportUpload(file) {
  if (!file) return;
  const fd = new FormData();
  fd.append("file", file);
  try {
    const info = await apiFetch("/api/import/upload", { method: "POST", body: fd });
    uploadId = info.upload_id;
    renderMappingControls(info);
    document.getElementById("imp-config-panel").classList.remove("hidden");
    document.getElementById("imp-preview-section").classList.add("hidden");
    document.getElementById("imp-result-section").classList.add("hidden");
    toast(`Uploaded ${file.name} (${info.total_data_rows} data rows).`, "success");
  } catch (err) {
    toast(err.message, "error");
  }
}

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

document.addEventListener("DOMContentLoaded", async () => {
  if (window.location.hash === "#export") {
    switchExcelTab("export");
  }

  document.querySelectorAll("[data-excel-tab]").forEach((btn) => {
    btn.addEventListener("click", () => switchExcelTab(btn.dataset.excelTab));
  });

  // Import listeners
  const dropzone = document.getElementById("imp-dropzone");
  const fileInput = document.getElementById("imp-file-input");
  dropzone.addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", () => handleImportUpload(fileInput.files[0]));
  dropzone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropzone.classList.add("dragover");
  });
  dropzone.addEventListener("dragleave", () => dropzone.classList.remove("dragover"));
  dropzone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropzone.classList.remove("dragover");
    if (e.dataTransfer.files.length) handleImportUpload(e.dataTransfer.files[0]);
  });

  document.getElementById("imp-sheet").addEventListener("change", async (e) => {
    if (!uploadId) return;
    try {
      const info = await apiFetch("/api/import/inspect", {
        method: "POST",
        body: { upload_id: uploadId, sheet_name: e.target.value },
      });
      renderMappingControls(info);
    } catch (err) {
      toast(err.message, "error");
    }
  });

  document.getElementById("imp-preview-btn").addEventListener("click", async () => {
    if (!uploadId) return;
    try {
      const preview = await apiFetch("/api/import/preview", {
        method: "POST",
        body: {
          upload_id: uploadId,
          sheet_name: document.getElementById("imp-sheet").value,
          column_mapping: collectMapping(),
          existing_policy: document.getElementById("imp-policy").value,
        },
      });
      renderPreview(preview);
    } catch (err) {
      toast(err.message, "error");
    }
  });

  document.querySelectorAll("#imp-row-filter .tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("#imp-row-filter .tab-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      rowFilterStatus = btn.dataset.rowStatus;
      renderPreviewRows();
    });
  });

  document.getElementById("imp-confirm-btn").addEventListener("click", async (e) => {
    if (!uploadId) return;
    const btn = e.currentTarget;
    btn.disabled = true;
    btn.textContent = "Importing...";
    try {
      const res = await apiFetch("/api/import/confirm", {
        method: "POST",
        body: {
          upload_id: uploadId,
          sheet_name: document.getElementById("imp-sheet").value,
          column_mapping: collectMapping(),
          existing_policy: document.getElementById("imp-policy").value,
        },
      });
      uploadId = null;
      renderImportResults(res);
      toast(`Import finished: ${res.summary.imported_items} item(s) imported.`, "success");
    } catch (err) {
      toast(err.message, "error");
      btn.disabled = false;
      btn.textContent = "Confirm & Execute Import";
    }
  });

  // Export initialization
  try {
    const [catData, userData] = await Promise.all([
      apiFetch("/api/categories"),
      apiFetch("/api/users"),
    ]);
    populateCategorySelects(
      document.getElementById("ex-parent-cat"),
      document.getElementById("ex-sub-cat"),
      catData.categories || [],
      true
    );
    const userSel = document.getElementById("extx-user");
    (userData.users || []).forEach((u) => {
      const opt = document.createElement("option");
      opt.value = u.id;
      opt.textContent = `${u.first_name} ${u.last_name} (@${u.user_name})`;
      userSel.appendChild(opt);
    });
  } catch (err) {
    toast(err.message, "error");
  }

  document.getElementById("ex-inv-count-btn").addEventListener("click", async () => {
    try {
      const params = { ...getInventoryExportFilters(), page: 1, page_size: 1 };
      const data = await apiFetch(`/api/items${buildQuery(params)}`);
      document.getElementById("ex-inv-count-msg").textContent =
        `${fmtQty(data.total)} item(s) match these export filters.`;
    } catch (err) {
      toast(err.message, "error");
    }
  });

  document.getElementById("ex-inv-dl-btn").addEventListener("click", async () => {
    try {
      const qs = buildQuery(getInventoryExportFilters());
      await downloadExcel(`/api/export/inventory${qs}`, {}, "inventory_report.xlsx");
      toast("Inventory Excel exported.", "success");
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
    document.getElementById("ex-parent-cat").value = "";
    document.getElementById("ex-parent-cat").dispatchEvent(new Event("change"));
    document.getElementById("ex-zero").checked = false;
    document.getElementById("ex-inv-count-msg").textContent = "";
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
      toast("Movement Excel exported.", "success");
    } catch (err) {
      toast(err.message, "error");
    }
  });
});
