import { apiFetch, buildQuery } from "../api.js";
import { openCategoryModal, openItemModal } from "../modals.js";
import {
  escapeHtml,
  fmtPriceHtml,
  fmtPriceInline,
  fmtQty,
  openModal,
  populateCategorySelects,
  rialToTomanDisplay,
  stockBadge,
  toast,
  translateServerError,
  txTypeLabel,
} from "../ui.js";

const cart = new Map();
let allCategories = [];

const catalogMap = new Map();
let catalogItems = [];
let catalogPage = 1;
let catalogTotalPages = 1;
let catalogTotal = 0;
let isLoadingCatalog = false;

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
  if (mobileType) mobileType.textContent = txTypeLabel(txType);

  if (txType === "PURCHASE_IN") {
    hint.textContent =
      "وارد کردن قیمت واحد (به ریال) برای هر قلم الزامی است. معادل تومان در کادر زیر آن نمایش داده می‌شود و قیمت میانگین و آخرین قیمت خرید به‌روزرسانی می‌شوند.";
  } else if (txType === "OPENING") {
    hint.textContent =
      "وارد کردن قیمت واحد (به ریال) اختیاری است. در صورت ورود، قیمت میانگین و آخرین قیمت خرید مقداردهی می‌شوند.";
  } else if (txType === "ADJUSTMENT_IN") {
    hint.textContent =
      "وارد کردن قیمت واحد (به ریال) اختیاری است. در صورت خالی بودن، اسنپ‌شات از قیمت میانگین فعلی استفاده می‌کند.";
  } else {
    hint.textContent =
      "تراکنش خروجی: ورود قیمت غیرفعال است و هزینه واحد از قیمت میانگین فعلی (به ریال) محاسبه می‌شود.";
  }
}

function addToCart(item, qtyToAdd) {
  const qty = parseInt(qtyToAdd, 10);
  if (!Number.isInteger(qty) || qty <= 0) {
    toast("تعداد باید یک عدد صحیح مثبت باشد.", "warning");
    return;
  }

  if (cart.has(item.id)) {
    const existing = cart.get(item.id);
    existing.item = item;
    existing.quantity += qty;
    toast(`تعداد ${item.item_code} در سبد به ${existing.quantity} افزایش یافت.`, "info");
  } else {
    cart.set(item.id, {
      item,
      quantity: qty,
      price: "",
      description: "",
    });
    toast(`${item.item_code} (${qty} عدد) به سبد اضافه شد.`, "success");
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
    box.innerHTML = `<div class="empty-state" style="padding:20px 10px;">سبد خالی است. قطعات را از فهرست اضافه کنید.</div>`;
    return;
  }

  box.innerHTML = Array.from(cart.values())
    .map(({ item, quantity, price, description }) => {
      const overStock = outgoing && quantity > item.quantity;
      const tomanText = rialToTomanDisplay(price);
      return `
      <div class="cart-item" data-cart-id="${item.id}">
        <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;">
          <div style="min-width:0;">
            <strong class="mono">${escapeHtml(item.item_code)}</strong>
            ${item.model ? `<span class="text-secondary"> — ${escapeHtml(item.model)}</span>` : ""}
            <div class="text-muted" style="font-size:0.78rem;">
              موجودی: ${stockBadge(item.quantity)} • محل: ${escapeHtml(item.location)}
            </div>
          </div>
          <button type="button" class="btn btn-sm btn-ghost" data-remove="${item.id}" aria-label="حذف">✕</button>
        </div>

        ${
          overStock
            ? `<div class="badge badge-danger" style="align-self:flex-start;">بیشتر از موجودی انبار (موجود: ${fmtQty(item.quantity)})</div>`
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
              ? `<div style="flex:1;min-width:145px;display:flex;flex-direction:column;gap:4px;">
                   <div class="input-unit-group">
                     <input
                       type="number"
                       min="0"
                       step="1"
                       class="input ltr"
                       style="min-height:36px;"
                       placeholder="${priceReq ? "قیمت واحد (ریال) *" : "قیمت (ریال - اختیاری)"}"
                       value="${escapeHtml(price)}"
                       data-price="${item.id}"
                     >
                     <span class="input-unit">ریال</span>
                   </div>
                   <input
                     type="text"
                     readonly
                     tabindex="-1"
                     class="input price-toman-box"
                     placeholder="معادل به تومان..."
                     value="${escapeHtml(tomanText)}"
                     data-toman-preview="${item.id}"
                   >
                 </div>`
              : `<div class="text-muted" style="font-size:0.8rem;">قیمت میانگین: <span class="num">${fmtPriceInline(item.weighted_avg_cost, "نامشخص")}</span></div>`
          }
        </div>

        <input
          type="text"
          class="input"
          style="min-height:34px;font-size:0.84rem;"
          placeholder="یادداشت این ردیف (اختیاری)"
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
      const id = Number(inp.dataset.price);
      const entry = cart.get(id);
      if (entry) entry.price = inp.value;
      const preview = box.querySelector(`[data-toman-preview="${id}"]`);
      if (preview) {
        preview.value = rialToTomanDisplay(inp.value);
      }
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

  if (priceReq) {
    for (const { item, price } of cart.values()) {
      if (price === "" || price === null || Number.isNaN(Number(price)) || Number(price) < 0) {
        toast(`برای ثبت خرید (${item.item_code}) وارد کردن قیمت واحد به ریال الزامی است.`, "warning");
        return;
      }
    }
  }

  const rowsHtml = Array.from(cart.values())
    .map(({ item, quantity, price }) => {
      const warn = outgoing && quantity > item.quantity
        ? `<span class="badge badge-danger">احتمال خطا: موجود ${fmtQty(item.quantity)}</span>`
        : `<span class="badge badge-stock-accent num">موجود: ${fmtQty(item.quantity)}</span>`;
      const unitCostCell = outgoing
        ? fmtPriceHtml(item.weighted_avg_cost, "قیمت میانگین نامشخص")
        : fmtPriceHtml(price, "—");
      return `
      <tr>
        <td class="mono"><strong>${escapeHtml(item.item_code)}</strong></td>
        <td>${escapeHtml(item.model || "—")}</td>
        <td class="text-right num"><strong>${fmtQty(quantity)}</strong></td>
        <td class="text-right num">${unitCostCell}</td>
        <td>${warn}</td>
      </tr>`;
    })
    .join("");

  const modal = openModal({
    title: `بررسی و تایید نهایی: ${txTypeLabel(txType)}`,
    large: true,
    bodyHtml: `
      <div class="alert alert-info" style="margin-bottom:12px;">
        هر قطعه به صورت مستقل توسط پایگاه‌داده بررسی و ثبت می‌شود. اگر موجودی یک قطعه کافی نباشد، سایر قطعات معتبر بدون مشکل ثبت خواهند شد.
      </div>
      <div class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th>کد قطعه</th>
              <th>مدل</th>
              <th class="text-right">تعداد</th>
              <th class="text-right">${outgoing ? "بهای واحد تخمینی (قیمت میانگین)" : "قیمت واحد (ریال / تومان)"}</th>
              <th>کنترل موجودی</th>
            </tr>
          </thead>
          <tbody>${rowsHtml}</tbody>
        </table>
      </div>
      ${sharedNote ? `<p class="text-secondary" style="margin-top:10px;"><strong>توضیحات مشترک:</strong> ${escapeHtml(sharedNote)}</p>` : ""}
    `,
    footerHtml: `
      <button type="button" class="btn" data-modal-close>بازگشت به سبد</button>
      <button type="button" id="confirm-submit-tx" class="btn btn-primary">تایید و ثبت تراکنش‌ها</button>
    `,
  });

  modal.querySelector("#confirm-submit-tx").addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true;
    btn.textContent = "در حال ثبت...";

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

      (res.results || []).forEach((r) => {
        if (r.status === "succeeded" && r.item_id) {
          cart.delete(r.item_id);
        }
      });

      renderCart();
      document.getElementById("tx-cart-panel").classList.remove("open");
      await loadCatalog(true);
      showResultsModal(res);
    } catch (err) {
      toast(err.message, "error");
      btn.disabled = false;
      btn.textContent = "تایید و ثبت تراکنش‌ها";
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
          <td><span class="badge badge-success">ثبت شد</span></td>
          <td class="mono"><strong>${escapeHtml(r.item_code)}</strong></td>
          <td>${escapeHtml(r.model || "—")}</td>
          <td class="text-right num">${fmtQty(tx.quantity)}</td>
          <td class="text-right num ltr">${fmtQty(tx.stock_before)} → <strong>${fmtQty(tx.stock_after)}</strong></td>
          <td class="text-right num">${fmtPriceHtml(tx.unit_cost_snapshot, "نامشخص")}</td>
          <td class="text-secondary">سند شماره ${tx.id} ثبت گردید</td>
        </tr>`;
      }
      return `
      <tr>
        <td><span class="badge badge-danger">ناموفق</span></td>
        <td class="mono"><strong>${escapeHtml(r.item_code || r.item_id || "—")}</strong></td>
        <td>${escapeHtml(r.model || "—")}</td>
        <td class="text-right num">${fmtQty(r.requested_quantity)}</td>
        <td class="text-right num">${r.available_quantity !== undefined && r.available_quantity !== null ? `<span class="badge badge-stock-accent num">موجود: ${fmtQty(r.available_quantity)}</span>` : "—"}</td>
        <td class="text-right">—</td>
        <td class="text-danger">${escapeHtml(translateServerError(r.error))}</td>
      </tr>`;
    })
    .join("");

  openModal({
    title: "گزارش نتیجه ثبت تراکنش‌ها",
    large: true,
    bodyHtml: `
      <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:14px;">
        <span class="badge badge-info">نوع: ${escapeHtml(txTypeLabel(res.transaction_type))}</span>
        <span class="badge badge-success">موفق: ${fmtQty(s.succeeded)}</span>
        <span class="badge ${s.failed > 0 ? "badge-danger" : "badge-neutral"}">ناموفق: ${fmtQty(s.failed)}</span>
      </div>
      ${
        s.failed > 0
          ? `<div class="alert alert-warning" style="margin-bottom:12px;">اقلام ناموفق در سبد باقی ماندند تا بتوانید تعداد آن‌ها را اصلاح و مجدداً ارسال کنید.</div>`
          : `<div class="alert alert-success" style="margin-bottom:12px;">همه اقلام با موفقیت اعتبارسنجی و در موجودی اعمال شدند.</div>`
      }
      <div class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th>وضعیت</th>
              <th>کد قطعه</th>
              <th>مدل</th>
              <th class="text-right">تعداد</th>
              <th class="text-right">تغییر موجودی</th>
              <th class="text-right">بهای واحد</th>
              <th>نتیجه</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    `,
    footerHtml: `
      <a class="btn" href="/transactions">مشاهده تاریخچه تراکنش‌ها</a>
      <button type="button" class="btn btn-primary" data-modal-close>بستن</button>
    `,
  });
}

function getFilterParams(page = 1) {
  const parentCat = document.getElementById("t-parent-cat").value;
  const subCat = document.getElementById("t-sub-cat").value;
  return {
    page,
    page_size: 24,
    search: document.getElementById("t-search").value,
    category_id: subCat || parentCat,
    item_code: document.getElementById("t-item-code").value,
    location: document.getElementById("t-location").value,
    below_threshold: document.getElementById("t-below").value,
    zero_stock: document.getElementById("t-zero").checked ? "true" : "",
    mounting_type: document.getElementById("t-mounting").value,
    size: document.getElementById("t-size").value,
    model: document.getElementById("t-model").value,
    voltage: document.getElementById("t-voltage").value,
    material: document.getElementById("t-material").value,
  };
}

function renderCatalogRow(it) {
  return `
    <div class="cart-item tx-catalog-row" style="flex-direction:row;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:12px;">
      <div style="min-width:200px;flex:1;">
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
          <strong class="mono">${escapeHtml(it.item_code)}</strong>
          ${it.model ? `<strong>${escapeHtml(it.model)}</strong>` : ""}
          ${stockBadge(it.quantity)}
        </div>
        <div class="text-secondary" style="font-size:0.81rem;margin-top:2px;">
          ${escapeHtml(it.category_path)} • محل: <strong>${escapeHtml(it.location)}</strong>
          ${it.size ? ` • سایز: ${escapeHtml(it.size)}` : ""}
          ${it.mounting_type ? ` • ${escapeHtml(it.mounting_type)}` : ""}
          ${it.voltage ? ` • ${escapeHtml(it.voltage)}` : ""}
        </div>
        <div class="text-muted" style="font-size:0.79rem;margin-top:2px;">
          قیمت میانگین: <span class="num">${fmtPriceInline(it.weighted_avg_cost, "نامشخص")}</span>
          • آخرین خرید: <span class="num">${fmtPriceInline(it.last_purchase_cost, "نامشخص")}</span>
        </div>
      </div>

      <div style="display:flex;align-items:center;gap:8px;">
        <input
          type="number"
          min="1"
          step="1"
          value="1"
          class="input num"
          style="width:78px;min-height:36px;text-align:center;"
          data-add-qty="${it.id}"
          aria-label="تعداد برای ${escapeHtml(it.item_code)}"
        >
        <button type="button" class="btn btn-primary btn-sm" data-add-item="${it.id}">+ افزودن</button>
      </div>
    </div>`;
}

function bindCatalogButtons(container) {
  container.querySelectorAll("[data-add-item]").forEach((btn) => {
    if (btn.dataset.bound) return;
    btn.dataset.bound = "1";
    btn.addEventListener("click", () => {
      const id = Number(btn.dataset.addItem);
      const item = catalogMap.get(id);
      const qtyInput = container.querySelector(`[data-add-qty="${id}"]`);
      if (item) addToCart(item, qtyInput ? qtyInput.value : 1);
    });
  });
}

function updateCatalogCounters() {
  const countBadge = document.getElementById("tx-match-count");
  const statusEl = document.getElementById("tx-catalog-status");
  if (countBadge) {
    countBadge.textContent = `${fmtQty(catalogTotal)} مورد منطبق`;
  }
  if (statusEl) {
    statusEl.textContent = `بارگذاری‌شده: ${fmtQty(catalogItems.length)} از ${fmtQty(catalogTotal)} قطعه`;
  }
}

async function loadCatalog(reset = true) {
  if (isLoadingCatalog) return;
  const container = document.getElementById("tx-catalog-list");

  if (reset) {
    catalogPage = 1;
    catalogTotalPages = 1;
    catalogItems = [];
    catalogMap.clear();
    container.scrollTop = 0;
    container.innerHTML = `<div class="empty-state">در حال بارگذاری قطعات...</div>`;
  } else if (catalogPage >= catalogTotalPages) {
    return;
  } else {
    catalogPage += 1;
  }

  isLoadingCatalog = true;
  try {
    const data = await apiFetch(`/api/items${buildQuery(getFilterParams(catalogPage))}`);
    const newItems = data.items || [];
    catalogTotal = data.total || 0;
    catalogTotalPages = data.total_pages || 1;

    newItems.forEach((it) => {
      catalogMap.set(it.id, it);
      catalogItems.push(it);
    });

    if (reset) {
      if (!catalogItems.length) {
        container.innerHTML = `<div class="empty-state">هیچ قطعه‌ای مطابق معیارهای جستجو یافت نشد.</div>`;
      } else {
        container.innerHTML = catalogItems.map(renderCatalogRow).join("");
        bindCatalogButtons(container);
      }
    } else if (newItems.length) {
      container.insertAdjacentHTML("beforeend", newItems.map(renderCatalogRow).join(""));
      bindCatalogButtons(container);
    }

    updateCatalogCounters();
  } catch (err) {
    toast(err.message, "error");
  } finally {
    isLoadingCatalog = false;
  }
}

async function refreshCategories() {
  const catData = await apiFetch("/api/categories");
  allCategories = catData.categories || [];
  populateCategorySelects(
    document.getElementById("t-parent-cat"),
    document.getElementById("t-sub-cat"),
    allCategories,
    true
  );
}

function launchCategoryModal() {
  openCategoryModal({
    allCategories,
    onSaved: async () => {
      await refreshCategories();
    },
  });
}

function launchItemModal() {
  openItemModal({
    allCategories,
    onNeedCategory: () => launchCategoryModal(),
    onSaved: async () => {
      await refreshCategories();
      await loadCatalog(true);
    },
  });
}

document.addEventListener("DOMContentLoaded", async () => {
  const params = new URLSearchParams(window.location.search);
  const preItemCode = params.get("item_code");
  if (preItemCode) {
    document.getElementById("t-item-code").value = preItemCode;
  }

  const moreFiltersBtn = document.getElementById("tx-more-filters-btn");
  const secondaryFilters = document.getElementById("tx-secondary-filters");
  moreFiltersBtn.addEventListener("click", () => {
    const isHidden = secondaryFilters.classList.toggle("hidden");
    moreFiltersBtn.textContent = isHidden ? "نمایش فیلترهای بیشتر" : "بستن فیلترهای بیشتر";
    moreFiltersBtn.setAttribute("aria-expanded", String(!isHidden));
  });

  document.getElementById("tx-btn-new-item").addEventListener("click", launchItemModal);
  document.getElementById("tx-btn-new-category").addEventListener("click", launchCategoryModal);

  const catalogScroll = document.getElementById("tx-catalog-list");
  catalogScroll.addEventListener("scroll", () => {
    if (
      catalogScroll.scrollTop + catalogScroll.clientHeight >= catalogScroll.scrollHeight - 120
    ) {
      loadCatalog(false);
    }
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

  document.getElementById("t-apply-btn").addEventListener("click", () => loadCatalog(true));
  document.getElementById("t-search").addEventListener("keydown", (e) => {
    if (e.key === "Enter") loadCatalog(true);
  });
  document.getElementById("t-reset-btn").addEventListener("click", () => {
    [
      "t-search", "t-item-code", "t-location", "t-below",
      "t-size", "t-model", "t-voltage", "t-material",
    ].forEach((id) => { document.getElementById(id).value = ""; });
    document.getElementById("t-mounting").value = "";
    document.getElementById("t-parent-cat").value = "";
    document.getElementById("t-parent-cat").dispatchEvent(new Event("change"));
    document.getElementById("t-zero").checked = false;
    loadCatalog(true);
  });

  updatePricingHint();
  renderCart();

  try {
    await refreshCategories();
  } catch (err) {
    toast(err.message, "error");
  }

  loadCatalog(true);
});
