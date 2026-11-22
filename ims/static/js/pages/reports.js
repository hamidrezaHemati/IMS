import { apiFetch, buildQuery, downloadExcel } from "../api.js";
import { fmtCost, fmtQty, populateCategorySelects, toast, txTypeBadge } from "../ui.js";

async function loadAnalytics() {
  const params = {
    date_from: document.getElementById("r-from").value,
    date_to: document.getElementById("r-to").value,
  };

  try {
    const data = await apiFetch(`/api/reports/analytics${buildQuery(params)}`);

    const txBody = document.getElementById("r-tx-tbody");
    const moves = data.movement_summary || [];
    if (!moves.length) {
      txBody.innerHTML = `<tr><td colspan="5" class="empty-state">تراکنشی در بازه انتخابی ثبت نشده است.</td></tr>`;
    } else {
      txBody.innerHTML = moves
        .map(
          (m) => `
        <tr>
          <td>${txTypeBadge(m.transaction_type)}</td>
          <td class="text-right num">${fmtQty(m.tx_count)}</td>
          <td class="text-right num"><strong>${fmtQty(m.total_units)}</strong></td>
          <td class="text-right num">${fmtCost(m.known_cost_total)}</td>
          <td>${
            m.cost_complete
              ? `<span class="badge badge-success">کامل</span>`
              : `<span class="badge badge-warning">${fmtQty(m.unknown_cost_tx_count)} بدون قیمت</span>`
          }</td>
        </tr>`
        )
        .join("");
    }
  } catch (err) {
    toast(err.message, "error");
  }
}

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
  document.getElementById("r-apply-btn").addEventListener("click", loadAnalytics);
  document.getElementById("r-reset-btn").addEventListener("click", () => {
    document.getElementById("r-from").value = "";
    document.getElementById("r-to").value = "";
    loadAnalytics();
  });

  document.getElementById("r-dl-inv").addEventListener("click", async () => {
    try {
      await downloadExcel("/api/export/inventory", {}, "inventory_report.xlsx");
      toast("فایل اکسل کامل موجودی دانلود شد.", "success");
    } catch (err) {
      toast(err.message, "error");
    }
  });

  document.getElementById("r-dl-tx").addEventListener("click", async () => {
    const qs = buildQuery({
      date_from: document.getElementById("r-from").value,
      date_to: document.getElementById("r-to").value,
    });
    try {
      await downloadExcel(`/api/export/transactions${qs}`, {}, "transactions_report.xlsx");
      toast("فایل اکسل گردش‌های انبار دانلود شد.", "success");
    } catch (err) {
      toast(err.message, "error");
    }
  });

  try {
    const [catData, userData] = await Promise.all([
      apiFetch("/api/categories"),
      apiFetch("/api/users"),
    ]);
    populateCategorySelects(
      document.getElementById("ex-parent-cat"),
      document.getElementById("ex-sub-cat"),
      catData.categories || [],
      true
    );
    const userSel = document.getElementById("extx-user");
    (userData.users || []).forEach((u) => {
      const opt = document.createElement("option");
      opt.value = u.id;
      opt.textContent = `${u.first_name} ${u.last_name} (@${u.user_name})`;
      userSel.appendChild(opt);
    });
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

  document.getElementById("ex-tx-dl-btn").addEventListener("click", async () => {
    const qs = buildQuery({
      date_from: document.getElementById("extx-from").value,
      date_to: document.getElementById("extx-to").value,
      transaction_type: document.getElementById("extx-type").value,
      user_id: document.getElementById("extx-user").value,
      search: document.getElementById("extx-search").value,
    });
    try {
      await downloadExcel(`/api/export/transactions${qs}`, {}, "transactions_report.xlsx");
      toast("گزارش اکسل گردش‌ها دریافت شد.", "success");
    } catch (err) {
      toast(err.message, "error");
    }
  });

  loadAnalytics();
});
