import { apiFetch } from "./api.js";
import { escapeHtml } from "./ui.js";

let _schemaCache = null;
let _schemaPromise = null;

export async function getSpecSchema() {
  if (_schemaCache) return _schemaCache;
  if (!_schemaPromise) {
    _schemaPromise = apiFetch("/api/items/spec-schema").then((data) => {
      _schemaCache = data;
      return data;
    });
  }
  return _schemaPromise;
}

export function getCachedSpecSchema() {
  return _schemaCache;
}

export function itemTypeBadge(itemType, labelFa = null) {
  const cls = itemType === "electronic_item" ? "badge-info" : "badge-neutral";
  const def = _schemaCache && _schemaCache.types ? _schemaCache.types[itemType] : null;
  const label = labelFa || (def ? def.label_fa : itemType || "نامشخص");
  return `<span class="badge ${cls}">${escapeHtml(label)}</span>`;
}

export function formatMm(val) {
  if (val === null || val === undefined || val === "") return "";
  const num = Number(val);
  if (Number.isNaN(num)) return String(val);
  return String(Number(num.toFixed(3)));
}

function normalizeDigitsJS(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/[۰-۹]/g, (ch) => String(ch.charCodeAt(0) - 0x06f0))
    .replace(/[٠-٩]/g, (ch) => String(ch.charCodeAt(0) - 0x0660));
}

export function resolveSpecContextFromCategory(categoryObj, allCategories = []) {
  if (!categoryObj) {
    return { isLeaf: false, specType: null, rootName: null };
  }
  const rootCat =
    allCategories.find((c) => c.id === categoryObj.root_id) ||
    (categoryObj.parent_id === null ? categoryObj : null);
  const rootName = rootCat ? rootCat.name : categoryObj.root_name || null;
  const isLeaf = categoryObj.parent_id !== null && (categoryObj.child_count || 0) === 0;
  return {
    isLeaf,
    specType: categoryObj.spec_type || null,
    rootName,
  };
}

function updateORingCrossSectionPreview(container) {
  const innerEl = container.querySelector('[data-spec-field="inner_diameter"]');
  const outerEl = container.querySelector('[data-spec-field="outer_diameter"]');
  const csEl = container.querySelector('[data-spec-computed="cross_section"]');
  if (!innerEl || !outerEl || !csEl) return;

  const innerStr = normalizeDigitsJS(innerEl.value).trim();
  const outerStr = normalizeDigitsJS(outerEl.value).trim();
  if (!innerStr || !outerStr) {
    csEl.value = "";
    csEl.classList.remove("is-invalid-field");
    return;
  }

  const inner = Number(innerStr);
  const outer = Number(outerStr);
  if (Number.isNaN(inner) || Number.isNaN(outer) || inner <= 0 || outer <= inner) {
    csEl.value = "نامعتبر (قطر خارجی باید بزرگ‌تر از داخلی باشد)";
    csEl.classList.add("is-invalid-field");
    return;
  }

  const cs = (outer - inner) / 2;
  csEl.value = formatMm(cs);
  csEl.classList.remove("is-invalid-field");
}

export function renderDynamicSpecForm(container, specType, existingSpecs = {}) {
  if (!container) return;
  const schema = _schemaCache;
  if (!specType || !schema || !schema.types || !schema.types[specType]) {
    container.innerHTML = `
      <div class="alert alert-info" style="grid-column:1 / -1;">
        ابتدا دسته‌بندی اصلی و زیردسته قطعه را انتخاب کنید تا فیلدهای فنی اختصاصی آن نوع قطعه نمایش داده شوند.
      </div>`;
    return;
  }

  const def = schema.types[specType];
  const specs = existingSpecs || {};

  const fieldsHtml = def.fields
    .map((f) => {
      const id = `m-spec-${f.name}`;
      const rawVal = specs[f.name];
      const reqStar = f.required ? " *" : "";

      if (f.kind === "computed_mm") {
        const val = rawVal !== null && rawVal !== undefined ? formatMm(rawVal) : "";
        return `
          <div class="field">
            <label for="${id}">${escapeHtml(f.label_fa)} (mm)</label>
            <div class="input-unit-group">
              <input
                id="${id}"
                type="text"
                readonly
                tabindex="-1"
                class="input ltr spec-computed-box"
                placeholder="محاسبه خودکار..."
                value="${escapeHtml(val)}"
                data-spec-computed="${f.name}"
              >
              <span class="input-unit">mm</span>
            </div>
          </div>`;
      }

      if (f.kind === "mm") {
        const val = rawVal !== null && rawVal !== undefined ? formatMm(rawVal) : "";
        return `
          <div class="field">
            <label for="${id}">${escapeHtml(f.label_fa)} (mm)${reqStar}</label>
            <div class="input-unit-group">
              <input
                id="${id}"
                type="number"
                step="0.001"
                min="0.001"
                ${f.required ? "required" : ""}
                class="input ltr"
                placeholder="مثلاً 4 یا 3.5"
                value="${escapeHtml(val)}"
                data-spec-field="${f.name}"
              >
              <span class="input-unit">mm</span>
            </div>
          </div>`;
      }

      if (f.kind === "enum") {
        const opts = [
          `<option value="">نامشخص</option>`,
          ...(f.options || []).map(
            (opt) =>
              `<option value="${escapeHtml(opt.value)}" ${
                rawVal === opt.value ? "selected" : ""
              }>${escapeHtml(opt.label_fa)}</option>`
          ),
        ].join("");
        return `
          <div class="field">
            <label for="${id}">${escapeHtml(f.label_fa)}${reqStar}</label>
            <select id="${id}" class="select" ${f.required ? "required" : ""} data-spec-field="${f.name}">
              ${opts}
            </select>
          </div>`;
      }

      const strVal = rawVal !== null && rawVal !== undefined ? String(rawVal) : "";
      return `
        <div class="field">
          <label for="${id}">${escapeHtml(f.label_fa)}${reqStar}</label>
          <input
            id="${id}"
            type="text"
            class="input"
            ${f.max_len ? `maxlength="${f.max_len}"` : ""}
            ${f.required ? "required" : ""}
            ${f.placeholder ? `placeholder="${escapeHtml(f.placeholder)}"` : ""}
            value="${escapeHtml(strVal)}"
            data-spec-field="${f.name}"
          >
        </div>`;
    })
    .join("");

  container.innerHTML = `
    <div class="spec-form-banner" style="grid-column:1 / -1;">
      <span>مشخصات فنی اختصاصی: <strong>${escapeHtml(def.label_fa)}</strong></span>
      ${def.root_category === "Mechanical" ? `<span class="badge badge-warning">تمام ابعاد به میلی‌متر (mm)</span>` : ""}
    </div>
    ${fieldsHtml}
  `;

  if (specType === "o_ring") {
    const innerEl = container.querySelector('[data-spec-field="inner_diameter"]');
    const outerEl = container.querySelector('[data-spec-field="outer_diameter"]');
    if (innerEl && outerEl) {
      innerEl.addEventListener("input", () => updateORingCrossSectionPreview(container));
      outerEl.addEventListener("input", () => updateORingCrossSectionPreview(container));
      updateORingCrossSectionPreview(container);
    }
  }
}

export function collectDynamicSpecForm(container, specType) {
  const schema = _schemaCache;
  if (!specType || !schema || !schema.types || !schema.types[specType]) {
    throw new Error("لطفاً یک دسته‌بندی معتبر (زیردسته نهایی) انتخاب کنید.");
  }
  const def = schema.types[specType];
  const specs = {};

  for (const f of def.fields) {
    if (f.kind === "computed_mm") continue;
    const el = container.querySelector(`[data-spec-field="${f.name}"]`);
    if (!el) continue;
    const raw = normalizeDigitsJS(el.value).trim();

    if (f.kind === "mm") {
      if (!raw) {
        if (f.required) {
          throw new Error(`وارد کردن ${f.label_fa} (بر حسب میلی‌متر) الزامی است.`);
        }
        specs[f.name] = null;
      } else {
        const num = Number(raw);
        if (Number.isNaN(num) || num <= 0) {
          throw new Error(`${f.label_fa} باید یک عدد مثبت بر حسب میلی‌متر باشد.`);
        }
        specs[f.name] = raw;
      }
    } else {
      specs[f.name] = raw || null;
    }
  }

  if (specType === "o_ring") {
    const inner = Number(specs.inner_diameter);
    const outer = Number(specs.outer_diameter);
    if (!(outer > inner)) {
      throw new Error("قطر خارجی اورینگ باید اکیداً بزرگ‌تر از قطر داخلی آن باشد.");
    }
  }

  return specs;
}

function optionLabelFa(specType, fieldName, value) {
  if (value === null || value === undefined || value === "") return "";
  const schema = _schemaCache;
  const def = schema && schema.types ? schema.types[specType] : null;
  if (!def) return String(value);
  const field = def.fields.find((f) => f.name === fieldName);
  if (!field || !field.options) return String(value);
  const found = field.options.find((o) => o.value === value);
  return found ? found.label_fa : String(value);
}

export function renderSpecDetailCards(item) {
  const schema = _schemaCache;
  const def = schema && schema.types ? schema.types[item.item_type] : null;
  const specs = item.specs || {};
  if (!def) {
    return item.spec_summary && item.spec_summary !== "—"
      ? `<div class="spec-item"><div class="spec-label">مشخصات</div><div class="spec-val">${escapeHtml(item.spec_summary)}</div></div>`
      : "";
  }

  const cards = [];
  for (const f of def.fields) {
    const val = specs[f.name];
    if (val === null || val === undefined || val === "") continue;
    let display;
    if (f.kind === "mm" || f.kind === "computed_mm") {
      display = `${formatMm(val)} mm`;
    } else if (f.kind === "enum") {
      display = optionLabelFa(item.item_type, f.name, val);
    } else {
      display = String(val);
    }
    cards.push(`
      <div class="spec-item">
        <div class="spec-label">${escapeHtml(f.label_fa)}</div>
        <div class="spec-val ${f.kind === "mm" || f.kind === "computed_mm" ? "num ltr" : ""}">${escapeHtml(display)}</div>
      </div>`);
  }
  return cards.join("");
}

function buildMmFilterPairHtml(prefix, name, labelFa) {
  return `
    <div class="field">
      <label for="${prefix}-min-${name}">${escapeHtml(labelFa)} (از / تا mm)</label>
      <div class="mm-range-pair">
        <input id="${prefix}-min-${name}" class="input ltr" type="number" step="0.001" min="0" placeholder="حداقل" data-filter-key="min_${name}">
        <input id="${prefix}-max-${name}" class="input ltr" type="number" step="0.001" min="0" placeholder="حداکثر" data-filter-key="max_${name}">
        <input id="${prefix}-${name}" class="input ltr" type="number" step="0.001" min="0.001" placeholder="دقیق" data-filter-key="${name}">
      </div>
    </div>`;
}

export function renderDynamicFilterFields(container, filterMode, prefix = "dyn") {
  if (!container) return;
  const schema = _schemaCache;

  if (!filterMode) {
    container.innerHTML = "";
    container.classList.add("hidden");
    return;
  }

  if (filterMode === "mechanical_any") {
    container.classList.remove("hidden");
    container.innerHTML = `
      <div class="spec-filter-title">فیلترهای عمومی قطعات مکانیکی (ابعاد به میلی‌متر)</div>
      <div class="form-grid">
        ${buildMmFilterPairHtml(prefix, "diameter", "قطر")}
        ${buildMmFilterPairHtml(prefix, "length", "طول")}
        <div class="field">
          <label for="${prefix}-material">جنس / متریال</label>
          <select id="${prefix}-material" class="select" data-filter-key="material">
            <option value="">همه</option>
            <option value="STAINLESS_STEEL">استیل ضدزنگ (Stainless Steel)</option>
            <option value="IRON">آهن (Iron)</option>
            <option value="PLASTIC">پلاستیک (Plastic)</option>
            <option value="BLACK">مشکی (Black)</option>
            <option value="WHITE">سفید / گالوانیزه (White)</option>
            <option value="PAPER">کاغذی (Paper)</option>
            <option value="NBR">NBR</option>
            <option value="VITON">وایتون (VITON)</option>
            <option value="SILICONE">سیلیکون (SILICONE)</option>
          </select>
        </div>
      </div>`;
    return;
  }

  const def = schema && schema.types ? schema.types[filterMode] : null;
  if (!def) {
    container.innerHTML = "";
    container.classList.add("hidden");
    return;
  }

  container.classList.remove("hidden");
  const fieldsHtml = def.fields
    .map((f) => {
      const id = `${prefix}-${f.name}`;
      if (f.kind === "mm" || f.kind === "computed_mm") {
        return buildMmFilterPairHtml(prefix, f.name, f.label_fa.replace(" (محاسبه خودکار)", ""));
      }
      if (f.kind === "enum") {
        const opts = [
          `<option value="">همه</option>`,
          ...(f.options || []).map((o) => `<option value="${escapeHtml(o.value)}">${escapeHtml(o.label_fa)}</option>`),
        ].join("");
        return `
          <div class="field">
            <label for="${id}">${escapeHtml(f.label_fa)}</label>
            <select id="${id}" class="select" data-filter-key="${f.name}">${opts}</select>
          </div>`;
      }
      const filterKey = filterMode === "electronic_item" && f.name === "material" ? "electronic_material" : f.name;
      return `
        <div class="field">
          <label for="${id}">${escapeHtml(f.label_fa)}</label>
          <input id="${id}" class="input" type="text" data-filter-key="${filterKey}">
        </div>`;
    })
    .join("");

  container.innerHTML = `
    <div class="spec-filter-title">فیلترهای تخصصی: ${escapeHtml(def.label_fa)}</div>
    <div class="form-grid">${fieldsHtml}</div>
  `;
}

export function collectDynamicFilterParams(container) {
  const out = {};
  if (!container) return out;
  container.querySelectorAll("[data-filter-key]").forEach((el) => {
    const val = normalizeDigitsJS(el.value).trim();
    if (val !== "") {
      out[el.dataset.filterKey] = val;
    }
  });
  return out;
}

export function resetDynamicFilterFields(container) {
  if (!container) return;
  container.querySelectorAll("[data-filter-key]").forEach((el) => {
    el.value = "";
  });
}

export function inferFilterModeFromSelects({
  itemTypeVal = "",
  parentCatId = "",
  subCatId = "",
  categories = [],
}) {
  if (itemTypeVal) return itemTypeVal;
  if (subCatId) {
    const sub = categories.find((c) => String(c.id) === String(subCatId));
    if (sub && sub.spec_type) return sub.spec_type;
  }
  if (parentCatId) {
    const leafSpecs = Array.from(
      new Set(
        categories
          .filter((c) => String(c.root_id) === String(parentCatId) && c.is_leaf && c.spec_type)
          .map((c) => c.spec_type)
      )
    );
    if (leafSpecs.length === 1) return leafSpecs[0];
    if (leafSpecs.length > 1) {
      return leafSpecs.includes("electronic_item") ? "" : "mechanical_any";
    }
    const parent = categories.find((c) => String(c.id) === String(parentCatId));
    if (parent) {
      const n = String(parent.name || "")
        .replace(/ي/g, "ی")
        .replace(/ك/g, "ک")
        .trim()
        .toLowerCase();
      if (
        [
          "electronic",
          "electronics",
          "الکترونیک",
          "الکترونیکی",
          "قطعات الکترونیک",
          "قطعات الکترونیکی",
        ].includes(n)
      ) {
        return "electronic_item";
      }
      if (
        [
          "mechanical",
          "mechanics",
          "مکانیک",
          "مکانیکی",
          "قطعات مکانیک",
          "قطعات مکانیکی",
        ].includes(n)
      ) {
        return "mechanical_any";
      }
    }
  }
  return "";
}
