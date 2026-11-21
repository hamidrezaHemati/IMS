import { apiFetch, buildQuery } from "../api.js";
import {
  closeModal,
  escapeHtml,
  fmtCost,
  fmtQty,
  openModal,
  populateCategorySelects,
  renderPagination,
  stockBadge,
  toast,
} from "../ui.js";

const cart = new Map(); // item_id -> { item, quantity, price, description }
let currentPage = 1;

function isOutgoingType(txType) {
  return txType === "OUT" || txType === "ADJUSTMENT_OUT";
}

function isPriceRequired(txType) {
  return txType === "PURCHASE_IN";
}

function getTxType() {
  return document.getElementById("cart-tx-type").value;
}

function updatePricingHint() {
  const txType = getTxType();
  const hint = document.getElementById("cart-pricing-hint");
  const mobileType = document.getElementById("mobile-cart-type");
  if (mobileType) mobileType.textContent = txType;

  if (txType === "PURCHASE_IN") {
    hint.textContent = "Unit price is required for every item. Updates weighted average cost & last purchase cost.";
  } else if (txType === "OPENING") {
    hint.textContent = "Unit price is optional. If entered, populates weighted average cost & last purchase cost.";
  } else if (txType === "ADJUSTMENT_IN") {
    hint.textContent = "Unit price is optional. If omitted, snapshot uses current weighted average cost.";
  } else {
    hint.textContent = "Outgoing movement: price is disabled; cost snapshot uses current weighted average cost.";
  }
}

function addToCart(item, qtyToAdd) {
  const qty = parseInt(qtyToAdd, 10);
  if (!Number.isInteger(qty) || qty <= 0) {
    toast("Quantity must be a positive whole number.", "warning");
    return;
  }

  if (cart.has(item.id)) {
    const existing = cart.get(item.id);
    existing.item = item;
    existing.quantity += qty;
    toast(`Updated ${item.item_code} quantity to ${existing.quantity}.`, "info");
  } else {
    cart.set(item.id, {
      item,
      quantity: qty,
      price: "",
      description: "",
    });
    toast(`Added ${item.item_code} (${qty}) to cart.`, "success");
  }
  renderCart();
}

function renderCart() {
  const txType = getTxType();
  const outgoing = isOutgoingType(txType);
  const priceReq = isPriceRequired(txType);

  const count = cart.size;
  document.getElementById("cart-count").textContent = String(count);
  document.getElementById("mobile-cart-count").textContent = String(count);
  document.getElementById("cart-review-btn").disabled = count === 0;

  const box = document.getElementById("cart-items-box");
  if (count === 0) {
    box.innerHTML = `<div class="empty-state" style="padding:20px 10px;">Cart is empty. Add components from the catalog.</div>`;
    return;
  }

  box.innerHTML = Array.from(cart.values())
    .map(({ item, quantity, price, description }) => {
      const overStock = outgoing && quantity > item.quantity;
      return `
      <div class="cart-item" data-cart-id="${item.id}">
        <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;">
          <div style="min-width:0;">
            <strong class="mono">${escapeHtml(item.item_code)}</strong>
            <span class="text-secondary"> — ${escapeHtml(item.model)}</span>
            <div class="text-muted" style="font-size:0.78rem;">
              Available: <strong class="num">${fmtQty(item.quantity)}</strong> • Loc: ${escapeHtml(item.location)}
            </div>
          </div>
          <button type="button" class="btn btn-sm btn-ghost" data-remove="${item.id}" aria-label="Remove">✕</button>
        </div>

        ${
          overStock
            ? `<div class="badge badge-danger" style="align-self:flex-start;">Exceeds available stock (${fmtQty(item.quantity)})</div>`
            : ""
        }

        <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;">
          <div class="stepper">
            <button type="button" data-dec="${item.id}">−</button>
            <input type="number" min="1" step="1" value="${quantity}" data-qty="${item.id}">
            <button type="button" data-inc="${item.id}">+</button>
          </div>
          ${
            !outgoing
              ? `<div style="flex:1;min-width:110px;">
                   <input
                     type="number"
                     min="0"
                     step="0.0001"
                     class="input"
                     style="min-height:36px;"
                     placeholder="${priceReq ? "Unit price *" : "Unit price (opt.)"}"
                     value="${escapeHtml(price)}"
                     data-price="${item.id}"
                   >
                 </div>`
              : `<div class="text-muted" style="font-size:0.8rem;">WAC: <span class="num">${fmtCost(item.weighted_avg_cost, "Unknown")}</span></div>`
          }
        </div>

        <input
          type="text"
          class="input"
          style="min-height:34px;font-size:0.84rem;"
          placeholder="Item note (optional)"
          value="${escapeHtml(description)}"
          data-note="${item.id}"
        >
      </div>`;
    })
    .join("");

  box.querySelectorAll("[data-remove]").forEach((btn) => {
    btn.addEventListener("click", () => {
      cart.delete(Number(btn.dataset.remove));
      renderCart();
    });
  });

  box.querySelectorAll("[data-dec]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const entry = cart.get(Number(btn.dataset.dec));
      if (entry && entry.quantity > 1) {
        entry.quantity -= 1;
        renderCart();
      }
    });
  });

  box.querySelectorAll("[data-inc]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const entry = cart.get(Number(btn.dataset.inc));
      if (entry) {
        entry.quantity += 1;
        renderCart();
      }
    });
  });

  box.querySelectorAll("[data-qty]").forEach((inp) => {
    inp.addEventListener("change", () => {
      const entry = cart.get(Number(inp.dataset.qty));
      const val = parseInt(inp.value, 10);
      if (entry) {
        entry.quantity = Number.isInteger(val) && val > 0 ? val : 1;
        renderCart();
      }
    });
  });

  box.querySelectorAll("[data-price]").forEach((inp) => {
    inp.addEventListener("input", () => {
      const entry = cart.get(Number(inp.dataset.price));
      if (entry) entry.price = inp.value;
    });
  });

  box.querySelectorAll("[data-note]").forEach((inp) => {
    inp.addEventListener("input", () => {
      const entry = cart.get(Number(inp.dataset.note));
      if (entry) entry.description = inp.value;
    });
  });
}

function openReviewModal() {
  const txType = getTxType();
  const outgoing = isOutgoingType(txType);
  const priceReq = isPriceRequired(txType);
  const sharedNote = document.getElementById("cart-shared-note").value.trim();

  // Client-side pre-check for missing required prices on PURCHASE_IN
  if (priceReq) {
    for (const { item, price } of cart.values()) {
      if (price === "" || price === null || Number.isNaN(Number(price)) || Number(price) < 0) {
        toast(`Unit price is required for ${item.item_code} when recording PURCHASE_IN.`, "warning");
        return;
      }
    }
  }

  const rowsHtml = Array.from(cart.values())
    .map(({ item, quantity, price }) => {
      const warn = outgoing && quantity > item.quantity
        ? `<span class="badge badge-danger">May fail: Avail ${fmtQty(item.quantity)}</span>`
        : `<span class="badge badge-neutral">Avail: ${fmtQty(item.quantity)}</span>`;
      return `
      <tr>
        <td class="mono"><strong>${escapeHtml(item.item_code)}</strong></td>
        <td>${escapeHtml(item.model)}</td>
        <td class="text-right num"><strong>${fmtQty(quantity)}</strong></td>
        <td class="text-right num">${outgoing ? fmtCost(item.weighted_avg_cost, "WAC / Unknown") : escapeHtml(price || "—")}</td>
        <td>${warn}</td>
      </tr>`;
    })
    .join("");

  const modal = openModal({
    title: `Review & Confirm ${txType}`,
    large: true,
    bodyHtml: `
      <div class="alert alert-info" style="margin-bottom:12px;">
        Each component will be submitted and validated independently by PostgreSQL.
        If one item lacks sufficient stock, valid items will still be recorded.
      </div>
      <div class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th>Item Code</th>
              <th>Model</th>
              <th class="text-right">Qty</th>
              <th class="text-right">${outgoing ? "Est. Unit Cost (WAC)" : "Unit Price"}</th>
              <th>Stock Check</th>
            </tr>
          </thead>
          <tbody>${rowsHtml}</tbody>
        </table>
      </div>
      ${sharedNote ? `<p class="text-secondary" style="margin-top:10px;"><strong>Note:</strong> ${escapeHtml(sharedNote)}</p>` : ""}
    `,
    footerHtml: `
      <button type="button" class="btn" data-modal-close>Back to Cart</button>
      <button type="button" id="confirm-submit-tx" class="btn btn-primary">Confirm &amp; Submit</button>
    `,
  });

  modal.querySelector("#confirm-submit-tx").addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true;
    btn.textContent = "Submitting...";

    const payload = {
      transaction_type: txType,
      description: sharedNote || null,
      items: Array.from(cart.values()).map(({ item, quantity, price, description }) => ({
        item_id: item.id,
        quantity,
        price: outgoing ? null : (price === "" ? null : price),
        description: description || null,
      })),
    };

    try {
      const res = await apiFetch("/api/transactions/bulk", {
        method: "POST",
        body: payload,
      });

      // Remove succeeded items from cart; retain failed items for adjustment
      (res.results || []).forEach((r) => {
        if (r.status === "succeeded" && r.item_id) {
          cart.delete(r.item_id);
        }
      });

      renderCart();
      document.getElementById("tx-cart-panel").classList.remove("open");
      await loadCatalog(currentPage);
      showResultsModal(res);
    } catch (err) {
      toast(err.message, "error");
      btn.disabled = false;
      btn.textContent = "Confirm & Submit";
    }
  });
}

function showResultsModal(res) {
  const s = res.summary || {};
  const rows = (res.results || [])
    .map((r) => {
      if (r.status === "succeeded") {
        const tx = r.transaction;
        return `
        <tr>
          <td><span class="badge badge-success">Succeeded</span></td>
          <td class="mono"><strong>${escapeHtml(r.item_code)}</strong></td>
          <td>${escapeHtml(r.model)}</td>
          <td class="text-right num">${fmtQty(tx.quantity)}</td>
          <td class="text-right num">${fmtQty(tx.stock_before)} → <strong>${fmtQty(tx.stock_after)}</strong></td>
          <td class="text-right num">${fmtCost(tx.unit_cost_snapshot, "Unknown")}</td>
          <td class="text-secondary">Tx #${tx.id} recorded</td>
        </tr>`;
      }
      return `
      <tr>
        <td><span class="badge badge-danger">Failed</span></td>
        <td class="mono"><strong>${escapeHtml(r.item_code || r.item_id || "—")}</strong></td>
        <td>${escapeHtml(r.model || "—")}</td>
        <td class="text-right num">${fmtQty(r.requested_quantity)}</td>
        <td class="text-right num">${r.available_quantity !== undefined && r.available_quantity !== null ? `Avail: ${fmtQty(r.available_quantity)}` : "—"}</td>
        <td class="text-right">—</td>
        <td class="text-danger">${escapeHtml(r.error)}</td>
      </tr>`;
    })
    .join("");

  openModal({
    title: "Transaction Submission Summary",
    large: true,
    bodyHtml: `
      <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:14px;">
        <span class="badge badge-info">Type: ${escapeHtml(res.transaction_type)}</span>
        <span class="badge badge-success">Succeeded: ${fmtQty(s.succeeded)}</span>
        <span class="badge ${s.failed > 0 ? "badge-danger" : "badge-neutral"}">Failed: ${fmtQty(s.failed)}</span>
      </div>
      ${
        s.failed > 0
          ? `<div class="alert alert-warning" style="margin-bottom:12px;">Failed items were kept in your cart so you can adjust quantities and resubmit.</div>`
          : `<div class="alert alert-success" style="margin-bottom:12px;">All items were validated and applied to inventory.</div>`
      }
      <div class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th>Status</th>
              <th>Item Code</th>
              <th>Model</th>
              <th class="text-right">Qty</th>
              <th class="text-right">Stock Change</th>
              <th class="text-right">Unit Cost</th>
              <th>Result</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    `,
    footerHtml: `
      <a class="btn" href="/transactions">View History</a>
      <button type="button" class="btn btn-primary" data-modal-close>Done</button>
    `,
  });
}

function getFilterParams(page = 1) {
  const parentCat = document.getElementById("t-parent-cat").value;
  const subCat = document.getElementById("t-sub-cat").value;
  return {
    page,
    page_size: 12,
    search: document.getElementById("t-search").value,
    category_id: subCat || parentCat,
    mounting_type: document.getElementById("t-mounting").value,
    item_code: document.getElementById("t-item-code").value,
    model: document.getElementById("t-model").value,
    size: document.getElementById("t-size").value,
    material: document.getElementById("t-material").value,
    voltage: document.getElementById("t-voltage").value,
    location: document.getElementById("t-location").value,
    description: document.getElementById("t-desc").value,
    min_quantity: document.getElementById("t-min-qty").value,
    max_quantity: document.getElementById("t-max-qty").value,
    below_threshold: document.getElementById("t-below").value,
    min_wac: document.getElementById("t-min-wac").value,
    max_wac: document.getElementById("t-max-wac").value,
    min_lpc: document.getElementById("t-min-lpc").value,
    max_lpc: document.getElementById("t-max-lpc").value,
  };
}

async function loadCatalog(page = 1) {
  currentPage = page;
  const container = document.getElementById("tx-catalog-list");
  container.innerHTML = `<div class="empty-state">Loading components...</div>`;

  try {
    const data = await apiFetch(`/api/items${buildQuery(getFilterParams(page))}`);
    const items = data.items || [];

    if (!items.length) {
      container.innerHTML = `<div class="empty-state">No components match your search criteria.</div>`;
    } else {
      container.innerHTML = items
        .map(
          (it) => `
        <div class="cart-item" style="flex-direction:row;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:12px;">
          <div style="min-width:200px;flex:1;">
            <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
              <strong class="mono">${escapeHtml(it.item_code)}</strong>
              <strong>${escapeHtml(it.model)}</strong>
              ${stockBadge(it.quantity)}
            </div>
            <div class="text-secondary" style="font-size:0.82rem;margin-top:3px;">
              ${escapeHtml(it.category_path)} • Loc: <strong>${escapeHtml(it.location)}</strong>
              ${it.size ? ` • Size: ${escapeHtml(it.size)}` : ""}
              ${it.mounting_type ? ` • ${escapeHtml(it.mounting_type)}` : ""}
              ${it.voltage ? ` • ${escapeHtml(it.voltage)}` : ""}
            </div>
            <div class="text-muted" style="font-size:0.8rem;margin-top:2px;">
              WAC: <span class="num">${fmtCost(it.weighted_avg_cost, "Unknown")}</span>
              • Last Purchase: <span class="num">${fmtCost(it.last_purchase_cost, "Unknown")}</span>
            </div>
          </div>

          <div style="display:flex;align-items:center;gap:8px;">
            <input
              type="number"
              min="1"
              step="1"
              value="1"
              class="input num"
              style="width:82px;text-align:center;"
              data-add-qty="${it.id}"
              aria-label="Quantity for ${escapeHtml(it.item_code)}"
            >
            <button type="button" class="btn btn-primary btn-sm" data-add-item="${it.id}">+ Add</button>
          </div>
        </div>`
        )
        .join("");

      container.querySelectorAll("[data-add-item]").forEach((btn) => {
        btn.addEventListener("click", () => {
          const id = Number(btn.dataset.addItem);
          const item = items.find((x) => x.id === id);
          const qtyInput = container.querySelector(`[data-add-qty="${id}"]`);
          addToCart(item, qtyInput ? qtyInput.value : 1);
        });
      });
    }

    renderPagination(
      document.getElementById("tx-catalog-pagination"),
      data.page,
      data.total_pages,
      data.total,
      (p) => loadCatalog(p)
    );
  } catch (err) {
    toast(err.message, "error");
  }
}

document.addEventListener("DOMContentLoaded", async () => {
  const params = new URLSearchParams(window.location.search);
  const preItemCode = params.get("item_code");
  if (preItemCode) {
    document.getElementById("t-item-code").value = preItemCode;
  }

  document.getElementById("tx-filter-toggle").addEventListener("click", () => {
    document.getElementById("tx-adv-filters").classList.toggle("open");
  });

  document.getElementById("mobile-cart-open").addEventListener("click", () => {
    document.getElementById("tx-cart-panel").classList.add("open");
  });
  document.getElementById("mobile-cart-close").addEventListener("click", () => {
    document.getElementById("tx-cart-panel").classList.remove("open");
  });

  document.getElementById("cart-tx-type").addEventListener("change", () => {
    updatePricingHint();
    renderCart();
  });

  document.getElementById("cart-clear-btn").addEventListener("click", () => {
    cart.clear();
    renderCart();
  });

  document.getElementById("cart-review-btn").addEventListener("click", openReviewModal);

  document.getElementById("t-apply-btn").addEventListener("click", () => loadCatalog(1));
  document.getElementById("t-search").addEventListener("keydown", (e) => {
    if (e.key === "Enter") loadCatalog(1);
  });
  document.getElementById("t-reset-btn").addEventListener("click", () => {
    [
      "t-search", "t-item-code", "t-model", "t-size", "t-material",
      "t-voltage", "t-location", "t-desc", "t-min-qty", "t-max-qty",
      "t-below", "t-min-wac", "t-max-wac", "t-min-lpc", "t-max-lpc",
    ].forEach((id) => { document.getElementById(id).value = ""; });
    document.getElementById("t-mounting").value = "";
    document.getElementById("t-parent-cat").value = "";
    document.getElementById("t-parent-cat").dispatchEvent(new Event("change"));
    loadCatalog(1);
  });

  updatePricingHint();
  renderCart();

  try {
    const catData = await apiFetch("/api/categories");
    populateCategorySelects(
      document.getElementById("t-parent-cat"),
      document.getElementById("t-sub-cat"),
      catData.categories || [],
      true
    );
  } catch (err) {
    toast(err.message, "error");
  }

  loadCatalog(1);
});
