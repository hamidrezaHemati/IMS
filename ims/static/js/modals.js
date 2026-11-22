import { apiFetch } from "./api.js";
import { closeModal, escapeHtml, openModal, toast } from "./ui.js";

/**
 * Open modal to create or edit a category / subcategory.
 */
export function openCategoryModal({
  allCategories = [],
  existing = null,
  defaultParentId = null,
  onSaved = null,
}) {
  const selectedParent = existing ? existing.parent_id : defaultParentId;
  const parentOptions = [
    `<option value="">بدون والد (دسته‌بندی اصلی)</option>`,
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
    title: existing ? "ویرایش دسته‌بندی" : "دسته‌بندی جدید",
    bodyHtml: `
      <form id="cat-modal-form" style="display:flex;flex-direction:column;gap:12px;">
        <div class="field">
          <label for="m-cat-name">نام دسته‌بندی *</label>
          <input id="m-cat-name" class="input" required maxlength="100" value="${escapeHtml(existing ? existing.name : "")}">
        </div>
        <div class="field">
          <label for="m-cat-parent">دسته والد</label>
          <select id="m-cat-parent" class="select">${parentOptions}</select>
        </div>
        <div class="field">
          <label for="m-cat-desc">توضیحات</label>
          <textarea id="m-cat-desc" class="textarea">${escapeHtml(existing ? existing.description || "" : "")}</textarea>
        </div>
      </form>
    `,
    footerHtml: `
      <button type="button" class="btn" data-modal-close>انصراف</button>
      <button type="submit" form="cat-modal-form" class="btn btn-primary">ذخیره دسته‌بندی</button>
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
      let resp;
      if (existing) {
        resp = await apiFetch(`/api/categories/${existing.id}`, { method: "PUT", body: payload });
        toast("دسته‌بندی به‌روزرسانی شد.", "success");
      } else {
        resp = await apiFetch("/api/categories", { method: "POST", body: payload });
        toast("دسته‌بندی ایجاد شد.", "success");
      }
      closeModal();
      if (onSaved) await onSaved(resp.category);
    } catch (err) {
      toast(err.message, "error");
    }
  });
}

/**
 * Open modal to create or edit an item record (inventory initialized by PostgreSQL trigger).
 */
export function openItemModal({
  allCategories = [],
  existing = null,
  onSaved = null,
  onNeedCategory = null,
}) {
  if (!allCategories.length) {
    toast("پیش از افزودن قطعه، حداقل یک دسته‌بندی ایجاد کنید.", "warning");
    if (onNeedCategory) {
      onNeedCategory();
    } else {
      openCategoryModal({ allCategories });
    }
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
    title: existing ? `ویرایش قطعه: ${existing.item_code}` : "افزودن قطعه جدید",
    large: true,
    bodyHtml: `
      <div class="alert alert-info" style="margin-bottom:12px;">
        ${
          existing
            ? "ویرایش فقط مشخصات فنی قطعه را به‌روزرسانی می‌کند. تغییر موجودی و قیمت تنها از طریق تراکنش‌ها انجام می‌شود."
            : "با ثبت قطعه جدید، ردیف موجودی خالی (تعداد ۰) به صورت خودکار توسط تریگر PostgreSQL ایجاد می‌شود. افزایش موجودی از طریق ثبت تراکنش انجام می‌شود."
        }
      </div>
      <form id="item-modal-form" class="form-grid">
        <div class="field">
          <label for="m-item-code">کد قطعه *</label>
          <input id="m-item-code" class="input ltr" required maxlength="80" value="${escapeHtml(existing ? existing.item_code : "")}">
        </div>
        <div class="field">
          <label for="m-item-cat">دسته‌بندی / زیردسته *</label>
          <select id="m-item-cat" class="select" required>${catOptions}</select>
        </div>
        <div class="field">
          <label for="m-item-model">مدل *</label>
          <input id="m-item-model" class="input" required maxlength="150" value="${escapeHtml(existing ? existing.model : "")}">
        </div>
        <div class="field">
          <label for="m-item-location">محل نگهداری / کشو *</label>
          <input id="m-item-location" class="input" required maxlength="150" value="${escapeHtml(existing ? existing.location : "")}">
        </div>
        <div class="field">
          <label for="m-item-size">سایز / پکیج</label>
          <input id="m-item-size" class="input" maxlength="50" value="${escapeHtml(existing ? existing.size || "" : "")}">
        </div>
        <div class="field">
          <label for="m-item-mount">نوع نصب</label>
          <select id="m-item-mount" class="select">
            <option value="">نامشخص</option>
            <option value="SMD" ${existing && existing.mounting_type === "SMD" ? "selected" : ""}>SMD</option>
            <option value="DIP" ${existing && existing.mounting_type === "DIP" ? "selected" : ""}>DIP</option>
          </select>
        </div>
        <div class="field">
          <label for="m-item-voltage">ولتاژ</label>
          <input id="m-item-voltage" class="input" maxlength="80" value="${escapeHtml(existing ? existing.voltage || "" : "")}">
        </div>
        <div class="field">
          <label for="m-item-material">جنس / متریال</label>
          <input id="m-item-material" class="input" maxlength="100" value="${escapeHtml(existing ? existing.material || "" : "")}">
        </div>
        <div class="field" style="grid-column: 1 / -1;">
          <label for="m-item-desc">توضیحات</label>
          <textarea id="m-item-desc" class="textarea">${escapeHtml(existing ? existing.description || "" : "")}</textarea>
        </div>
      </form>
    `,
    footerHtml: `
      <button type="button" class="btn" data-modal-close>انصراف</button>
      <button type="submit" form="item-modal-form" class="btn btn-primary">${existing ? "ذخیره تغییرات" : "ثبت قطعه"}</button>
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
      let resp;
      if (existing) {
        resp = await apiFetch(`/api/items/${existing.id}`, { method: "PUT", body: payload });
        toast("مشخصات قطعه به‌روزرسانی شد.", "success");
      } else {
        resp = await apiFetch("/api/items", { method: "POST", body: payload });
        toast("قطعه جدید با موجودی اولیه صفر ایجاد شد.", "success");
      }
      closeModal();
      if (onSaved) await onSaved(resp.item);
    } catch (err) {
      toast(err.message, "error");
    }
  });
}
