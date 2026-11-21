import { apiFetch } from "./api.js";

export function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export function fmtQty(val) {
  if (val === null || val === undefined) return "—";
  return Number(val).toLocaleString("en-US");
}

export function fmtCost(val, fallback = "Unknown") {
  if (val === null || val === undefined || val === "") return fallback;
  const num = Number(val);
  if (Number.isNaN(num)) return fallback;
  return num.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  });
}

export function fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function txTypeBadge(txType) {
  const map = {
    OPENING: "badge-info",
    PURCHASE_IN: "badge-success",
    ADJUSTMENT_IN: "badge-success",
    OUT: "badge-warning",
    ADJUSTMENT_OUT: "badge-danger",
  };
  const cls = map[txType] || "badge-neutral";
  return `<span class="badge ${cls}">${escapeHtml(txType)}</span>`;
}

export function stockBadge(qty) {
  const n = Number(qty || 0);
  if (n === 0) return `<span class="badge badge-danger num">0 (Out)</span>`;
  return `<span class="badge badge-neutral num">${fmtQty(n)}</span>`;
}

export function toast(message, type = "info", duration = 3800) {
  let container = document.getElementById("toast-container");
  if (!container) {
    container = document.createElement("div");
    container.id = "toast-container";
    container.className = "toast-container";
    document.body.appendChild(container);
  }
  const el = document.createElement("div");
  el.className = `toast toast-${type}`;
  el.innerHTML = `<span>${escapeHtml(message)}</span>`;
  container.appendChild(el);
  setTimeout(() => {
    el.remove();
  }, duration);
}

export function renderPagination(container, page, totalPages, total, onPageChange) {
  if (!container) return;
  container.innerHTML = `
    <span class="text-secondary">
      Showing page <strong class="num">${page}</strong> of <strong class="num">${totalPages}</strong>
      (${fmtQty(total)} total records)
    </span>
    <div class="pagination-controls">
      <button class="btn btn-sm" data-page="1" ${page <= 1 ? "disabled" : ""}>First</button>
      <button class="btn btn-sm" data-page="${page - 1}" ${page <= 1 ? "disabled" : ""}>Prev</button>
      <button class="btn btn-sm" data-page="${page + 1}" ${page >= totalPages ? "disabled" : ""}>Next</button>
      <button class="btn btn-sm" data-page="${totalPages}" ${page >= totalPages ? "disabled" : ""}>Last</button>
    </div>
  `;
  container.querySelectorAll("button[data-page]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const target = Number(btn.dataset.page);
      if (target >= 1 && target <= totalPages && target !== page) {
        onPageChange(target);
      }
    });
  });
}

export function populateCategorySelects(parentSelect, childSelect, categories, includeAll = true) {
  if (!parentSelect) return;
  const roots = categories.filter((c) => c.parent_id === null);
  const children = categories.filter((c) => c.parent_id !== null);

  parentSelect.innerHTML = includeAll
    ? `<option value="">All Categories</option>`
    : `<option value="">Select Category...</option>`;

  roots.forEach((cat) => {
    const opt = document.createElement("option");
    opt.value = cat.id;
    opt.textContent = cat.name;
    parentSelect.appendChild(opt);
  });

  const refreshChildren = () => {
    if (!childSelect) return;
    const parentId = parentSelect.value ? Number(parentSelect.value) : null;
    const filtered = parentId
      ? categories.filter((c) => c.root_id === parentId && c.id !== parentId)
      : children;

    childSelect.innerHTML = includeAll
      ? `<option value="">All Subcategories</option>`
      : `<option value="">None (Use Main Category)</option>`;

    filtered.forEach((sub) => {
      const opt = document.createElement("option");
      opt.value = sub.id;
      opt.textContent = parentId ? sub.name : sub.full_path;
      childSelect.appendChild(opt);
    });
  };

  refreshChildren();
  parentSelect.addEventListener("change", refreshChildren);
  return refreshChildren;
}

export function openModal({ title, bodyHtml, footerHtml = "", large = false }) {
  closeModal();
  const backdrop = document.createElement("div");
  backdrop.id = "active-modal-backdrop";
  backdrop.className = "modal-backdrop";
  backdrop.innerHTML = `
    <div class="modal-card ${large ? "modal-lg" : ""}" role="dialog" aria-modal="true">
      <div class="modal-header">
        <h3 class="card-title">${escapeHtml(title)}</h3>
        <button type="button" class="btn btn-sm btn-ghost" data-modal-close aria-label="Close">✕</button>
      </div>
      <div class="modal-body">${bodyHtml}</div>
      ${footerHtml ? `<div class="modal-footer">${footerHtml}</div>` : ""}
    </div>
  `;

  document.body.appendChild(backdrop);
  backdrop.addEventListener("click", (e) => {
    if (e.target === backdrop || e.target.closest("[data-modal-close]")) {
      closeModal();
    }
  });
  return backdrop;
}

export function closeModal() {
  const existing = document.getElementById("active-modal-backdrop");
  if (existing) existing.remove();
}

export async function openItemDetailModal(itemId) {
  const modal = openModal({
    title: "Component Details",
    bodyHtml: `<div class="empty-state">Loading component details...</div>`,
    large: true,
  });

  try {
    const data = await apiFetch(`/api/items/${itemId}`);
    const item = data.item;
    const headerTitle = modal.querySelector(".modal-header .card-title");
    if (headerTitle) {
      headerTitle.textContent = `${item.item_code} — ${item.model}`;
    }

    const txRows = (item.transactions || [])
      .map(
        (t) => `
      <tr>
        <td class="text-muted">${escapeHtml(fmtDate(t.created_at))}</td>
        <td>${txTypeBadge(t.transaction_type)}</td>
        <td class="text-right num"><strong>${fmtQty(t.quantity)}</strong></td>
        <td class="text-right num">${fmtQty(t.stock_before)} → <strong>${fmtQty(t.stock_after)}</strong></td>
        <td class="text-right num">${fmtCost(t.price, "—")}</td>
        <td class="text-right num">${fmtCost(t.unit_cost_snapshot, "Unknown")}</td>
        <td class="text-right num">${fmtCost(t.transaction_cost_snapshot, "Unknown")}</td>
        <td>${escapeHtml(t.user_name)}</td>
        <td class="text-secondary">${escapeHtml(t.description || "—")}</td>
      </tr>
    `
      )
      .join("");

    const body = modal.querySelector(".modal-body");
    body.innerHTML = `
      <div class="spec-grid" style="margin-bottom: 16px;">
        <div class="spec-item">
          <div class="spec-label">Current Stock</div>
          <div class="spec-val num" style="font-size:1.15rem;">${fmtQty(item.quantity)}</div>
        </div>
        <div class="spec-item">
          <div class="spec-label">Weighted Avg Cost</div>
          <div class="spec-val num">${fmtCost(item.weighted_avg_cost, "Unknown")}</div>
        </div>
        <div class="spec-item">
          <div class="spec-label">Last Purchase Cost</div>
          <div class="spec-val num">${fmtCost(item.last_purchase_cost, "Unknown")}</div>
        </div>
        <div class="spec-item">
          <div class="spec-label">WAC Total Value</div>
          <div class="spec-val num">${fmtCost(item.total_wac_value, "Unknown")}</div>
        </div>
        <div class="spec-item">
          <div class="spec-label">Category</div>
          <div class="spec-val">${escapeHtml(item.category_path)}</div>
        </div>
        <div class="spec-item">
          <div class="spec-label">Location</div>
          <div class="spec-val">${escapeHtml(item.location)}</div>
        </div>
        <div class="spec-item">
          <div class="spec-label">Mounting / Size</div>
          <div class="spec-val">${escapeHtml(item.mounting_type || "—")} / ${escapeHtml(item.size || "—")}</div>
        </div>
        <div class="spec-item">
          <div class="spec-label">Voltage / Material</div>
          <div class="spec-val">${escapeHtml(item.voltage || "—")} / ${escapeHtml(item.material || "—")}</div>
        </div>
      </div>

      ${
        item.description
          ? `<div class="alert" style="margin-bottom: 16px;"><strong>Notes:</strong> ${escapeHtml(
              item.description
            )}</div>`
          : ""
      }

      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;gap:8px;flex-wrap:wrap;">
        <h4 style="font-size:0.95rem;">Recent Transaction History</h4>
        <a class="btn btn-sm btn-primary" href="/transactions/new?item_code=${encodeURIComponent(item.item_code)}">
          New Transaction for Item
        </a>
      </div>
      ${
        txRows
          ? `<div class="table-wrap">
               <table class="table">
                 <thead>
                   <tr>
                     <th>Date</th>
                     <th>Type</th>
                     <th class="text-right">Qty</th>
                     <th class="text-right">Stock</th>
                     <th class="text-right">Price</th>
                     <th class="text-right">Unit Cost</th>
                     <th class="text-right">Total Cost</th>
                     <th>User</th>
                     <th>Note</th>
                   </tr>
                 </thead>
                 <tbody>${txRows}</tbody>
               </table>
             </div>`
          : `<div class="empty-state">No transactions recorded for this component yet.</div>`
      }
    `;
  } catch (err) {
    const body = modal.querySelector(".modal-body");
    if (body) {
      body.innerHTML = `<div class="alert alert-danger">${escapeHtml(err.message)}</div>`;
    }
  }
}
