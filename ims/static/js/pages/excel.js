import { apiFetch } from "../api.js";
import { getSpecSchema, itemTypeBadge } from "../spec_ui.js";
import { escapeHtml, fmtPriceHtml, fmtQty, toast, translateServerError } from "../ui.js";

const STATUS_FA = {
  new: "جدید",
  existing: "موجود در سیستم",
  duplicate: "تکراری",
  invalid: "نامعتبر",
  created: "ایجاد شد",
  updated: "به‌روزرسانی شد",
  skipped: "رد شد",
  failed: "ناموفق",
};

const POLICY_EXPLANATION_FA = {
  skip: "سیاست امن پیش‌فرض: فقط کدهای قطعه جدید با مشخصات نوع انتخاب‌شده ایجاد می‌شوند و موجودی اولیه آن‌ها از طریق تراکنش OPENING ثبت می‌گردد. اقلامی که از قبل در سیستم وجود دارند نادیده گرفته می‌شوند.",
  update_metadata: "اقلام جدید ایجاد شده و موجودی اولیه آن‌ها ثبت می‌شود. برای کدهای موجود هم‌نوع در سیستم، فقط مشخصات فنی به‌روزرسانی می‌شود و موجودی، قیمت‌ها و تاریخچه تراکنش‌ها تغییر نمی‌کنند.",
};

let specSchema = null;
let activeItemType = null;
let activeUploadId = null;
let activeFieldsMeta = [];
let lastPreview = null;
let rowFilterStatus = "ALL";

function translateImportMessage(msg) {
  if (!msg) return "";
  const text = String(msg);
  if (/Missing item_code/i.test(text)) return "کد قطعه وارد نشده است.";
  if (/Missing category/i.test(text)) return "دسته‌بندی اصلی وارد نشده است.";
  if (/Missing sub_category/i.test(text)) return "زیردسته وارد نشده است.";
  if (/Missing model/i.test(text)) return "مدل قطعه وارد نشده است.";
  if (/Missing location/i.test(text)) return "محل نگهداری وارد نشده است.";
  if (/Duplicate item_code/i.test(text)) return "کد قطعه در فایل اکسل تکراری است.";
  if (/Quantity is 0:/i.test(text)) {
    return "مقدار صفر است: قطعه با موجودی ۰ ایجاد می‌شود و تراکنش OPENING ثبت نخواهد شد.";
  }
  if (/Price will not apply because quantity is 0/i.test(text)) {
    return "به دلیل صفر بودن تعداد، قیمت اعمال نمی‌شود.";
  }
  if (/Existing stock .* will NOT be altered/i.test(text)) {
    return "فقط مشخصات فنی به‌روزرسانی می‌شود؛ موجودی و تراکنش‌ها تغییر نمی‌کنند.";
  }
  if (/Already exists .* row will be skipped/i.test(text)) {
    return "در سیستم موجود است؛ این ردیف نادیده گرفته می‌شود.";
  }
  if (/Existing item skipped per import policy/i.test(text)) {
    return "بر اساس سیاست انتخابی، قلم موجود نادیده گرفته شد.";
  }
  if (/Specifications updated; stock and transactions unchanged/i.test(text)) {
    return "مشخصات به‌روزرسانی شد؛ موجودی و تراکنش‌ها بدون تغییر ماندند.";
  }
  if (/quantity must be/i.test(text)) return "مقدار تعداد باید یک عدد صحیح نامنفی باشد.";
  if (/price must be/i.test(text)) return "قیمت باید یک عدد معتبر و نامنفی باشد.";
  return translateServerError(text);
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
  return `<span class="badge ${map[status] || "badge-neutral"}">${escapeHtml(STATUS_FA[status] || status)}</span>`;
}

function renderImportTypeCards() {
  const grid = document.getElementById("imp-cards-grid");
  if (!specSchema || !specSchema.order) {
    grid.innerHTML = `<div class="alert alert-danger">امکان دریافت ساختار انواع قطعات وجود ندارد.</div>`;
    return;
  }

  grid.innerHTML = specSchema.order
    .map((key) => {
      const def = specSchema.types[key];
      const fieldNotes = def.fields
        .map((f) => {
          const star = f.required ? " *" : "";
          const unit = f.kind === "mm" || f.kind === "computed_mm" ? " (mm)" : "";
          const computed = f.kind === "computed_mm" ? " [خودکار]" : "";
          return `<span class="badge ${f.required ? "badge-info" : "badge-neutral"}">${escapeHtml(
            f.label_fa + unit + star + computed
          )}</span>`;
        })
        .join(" ");

      const typeHint =
        key === "o_ring"
          ? "سطح مقطع به صورت خودکار توسط پایگاه‌داده از (قطر خارجی − قطر داخلی) ÷ ۲ محاسبه می‌شود."
          : key === "electronic_item"
          ? "ستون زیردسته (Resistor، Capacitor و...) الزامی است؛ سایز پکیج در ستون package_size ثبت می‌شود."
          : `ابعاد مکانیکی باید به صورت عدد خالص بر حسب میلی‌متر (mm) وارد شوند (بدون پسوند mm یا M5).`;

      return `
      <article class="card import-type-card ${activeItemType === key ? "is-active-import" : ""}" data-import-card="${escapeHtml(key)}">
        <div class="card-header">
          <div>
            <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
              ${itemTypeBadge(key, def.label_fa)}
              <span class="text-muted mono" style="font-size:0.78rem;">${escapeHtml(def.label_en)}</span>
            </div>
            <div class="text-muted" style="font-size:0.78rem;margin-top:4px;">
              دسته پیش‌فرض: ${escapeHtml(def.root_category)} &gt; ${escapeHtml(def.default_subcategory)}
            </div>
          </div>
          <a href="/api/import/template/${encodeURIComponent(key)}" class="btn btn-sm">فایل نمونه (.xlsx)</a>
        </div>
        <div class="card-body" style="display:flex;flex-direction:column;gap:12px;">
          <div style="display:flex;flex-wrap:wrap;gap:6px;">${fieldNotes}</div>
          <p class="text-secondary" style="font-size:0.81rem;margin:0;">${escapeHtml(typeHint)}</p>
          <div class="dropzone" data-dropzone="${escapeHtml(key)}">
            <input type="file" accept=".xlsx" class="hidden" data-file-input="${escapeHtml(key)}">
            <p style="font-weight:700;margin:0;">بارگذاری فایل اکسل ${escapeHtml(def.label_fa)} (.xlsx)</p>
            <p class="text-muted" style="font-size:0.79rem;margin:4px 0 0;" data-card-status="${escapeHtml(key)}">
              فایل را اینجا رها کنید یا کلیک کنید
            </p>
          </div>
        </div>
      </article>`;
    })
    .join("");

  grid.querySelectorAll("[data-dropzone]").forEach((dz) => {
    const key = dz.dataset.dropzone;
    const input = dz.querySelector(`[data-file-input="${key}"]`);
    dz.addEventListener("click", () => input.click());
    input.addEventListener("change", () => handleImportUpload(key, input.files[0]));
    dz.addEventListener("dragover", (e) => {
      e.preventDefault();
      dz.classList.add("dragover");
    });
    dz.addEventListener("dragleave", () => dz.classList.remove("dragover"));
    dz.addEventListener("drop", (e) => {
      e.preventDefault();
      dz.classList.remove("dragover");
      if (e.dataTransfer.files.length) {
        handleImportUpload(key, e.dataTransfer.files[0]);
      }
    });
  });
}

function renderMappingControls(info) {
  activeFieldsMeta = info.fields || [];
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

  grid.innerHTML = activeFieldsMeta
    .map((f) => {
      const opts = [
        `<option value="">${f.required ? "انتخاب ستون..." : "(نگاشت نشده)"}</option>`,
        ...headers.map(
          (h) =>
            `<option value="${escapeHtml(h)}" ${suggested[f.key] === h ? "selected" : ""}>${escapeHtml(h)}</option>`
        ),
      ].join("");

      return `
        <div class="field">
          <label for="map-${escapeHtml(f.key)}">${escapeHtml(f.label)}${f.required ? " *" : ""}</label>
          <select id="map-${escapeHtml(f.key)}" class="select">${opts}</select>
        </div>`;
    })
    .join("");
}

function collectMapping() {
  const mapping = {};
  activeFieldsMeta.forEach((f) => {
    const el = document.getElementById(`map-${f.key}`);
    mapping[f.key] = el && el.value ? el.value : null;
  });
  return mapping;
}

function renderPreview(preview) {
  lastPreview = preview;
  document.getElementById("imp-preview-section").classList.remove("hidden");
  document.getElementById("imp-result-section").classList.add("hidden");

  const policyText = POLICY_EXPLANATION_FA[preview.existing_policy] || preview.policy_explanation;
  document.getElementById("imp-policy-banner").innerHTML = `
    <strong>${escapeHtml(preview.item_type_label_fa || activeItemType)} — سیاست ورود اطلاعات:</strong> ${escapeHtml(policyText)}
  `;

  const s = preview.summary;
  document.getElementById("imp-preview-kpis").innerHTML = `
    <div class="card kpi-card"><span class="kpi-label">کل ردیف‌های اکسل</span><span class="kpi-value">${fmtQty(s.total_rows)}</span></div>
    <div class="card kpi-card"><span class="kpi-label">اقلام جدید آماده ثبت</span><span class="kpi-value text-success">${fmtQty(s.valid_new_rows)}</span><span class="kpi-note">${fmtQty(s.zero_quantity_new_rows)} قلم با موجودی صفر</span></div>
    <div class="card kpi-card"><span class="kpi-label">اقلام موجود در سیستم</span><span class="kpi-value">${fmtQty(s.existing_rows)}</span><span class="kpi-note">رد شده: ${fmtQty(s.existing_skipped_rows)} • به‌روزرسانی مشخصات: ${fmtQty(s.existing_updated_rows)}</span></div>
    <div class="card kpi-card kpi-card-accent"><span class="kpi-label">کدهای تکراری در فایل</span><span class="kpi-value ${s.duplicate_rows > 0 ? "text-warning" : ""}">${fmtQty(s.duplicate_rows)}</span></div>
    <div class="card kpi-card"><span class="kpi-label">نامعتبر / ناقص</span><span class="kpi-value ${s.invalid_rows > 0 ? "text-danger" : ""}">${fmtQty(s.invalid_rows)}</span><span class="kpi-note">${fmtQty(s.missing_category_rows)} ردیف بدون دسته‌بندی مجاز</span></div>
    <div class="card kpi-card kpi-card-accent"><span class="kpi-label">دسته‌بندی‌های جدید</span><span class="kpi-value">${fmtQty(s.categories_to_create)} / ${fmtQty(s.subcategories_to_create)}</span><span class="kpi-note">دسته اصلی / زیردسته</span></div>
  `;

  const catPlanBox = document.getElementById("imp-cat-plan");
  if (!preview.category_plan || !preview.category_plan.length) {
    catPlanBox.innerHTML = `<span class="text-muted">هیچ دسته‌بندی یا زیردسته جدیدی از ردیف‌های معتبر ایجاد نمی‌شود.</span>`;
  } else {
    catPlanBox.innerHTML = preview.category_plan
      .map((p) => {
        const pLabel = p.status === "new" ? "جدید" : "موجود";
        const subs = (p.subcategories || [])
          .map(
            (sub) =>
              `<span class="badge ${sub.status === "new" ? "badge-success" : "badge-neutral"}">${escapeHtml(
                sub.name
              )} (${sub.status === "new" ? "جدید" : "موجود"})</span>`
          )
          .join(" ");
        return `
        <div style="padding:8px 0;border-bottom:1px solid var(--border-color);display:flex;flex-wrap:wrap;gap:8px;align-items:center;">
          <strong>${escapeHtml(p.name)}</strong>
          <span class="badge ${p.status === "new" ? "badge-info" : "badge-neutral"}">${pLabel}</span>
          ${subs ? `<span class="text-muted">←</span> ${subs}` : ""}
        </div>`;
      })
      .join("");
  }

  renderPreviewRows();
  const confirmBtn = document.getElementById("imp-confirm-btn");
  confirmBtn.disabled = s.will_import_rows === 0;
  confirmBtn.textContent = "تایید و اجرای نهایی ورود اطلاعات";
}

function renderPreviewRows() {
  if (!lastPreview) return;
  const rows = (lastPreview.rows || []).filter(
    (r) => rowFilterStatus === "ALL" || r.status === rowFilterStatus
  );
  const tbody = document.getElementById("imp-preview-tbody");
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="9" class="empty-state">ردیفی با این وضعیت وجود ندارد.</td></tr>`;
    return;
  }

  tbody.innerHTML = rows
    .map((r) => {
      const catText = r.sub_category ? `${r.category || "?"} > ${r.sub_category}` : r.category || "—";
      const msgs = [
        ...(r.errors || []).map((e) => `<div class="text-danger">${escapeHtml(translateImportMessage(e))}</div>`),
        ...(r.warnings || []).map((w) => `<div class="text-warning">${escapeHtml(translateImportMessage(w))}</div>`),
      ].join("");
      return `
      <tr>
        <td class="num">${r.row_number}</td>
        <td>${statusBadge(r.status)}</td>
        <td class="mono"><strong>${escapeHtml(r.item_code || "—")}</strong></td>
        <td>${escapeHtml(catText)}</td>
        <td>${escapeHtml(r.spec_summary || "—")}</td>
        <td>${escapeHtml(r.location || "—")}</td>
        <td class="text-right num">${r.quantity !== null && r.quantity !== undefined ? fmtQty(r.quantity) : "—"}</td>
        <td class="text-right num">${fmtPriceHtml(r.price, "—")}</td>
        <td style="font-size:0.82rem;">${msgs || `<span class="text-success">آماده ثبت</span>`}</td>
      </tr>`;
    })
    .join("");
}

function renderImportResults(res) {
  document.getElementById("imp-preview-section").classList.add("hidden");
  document.getElementById("imp-result-section").classList.remove("hidden");

  const s = res.summary;
  document.getElementById("imp-result-kpis").innerHTML = `
    <div class="card kpi-card"><span class="kpi-label">کل ردیف‌های اکسل</span><span class="kpi-value">${fmtQty(s.total_rows)}</span></div>
    <div class="card kpi-card"><span class="kpi-label">اقلام واردشده</span><span class="kpi-value text-success">${fmtQty(s.imported_items)}</span><span class="kpi-note">ایجاد شده: ${fmtQty(s.created_items)} • به‌روزرسانی شده: ${fmtQty(s.updated_items)}</span></div>
    <div class="card kpi-card kpi-card-accent"><span class="kpi-label">تراکنش‌های OPENING</span><span class="kpi-value">${fmtQty(s.opening_transactions_created)}</span><span class="kpi-note">مقداردهی قیمت میانگین و آخرین خرید</span></div>
    <div class="card kpi-card"><span class="kpi-label">دسته‌بندی‌های ایجادشده</span><span class="kpi-value">${fmtQty(s.categories_created)} / ${fmtQty(s.subcategories_created)}</span><span class="kpi-note">دسته اصلی / زیردسته</span></div>
    <div class="card kpi-card"><span class="kpi-label">رد شده / ناموفق</span><span class="kpi-value ${s.failed_rows > 0 ? "text-danger" : ""}">${fmtQty(s.skipped_items)} / ${fmtQty(s.failed_rows)}</span><span class="kpi-note">تکراری: ${fmtQty(s.duplicate_rows)} • نامعتبر: ${fmtQty(s.invalid_or_missing_rows)}</span></div>
  `;

  document.getElementById("imp-result-tbody").innerHTML = (res.results || [])
    .map(
      (r) => `
    <tr>
      <td class="num">${r.row_number}</td>
      <td class="mono"><strong>${escapeHtml(r.item_code || "—")}</strong></td>
      <td>${itemTypeBadge(res.item_type, res.item_type_label_fa)} ${escapeHtml(r.spec_summary || "—")}</td>
      <td>${statusBadge(r.status)}</td>
      <td class="text-right num">${r.quantity !== undefined && r.quantity !== null ? fmtQty(r.quantity) : "—"}</td>
      <td class="text-right num">${fmtPriceHtml(r.price, "—")}</td>
      <td class="text-secondary">${escapeHtml(
        r.reason
          ? translateImportMessage(r.reason)
          : r.opening_transaction_id
          ? `تراکنش OPENING شماره ${r.opening_transaction_id}`
          : "قطعه ایجاد شد (موجودی ۰)"
      )}</td>
    </tr>`
    )
    .join("");
}

async function handleImportUpload(itemType, file) {
  if (!file || !itemType) return;
  const fd = new FormData();
  fd.append("file", file);
  fd.append("item_type", itemType);

  try {
    const info = await apiFetch("/api/import/upload", { method: "POST", body: fd });
    activeItemType = itemType;
    activeUploadId = info.upload_id;
    lastPreview = null;
    rowFilterStatus = "ALL";

    document.querySelectorAll("[data-import-card]").forEach((card) => {
      card.classList.toggle("is-active-import", card.dataset.importCard === itemType);
    });
    const cardStatus = document.querySelector(`[data-card-status="${itemType}"]`);
    if (cardStatus) {
      cardStatus.textContent = `بارگذاری‌شده: ${file.name} (${fmtQty(info.total_data_rows)} ردیف)`;
    }

    document.getElementById("imp-active-type-label").textContent = info.item_type_label_fa || itemType;
    document.getElementById("imp-active-file-badge").textContent = `${file.name} (${fmtQty(info.total_data_rows)} ردیف)`;

    renderMappingControls(info);
    document.getElementById("imp-config-panel").classList.remove("hidden");
    document.getElementById("imp-preview-section").classList.add("hidden");
    document.getElementById("imp-result-section").classList.add("hidden");
    document.getElementById("imp-config-panel").scrollIntoView({ behavior: "smooth", block: "start" });

    toast(`فایل ${file.name} برای «${info.item_type_label_fa}» بارگذاری شد.`, "success");
  } catch (err) {
    toast(err.message, "error");
  }
}

document.addEventListener("DOMContentLoaded", async () => {
  try {
    specSchema = await getSpecSchema();
    renderImportTypeCards();
  } catch (err) {
    toast(err.message, "error");
  }

  document.getElementById("imp-sheet").addEventListener("change", async (e) => {
    if (!activeUploadId || !activeItemType) return;
    try {
      const info = await apiFetch("/api/import/inspect", {
        method: "POST",
        body: {
          upload_id: activeUploadId,
          item_type: activeItemType,
          sheet_name: e.target.value,
        },
      });
      renderMappingControls(info);
    } catch (err) {
      toast(err.message, "error");
    }
  });

  document.getElementById("imp-preview-btn").addEventListener("click", async () => {
    if (!activeUploadId || !activeItemType) return;
    try {
      const preview = await apiFetch("/api/import/preview", {
        method: "POST",
        body: {
          upload_id: activeUploadId,
          item_type: activeItemType,
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
    if (!activeUploadId || !activeItemType) return;
    const btn = e.currentTarget;
    btn.disabled = true;
    btn.textContent = "در حال ورود اطلاعات...";
    try {
      const res = await apiFetch("/api/import/confirm", {
        method: "POST",
        body: {
          upload_id: activeUploadId,
          item_type: activeItemType,
          sheet_name: document.getElementById("imp-sheet").value,
          column_mapping: collectMapping(),
          existing_policy: document.getElementById("imp-policy").value,
        },
      });
      activeUploadId = null;
      renderImportResults(res);
      toast(`ورود اطلاعات با موفقیت انجام شد: ${res.summary.imported_items} قلم ثبت گردید.`, "success");
    } catch (err) {
      toast(err.message, "error");
      btn.disabled = false;
      btn.textContent = "تایید و اجرای نهایی ورود اطلاعات";
    }
  });
});
