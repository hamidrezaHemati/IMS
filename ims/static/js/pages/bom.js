import { apiFetch, downloadExcel } from "../api.js";
import { escapeHtml, fmtCost, fmtQty, toast } from "../ui.js";

let currentUploadId = null;
let lastAnalysis = null;
let currentAvailFilter = "ALL";

function populateMappingSelects(info) {
  const sheetSel = document.getElementById("bom-sheet");
  sheetSel.innerHTML = (info.sheet_names || [])
    .map(
      (s) =>
        `<option value="${escapeHtml(s)}" ${s === info.selected_sheet ? "selected" : ""}>${escapeHtml(s)}</option>`
    )
    .join("");

  const headers = info.headers || [];
  const fillCol = (selectId, selectedVal, optional = false) => {
    const sel = document.getElementById(selectId);
    sel.innerHTML = optional ? `<option value="">(None)</option>` : `<option value="">Select column...</option>`;
    headers.forEach((h) => {
      const opt = document.createElement("option");
      opt.value = h;
      opt.textContent = h;
      if (selectedVal === h) opt.selected = true;
      sel.appendChild(opt);
    });
  };

  const m = info.suggested_mapping || {};
  fillCol("bom-col-code", m.item_code, false);
  fillCol("bom-col-qty", m.quantity, false);
  fillCol("bom-col-name", m.item_name, true);
}

function getSelectedMapping() {
  return {
    sheet_name: document.getElementById("bom-sheet").value,
    column_mapping: {
      item_code: document.getElementById("bom-col-code").value || null,
      quantity: document.getElementById("bom-col-qty").value || null,
      item_name: document.getElementById("bom-col-name").value || null,
    },
  };
}

function availStatusBadge(status) {
  const cls = {
    Available: "badge-success",
    Insufficient: "badge-warning",
    "Out of Stock": "badge-danger",
    Unknown: "badge-danger",
  }[status] || "badge-neutral";
  return `<span class="badge ${cls}">${escapeHtml(status)}</span>`;
}

function renderSummary(analysis) {
  const a = analysis.availability_summary;
  const c = analysis.cost_summary;
  const container = document.getElementById("bom-summary-kpis");

  const wacHtml = c.wac_complete
    ? `<span class="kpi-value">${fmtCost(c.wac_total)}</span><span class="kpi-note text-success">Complete cost across all components</span>`
    : `<span class="kpi-value text-warning">Incomplete</span><span class="kpi-note">Known subtotal: ${fmtCost(c.wac_known_subtotal)} (${fmtQty(c.wac_missing_count)} item(s) missing cost or unknown)</span>`;

  const lpcHtml = c.lpc_complete
    ? `<span class="kpi-value">${fmtCost(c.lpc_total)}</span><span class="kpi-note text-success">Complete cost across all components</span>`
    : `<span class="kpi-value text-warning">Incomplete</span><span class="kpi-note">Known subtotal: ${fmtCost(c.lpc_known_subtotal)} (${fmtQty(c.lpc_missing_count)} item(s) missing cost or unknown)</span>`;

  container.innerHTML = `
    <div class="card kpi-card">
      <span class="kpi-label">Unique Components</span>
      <span class="kpi-value">${fmtQty(a.total_unique_items)}</span>
      <span class="kpi-note">${fmtQty(a.merged_duplicate_rows)} duplicate row(s) merged</span>
    </div>
    <div class="card kpi-card">
      <span class="kpi-label">Availability Breakdown</span>
      <span class="kpi-value text-success">${fmtQty(a.available)} <span class="text-muted" style="font-size:0.9rem;">/ ${fmtQty(a.total_unique_items)}</span></span>
      <span class="kpi-note">Insuff: ${fmtQty(a.insufficient)} • Out: ${fmtQty(a.out_of_stock)} • Unknown: ${fmtQty(a.unknown)}</span>
    </div>
    <div class="card kpi-card">
      <span class="kpi-label">Total BOM (Weighted Avg)</span>
      ${wacHtml}
    </div>
    <div class="card kpi-card">
      <span class="kpi-label">Total BOM (Last Purchase)</span>
      ${lpcHtml}
    </div>
  `;
}

function renderAvailabilityTable() {
  if (!lastAnalysis) return;
  const rows = (lastAnalysis.availability_report || []).filter(
    (r) => currentAvailFilter === "ALL" || r.status === currentAvailFilter
  );
  const tbody = document.getElementById("bom-avail-tbody");
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="8" class="empty-state">No components match this status filter.</td></tr>`;
    return;
  }

  tbody.innerHTML = rows
    .map(
      (r) => `
    <tr>
      <td class="mono"><strong>${escapeHtml(r.item_code)}</strong>${r.merged_rows > 1 ? ` <span class="badge badge-neutral">×${r.merged_rows}</span>` : ""}</td>
      <td>${escapeHtml(r.model || r.bom_item_name || "—")}</td>
      <td>${escapeHtml(r.category_name ? (r.subcategory_name ? `${r.category_name} > ${r.subcategory_name}` : r.category_name) : "—")}</td>
      <td>${escapeHtml(r.location || "—")}</td>
      <td class="text-right num"><strong>${fmtQty(r.required_qty)}</strong></td>
      <td class="text-right num">${r.available_qty !== null ? fmtQty(r.available_qty) : "N/A"}</td>
      <td class="text-right num ${r.shortage > 0 ? "text-danger" : ""}">${r.shortage > 0 ? fmtQty(r.shortage) : "0"}</td>
      <td>${availStatusBadge(r.status)}</td>
    </tr>`
    )
    .join("");
}

function renderInvalidRows(invalidRows) {
  const card = document.getElementById("bom-invalid-card");
  const tbody = document.getElementById("bom-invalid-tbody");
  if (!invalidRows || !invalidRows.length) {
    card.classList.add("hidden");
    return;
  }
  card.classList.remove("hidden");
  tbody.innerHTML = invalidRows
    .map(
      (bad) => `
    <tr>
      <td class="num">${bad.row_number}</td>
      <td class="mono">${escapeHtml(bad.item_code || "—")}</td>
      <td>${escapeHtml(bad.item_name || "—")}</td>
      <td class="mono">${escapeHtml(bad.quantity || "—")}</td>
      <td class="text-danger">${escapeHtml(bad.error)}</td>
    </tr>`
    )
    .join("");
}

function renderCostTable(analysis) {
  const tbody = document.getElementById("bom-cost-tbody");
  const tfoot = document.getElementById("bom-cost-tfoot");
  const rows = analysis.cost_report || [];
  const cs = analysis.cost_summary;

  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="7" class="empty-state">No valid BOM components to calculate.</td></tr>`;
    tfoot.innerHTML = "";
    return;
  }

  tbody.innerHTML = rows
    .map(
      (r) => `
    <tr>
      <td class="mono"><strong>${escapeHtml(r.item_code)}</strong></td>
      <td>${escapeHtml(r.item_name)}${r.is_unknown ? ` <span class="badge badge-danger">Unknown Item</span>` : ""}</td>
      <td class="text-right num"><strong>${fmtQty(r.required_qty)}</strong></td>
      <td class="text-right num">${r.wac_missing ? `<span class="text-warning">Unavailable</span>` : fmtCost(r.weighted_avg_cost)}</td>
      <td class="text-right num">${r.wac_missing ? `<span class="text-warning">Unavailable</span>` : fmtCost(r.wac_line_total)}</td>
      <td class="text-right num">${r.lpc_missing ? `<span class="text-warning">Unavailable</span>` : fmtCost(r.last_purchase_cost)}</td>
      <td class="text-right num">${r.lpc_missing ? `<span class="text-warning">Unavailable</span>` : fmtCost(r.lpc_line_total)}</td>
    </tr>`
    )
    .join("");

  tfoot.innerHTML = `
    <tr style="background:var(--bg-subtle);font-weight:700;">
      <td colspan="4">Grand Total (Weighted Average Cost)</td>
      <td class="text-right num">
        ${
          cs.wac_complete
            ? fmtCost(cs.wac_total)
            : `<span class="text-warning">Incomplete (known: ${fmtCost(cs.wac_known_subtotal)})</span>`
        }
      </td>
      <td></td>
      <td></td>
    </tr>
    <tr style="background:var(--bg-subtle);font-weight:700;">
      <td colspan="4">Grand Total (Last Purchase Cost)</td>
      <td></td>
      <td></td>
      <td class="text-right num">
        ${
          cs.lpc_complete
            ? fmtCost(cs.lpc_total)
            : `<span class="text-warning">Incomplete (known: ${fmtCost(cs.lpc_known_subtotal)})</span>`
        }
      </td>
    </tr>
  `;
}

async function handleFileUpload(file) {
  if (!file) return;
  const fd = new FormData();
  fd.append("file", file);
  try {
    const info = await apiFetch("/api/bom/inspect", { method: "POST", body: fd });
    currentUploadId = info.upload_id;
    populateMappingSelects(info);
    document.getElementById("bom-mapping-panel").classList.remove("hidden");
    toast(`Loaded ${file.name} (${info.total_data_rows} rows). Review mapping and click Analyze.`, "success");
  } catch (err) {
    toast(err.message, "error");
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const dropzone = document.getElementById("bom-dropzone");
  const fileInput = document.getElementById("bom-file-input");

  dropzone.addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", () => handleFileUpload(fileInput.files[0]));
  dropzone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropzone.classList.add("dragover");
  });
  dropzone.addEventListener("dragleave", () => dropzone.classList.remove("dragover"));
  dropzone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropzone.classList.remove("dragover");
    if (e.dataTransfer.files.length) handleFileUpload(e.dataTransfer.files[0]);
  });

  document.getElementById("bom-sheet").addEventListener("change", async (e) => {
    if (!currentUploadId) return;
    try {
      const info = await apiFetch("/api/bom/inspect", {
        method: "POST",
        body: { upload_id: currentUploadId, sheet_name: e.target.value },
      });
      populateMappingSelects(info);
    } catch (err) {
      toast(err.message, "error");
    }
  });

  document.getElementById("bom-calc-btn").addEventListener("click", async () => {
    if (!currentUploadId) return;
    const { sheet_name, column_mapping } = getSelectedMapping();
    try {
      const analysis = await apiFetch("/api/bom/calculate", {
        method: "POST",
        body: { upload_id: currentUploadId, sheet_name, column_mapping },
      });
      lastAnalysis = analysis;
      document.getElementById("bom-results").classList.remove("hidden");
      document.getElementById("bom-export-btn").classList.remove("hidden");
      renderSummary(analysis);
      renderAvailabilityTable();
      renderInvalidRows(analysis.invalid_rows);
      renderCostTable(analysis);
    } catch (err) {
      toast(err.message, "error");
    }
  });

  document.getElementById("bom-export-btn").addEventListener("click", async () => {
    if (!currentUploadId) return;
    const { sheet_name, column_mapping } = getSelectedMapping();
    try {
      await downloadExcel(
        "/api/bom/export",
        {
          method: "POST",
          body: { upload_id: currentUploadId, sheet_name, column_mapping },
        },
        "bom_cost_report.xlsx"
      );
      toast("BOM Excel report downloaded.", "success");
    } catch (err) {
      toast(err.message, "error");
    }
  });

  document.querySelectorAll("#bom-avail-filter .tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("#bom-avail-filter .tab-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      currentAvailFilter = btn.dataset.status;
      renderAvailabilityTable();
    });
  });
});
