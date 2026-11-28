import { apiFetch } from "./api.js";
import { formatJalaliDateTime } from "./jalali_datepicker.js";
import { getSpecSchema, itemTypeBadge, renderSpecDetailCards } from "./spec_ui.js";

export function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export function translateServerError(msg) {
  if (!msg) return "خطای نامشخص رخ داد.";
  const text = String(msg);

  const insuffMatch = text.match(/Insufficient stock for item_id (\d+)\. Available: (\d+), requested: (\d+)/i);
  if (insuffMatch) {
    return `موجودی کافی نیست (موجود: ${insuffMatch[2]}، درخواستی: ${insuffMatch[3]}).`;
  }
  if (/Invalid username or password/i.test(text)) {
    return "نام کاربری یا رمز عبور اشتباه است.";
  }
  if (/Current password is incorrect/i.test(text)) {
    return "رمز عبور فعلی نادرست است.";
  }
  if (/username is already taken/i.test(text)) {
    return "این نام کاربری قبلاً ثبت شده است.";
  }
  if (/item with this item code already exists/i.test(text)) {
    return "قطعه دیگری با این کد قطعه قبلاً ثبت شده است.";
  }
  if (/Cannot delete this category because it still has subcategories/i.test(text)) {
    return "امکان حذف این دسته‌بندی وجود ندارد زیرا دارای زیردسته است.";
  }
  if (/Cannot delete or change this category because items are assigned/i.test(text)) {
    return "امکان حذف یا تغییر این دسته‌بندی وجود ندارد زیرا قطعاتی به آن اختصاص یافته‌اند.";
  }
  if (/would create a cycle/i.test(text) || /cannot be its own parent/i.test(text)) {
    return "سلسله‌مراتب دسته‌بندی نامعتبر است: این تغییر باعث ایجاد حلقه می‌شود.";
  }
  if (/already exists under the selected parent/i.test(text)) {
    return "دسته‌بندی با این نام در همین سطح از قبل وجود دارد.";
  }
  if (/Unit price is required for PURCHASE_IN/i.test(text)) {
    return "وارد کردن قیمت واحد برای تراکنش خرید (PURCHASE_IN) الزامی است.";
  }
  if (/Price must not be specified for OUT/i.test(text)) {
    return "برای تراکنش‌های خروج نباید قیمت وارد شود؛ هزینه از قیمت میانگین محاسبه می‌شود.";
  }
  if (/Only \.xlsx Excel workbooks are supported/i.test(text)) {
    return "فقط فایل‌های اکسل با پسوند .xlsx پشتیبانی می‌شوند.";
  }
  if (/Admin access is required to assign the admin role/i.test(text)) {
    return "فقط مدیر سیستم (ادمین) مجاز به اختصاص نقش ادمین به کاربر جدید است.";
  }
  if (/Admin access is required/i.test(text)) {
    return "این عملیات فقط برای مدیر سیستم (ادمین) مجاز است.";
  }
  if (/Selected role does not exist/i.test(text)) {
    return "نقش کاربری انتخاب‌شده یافت نشد.";
  }
  if (/outer diameter .* strictly greater than inner diameter/i.test(text) || /chk_o_ring_outer_gt_inner/i.test(text)) {
    return "قطر خارجی اورینگ باید اکیداً بزرگ‌تر از قطر داخلی آن باشد.";
  }
  if (/valid numeric value in millimeters/i.test(text) || /\(mm\) must be greater than zero/i.test(text) || /\(mm\) is required/i.test(text)) {
    return "ابعاد مکانیکی باید به‌صورت عدد مثبت و بر حسب میلی‌متر (mm) وارد شوند.";
  }
  if (/incompatible specifications/i.test(text) || /not match item category type/i.test(text)) {
    return "مشخصات فنی واردشده با دسته‌بندی انتخابی هم‌خوانی ندارد.";
  }
  if (/Cannot change spec_type/i.test(text)) {
    return "تغییر نوع مشخصات فنی زیردسته‌ای که دارای قطعه است مجاز نیست.";
  }
  if (/already assigned to/i.test(text)) {
    return "این زیردسته به نوع قطعه دیگری اختصاص داده شده است.";
  }
  if (/valid leaf component category/i.test(text)) {
    return "قطعه باید در یکی از زیردسته‌های معتبر (الکترونیک یا مکانیک) ثبت شود.";
  }
  return text;
}

export function isCurrentUserAdmin() {
  return document.body && document.body.dataset.isAdmin === "true";
}

export function roleLabel(roleName) {
  const key = String(roleName || "").toLowerCase();
  if (key === "admin") return "مدیر سیستم";
  if (key === "employee") return "کارمند";
  return roleName || "نامشخص";
}

export function fmtQty(val) {
  if (val === null || val === undefined) return "—";
  return Number(val).toLocaleString("en-US");
}

export function fmtNumber(val) {
  if (val === null || val === undefined || val === "") return "—";
  const num = Number(val);
  if (Number.isNaN(num)) return "—";
  return num.toLocaleString("en-US", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 4,
  });
}

export function fmtCost(val, fallback = "نامشخص") {
  if (val === null || val === undefined || val === "") return fallback;
  const num = Number(val);
  if (Number.isNaN(num)) return fallback;
  return `${fmtNumber(num)} ریال`;
}

export function fmtToman(val, fallback = "نامشخص") {
  if (val === null || val === undefined || val === "") return fallback;
  const num = Number(val);
  if (Number.isNaN(num)) return fallback;
  return `${fmtNumber(num / 10)} تومان`;
}

export function fmtPriceInline(val, fallback = "نامشخص") {
  if (val === null || val === undefined || val === "") return fallback;
  const num = Number(val);
  if (Number.isNaN(num)) return fallback;
  return `${fmtNumber(num)} ریال (${fmtNumber(num / 10)} تومان)`;
}

export function fmtPriceHtml(val, fallback = "نامشخص") {
  if (val === null || val === undefined || val === "") {
    return `<span class="text-muted">${escapeHtml(fallback)}</span>`;
  }
  const num = Number(val);
  if (Number.isNaN(num)) {
    return `<span class="text-muted">${escapeHtml(fallback)}</span>`;
  }
  return `<span class="price-display num"><span class="price-rial">${fmtNumber(num)} ریال</span><span class="price-toman">${fmtNumber(num / 10)} تومان</span></span>`;
}

export function rialToTomanDisplay(rawVal) {
  if (rawVal === null || rawVal === undefined || String(rawVal).trim() === "") {
    return "";
  }
  const num = Number(rawVal);
  if (Number.isNaN(num) || num < 0) {
    return "مبلغ نامعتبر";
  }
  return `معادل: ${fmtNumber(num / 10)} تومان`;
}

export function fmtDate(isoOrJalali) {
  if (!isoOrJalali) return "—";
  const text = String(isoOrJalali).trim();
  const jalaliMatch = text.match(/^(\d{4}\/\d{2}\/\d{2})(?:[ T](\d{2}:\d{2})(?::\d{2})?)?$/);
  if (jalaliMatch) {
    return jalaliMatch[2] ? `${jalaliMatch[1]} ${jalaliMatch[2]}` : jalaliMatch[1];
  }
  return formatJalaliDateTime(text, false);
}

export const TX_TYPE_LABELS = {
  OPENING: "موجودی اولیه",
  PURCHASE_IN: "خرید (ورود)",
  OUT: "خروج کالا",
  ADJUSTMENT_IN: "تعدیل افزایشی",
  ADJUSTMENT_OUT: "تعدیل کاهشی",
};

export function txTypeLabel(txType) {
  return TX_TYPE_LABELS[txType] || txType;
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
  return `<span class="badge ${cls}">${escapeHtml(txTypeLabel(txType))}</span>`;
}

export function stockBadge(qty) {
  const n = Number(qty || 0);
  if (n === 0) return `<span class="badge badge-danger num">0 (ناموجود)</span>`;
  return `<span class="badge badge-stock-accent num">${fmtQty(n)}</span>`;
}

export function toast(message, type = "info", duration = 4000) {
  let container = document.getElementById("toast-container");
  if (!container) {
    container = document.createElement("div");
    container.id = "toast-container";
    container.className = "toast-container";
    document.body.appendChild(container);
  }
  const el = document.createElement("div");
  el.className = `toast toast-${type}`;
  el.innerHTML = `<span>${escapeHtml(translateServerError(message))}</span>`;
  container.appendChild(el);
  setTimeout(() => {
    el.remove();
  }, duration);
}

export function renderPagination(container, page, totalPages, total, onPageChange) {
  if (!container) return;
  container.innerHTML = `
    <span class="text-secondary">
      صفحه <strong class="num">${page}</strong> از <strong class="num">${totalPages}</strong>
      (مجموع <span class="num">${fmtQty(total)}</span> رکورد)
    </span>
    <div class="pagination-controls">
      <button class="btn btn-sm" data-page="1" ${page <= 1 ? "disabled" : ""}>اولین</button>
      <button class="btn btn-sm" data-page="${page - 1}" ${page <= 1 ? "disabled" : ""}>قبلی</button>
      <button class="btn btn-sm" data-page="${page + 1}" ${page >= totalPages ? "disabled" : ""}>بعدی</button>
      <button class="btn btn-sm" data-page="${totalPages}" ${page >= totalPages ? "disabled" : ""}>آخرین</button>
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
    ? `<option value="">همه دسته‌بندی‌ها</option>`
    : `<option value="">انتخاب دسته‌بندی...</option>`;

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
      ? `<option value="">همه زیردسته‌ها</option>`
      : `<option value="">بدون زیردسته (استفاده از دسته اصلی)</option>`;

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
        <button type="button" class="btn btn-sm btn-ghost" data-modal-close aria-label="بستن">✕</button>
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
    title: "مشخصات و سوابق قطعه",
    bodyHtml: `<div class="empty-state">در حال بارگذاری اطلاعات قطعه...</div>`,
    large: true,
  });

  try {
    const [data] = await Promise.all([apiFetch(`/api/items/${itemId}`), getSpecSchema()]);
    const item = data.item;
    const headerTitle = modal.querySelector(".modal-header .card-title");
    if (headerTitle) {
      headerTitle.textContent = item.display_name && item.display_name !== item.item_code
        ? `${item.item_code} — ${item.display_name}`
        : item.item_code;
    }

    const txRows = (item.transactions || [])
      .map(
        (t) => `
      <tr>
        <td class="text-muted ltr">${escapeHtml(fmtDate(t.created_at_jalali || t.created_at))}</td>
        <td>${txTypeBadge(t.transaction_type)}</td>
        <td class="text-right num"><strong>${fmtQty(t.quantity)}</strong></td>
        <td class="text-right num ltr">${fmtQty(t.stock_before)} → <strong>${fmtQty(t.stock_after)}</strong></td>
        <td class="text-right num">${fmtPriceHtml(t.price, "—")}</td>
        <td class="text-right num">${fmtPriceHtml(t.unit_cost_snapshot, "نامشخص")}</td>
        <td class="text-right num">${fmtPriceHtml(t.transaction_cost_snapshot, "نامشخص")}</td>
        <td>${escapeHtml(t.user_name)}</td>
        <td class="text-secondary">${escapeHtml(t.description || "—")}</td>
      </tr>
    `
      )
      .join("");

    const specCardsHtml = renderSpecDetailCards(item);
    const body = modal.querySelector(".modal-body");
    body.innerHTML = `
      <div class="spec-grid" style="margin-bottom: 16px;">
        <div class="spec-item">
          <div class="spec-label">نوع قطعه</div>
          <div class="spec-val">${itemTypeBadge(item.item_type, item.item_type_label_fa)}</div>
        </div>
        <div class="spec-item">
          <div class="spec-label">موجودی فعلی</div>
          <div class="spec-val num" style="font-size:1.05rem;">${stockBadge(item.quantity)}</div>
        </div>
        <div class="spec-item">
          <div class="spec-label">قیمت میانگین</div>
          <div class="spec-val num">${fmtPriceHtml(item.weighted_avg_cost, "نامشخص")}</div>
        </div>
        <div class="spec-item">
          <div class="spec-label">آخرین قیمت خرید</div>
          <div class="spec-val num">${fmtPriceHtml(item.last_purchase_cost, "نامشخص")}</div>
        </div>
        <div class="spec-item">
          <div class="spec-label">ارزش کل (بر مبنای قیمت میانگین)</div>
          <div class="spec-val num">${fmtPriceHtml(item.total_wac_value, "نامشخص")}</div>
        </div>
        <div class="spec-item">
          <div class="spec-label">دسته‌بندی</div>
          <div class="spec-val">${escapeHtml(item.category_path)}</div>
        </div>
        <div class="spec-item">
          <div class="spec-label">محل نگهداری</div>
          <div class="spec-val">${escapeHtml(item.location)}</div>
        </div>
        ${specCardsHtml}
      </div>

      ${
        item.description
          ? `<div class="alert" style="margin-bottom: 16px;"><strong>توضیحات:</strong> ${escapeHtml(
              item.description
            )}</div>`
          : ""
      }

      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;gap:8px;flex-wrap:wrap;">
        <h4 style="font-size:0.95rem;">تاریخچه گردش‌های اخیر قطعه</h4>
        <a class="btn btn-sm btn-primary" href="/transactions/new?item_code=${encodeURIComponent(item.item_code)}">
          ثبت تراکنش برای این قطعه
        </a>
      </div>
      ${
        txRows
          ? `<div class="table-wrap">
               <table class="table">
                 <thead>
                   <tr>
                     <th>تاریخ</th>
                     <th>نوع</th>
                     <th class="text-right">تعداد</th>
                     <th class="text-right">موجودی</th>
                     <th class="text-right">قیمت</th>
                     <th class="text-right">بهای واحد</th>
                     <th class="text-right">جمع ارزش</th>
                     <th>کاربر</th>
                     <th>توضیحات</th>
                   </tr>
                 </thead>
                 <tbody>${txRows}</tbody>
               </table>
             </div>`
          : `<div class="empty-state">هنوز هیچ تراکنشی برای این قطعه ثبت نشده است.</div>`
      }
    `;
  } catch (err) {
    const body = modal.querySelector(".modal-body");
    if (body) {
      body.innerHTML = `<div class="alert alert-danger">${escapeHtml(translateServerError(err.message))}</div>`;
    }
  }
}
