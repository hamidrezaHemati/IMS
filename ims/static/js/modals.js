import { apiFetch } from "./api.js";
import {
  collectDynamicSpecForm,
  getSpecSchema,
  renderDynamicSpecForm,
} from "./spec_ui.js";
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
 * Open category-aware dynamic modal to create or edit an electronic or mechanical item.
 */
export async function openItemModal({
  allCategories = [],
  existing = null,
  onSaved = null,
  onNeedCategory = null,
}) {
  const leafCategories = allCategories.filter((c) => c.is_leaf && c.spec_type);
  if (!leafCategories.length) {
    toast("پیش از افزودن قطعه، حداقل یک زیردسته معتبر ایجاد کنید.", "warning");
    if (onNeedCategory) {
      onNeedCategory();
    } else {
      openCategoryModal({ allCategories });
    }
    return;
  }

  await getSpecSchema();

  const roots = allCategories.filter((c) => c.parent_id === null);
  const initialCategory = existing
    ? allCategories.find((c) => c.id === existing.category_id)
    : null;
  const initialRootId = initialCategory ? initialCategory.root_id : roots[0]?.id || "";

  const rootOptions = [
    `<option value="">انتخاب دسته‌بندی اصلی...</option>`,
    ...roots.map(
      (r) =>
        `<option value="${r.id}" ${Number(initialRootId) === r.id ? "selected" : ""}>${escapeHtml(
          r.name
        )}</option>`
    ),
  ].join("");

  const modal = openModal({
    title: existing ? `ویرایش قطعه: ${existing.item_code}` : "افزودن قطعه جدید",
    large: true,
    bodyHtml: `
      <div class="alert alert-info" style="margin-bottom:12px;">
        ${
          existing
            ? "ویرایش فقط اطلاعات و مشخصات فنی قطعه را به‌روزرسانی می‌کند. تغییر موجودی و قیمت تنها از طریق تراکنش‌ها انجام می‌شود."
            : "با انتخاب نوع قطعه (الکترونیک یا مکانیک)، فرم مشخصات فنی متناسب نمایش داده می‌شود و موجودی اولیه (تعداد ۰) به صورت خودکار توسط تریگر PostgreSQL ایجاد خواهد شد."
        }
      </div>
      <form id="item-modal-form" class="form-grid">
        <div class="field">
          <label for="m-item-root-cat">دسته‌بندی اصلی *</label>
          <select id="m-item-root-cat" class="select" required>${rootOptions}</select>
        </div>
        <div class="field">
          <label for="m-item-cat">زیردسته (نوع قطعه) *</label>
          <select id="m-item-cat" class="select" required></select>
        </div>
        <div class="field">
          <label for="m-item-code">کد قطعه *</label>
          <input id="m-item-code" class="input ltr" required maxlength="80" value="${escapeHtml(existing ? existing.item_code : "")}">
        </div>
        <div class="field">
          <label for="m-item-location">محل نگهداری / کشو *</label>
          <input id="m-item-location" class="input" required maxlength="150" value="${escapeHtml(existing ? existing.location : "")}">
        </div>

        <div id="m-dynamic-specs" class="form-grid" style="grid-column:1 / -1;"></div>

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

  const rootSel = document.getElementById("m-item-root-cat");
  const subSel = document.getElementById("m-item-cat");
  const specContainer = document.getElementById("m-dynamic-specs");

  let activeSpecType = existing ? existing.item_type : null;
  let preservedSpecs = existing ? { ...(existing.specs || {}) } : {};

  function populateSubcategories(preselectId = null) {
    const rid = rootSel.value ? Number(rootSel.value) : null;
    const validSubs = rid
      ? leafCategories.filter((c) => c.root_id === rid)
      : [];

    subSel.innerHTML = [
      `<option value="">انتخاب زیردسته...</option>`,
      ...validSubs.map((c) => {
        const selected = preselectId && Number(preselectId) === c.id ? "selected" : "";
        return `<option value="${c.id}" ${selected}>${escapeHtml(c.name)}</option>`;
      }),
    ].join("");

    if (!subSel.value && validSubs.length === 1) {
      subSel.value = String(validSubs[0].id);
    }
    syncDynamicSpecForm();
  }

  function syncDynamicSpecForm() {
    const catId = subSel.value ? Number(subSel.value) : null;
    const catObj = catId ? allCategories.find((c) => c.id === catId) : null;
    const nextSpecType = catObj ? catObj.spec_type : null;

    if (nextSpecType !== activeSpecType) {
      activeSpecType = nextSpecType;
      const seedSpecs =
        existing && existing.item_type === nextSpecType
          ? existing.specs || {}
          : {};
      renderDynamicSpecForm(specContainer, nextSpecType, seedSpecs);
    } else if (nextSpecType) {
      renderDynamicSpecForm(specContainer, nextSpecType, preservedSpecs);
    } else {
      renderDynamicSpecForm(specContainer, null, {});
    }
  }

  rootSel.addEventListener("change", () => {
    preservedSpecs = {};
    populateSubcategories(null);
  });

  subSel.addEventListener("change", () => {
    const catObj = subSel.value
      ? allCategories.find((c) => c.id === Number(subSel.value))
      : null;
    const nextSpecType = catObj ? catObj.spec_type : null;
    if (nextSpecType === activeSpecType && nextSpecType) {
      return;
    }
    preservedSpecs = {};
    syncDynamicSpecForm();
  });

  populateSubcategories(existing ? existing.category_id : null);

  modal.querySelector("#item-modal-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const catId = Number(subSel.value);
    const catObj = allCategories.find((c) => c.id === catId);
    const specType = catObj ? catObj.spec_type : null;
    if (!catId || !specType) {
      toast("لطفاً دسته‌بندی اصلی و زیردسته معتبر انتخاب کنید.", "warning");
      return;
    }

    let specs;
    try {
      specs = collectDynamicSpecForm(specContainer, specType);
    } catch (validationErr) {
      toast(validationErr.message, "warning");
      return;
    }

    const payload = {
      item_code: document.getElementById("m-item-code").value,
      category_id: catId,
      location: document.getElementById("m-item-location").value,
      description: document.getElementById("m-item-desc").value,
      specs,
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
