import { apiFetch, buildQuery, downloadExcel } from "../api.js";
import { fmtQty, populateCategorySelects, toast } from "../ui.js";

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
  document.getElementById("r-dl-inv").addEventListener("click", async () => {
    try {
      await downloadExcel("/api/export/inventory", {}, "inventory_report.xlsx");
      toast("فایل اکسل کامل موجودی دانلود شد.", "success");
    } catch (err) {
      toast(err.message, "error");
    }
  });

  try {
    const catData = await apiFetch("/api/categories");
    populateCategorySelects(
      document.getElementById("ex-parent-cat"),
      document.getElementById("ex-sub-cat"),
      catData.categories || [],
      true
    );
  } catch (err) {
    toast(err.message, "error");
  }

  document.getElementById("ex-inv-count-btn").addEventListener("click", async () => {
    try {
      const params = { ...getInventoryExportFilters(), page: 1, page_size: 1 };
      const data = await apiFetch(`/api/items${buildQuery(params)}`);
      document.getElementById("ex-inv-count-msg").textContent =
        `${fmtQty(data.total)} قلم قطعه با فیلترهای انتخابی منطبق است.`;
    } catch (err) {
      toast(err.message, "error");
    }
  });

  document.getElementById("ex-inv-dl-btn").addEventListener("click", async () => {
    try {
      const qs = buildQuery(getInventoryExportFilters());
      await downloadExcel(`/api/export/inventory${qs}`, {}, "inventory_report.xlsx");
      toast("فایل اکسل موجودی دریافت شد.", "success");
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
});
