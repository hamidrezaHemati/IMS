import { apiFetch, buildQuery, downloadExcel } from "../api.js";
import { escapeHtml, fmtCost, fmtQty, toast, txTypeBadge } from "../ui.js";

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

    const catBody = document.getElementById("r-cat-tbody");
    const cats = data.category_breakdown || [];
    if (!cats.length) {
      catBody.innerHTML = `<tr><td colspan="7" class="empty-state">هنوز هیچ قطعه‌ای در انبار ثبت نشده است.</td></tr>`;
    } else {
      catBody.innerHTML = cats
        .map(
          (c) => `
        <tr>
          <td><strong>${escapeHtml(c.category_name)}</strong></td>
          <td>${escapeHtml(c.subcategory_name || "—")}</td>
          <td class="text-right num">${fmtQty(c.distinct_items)}</td>
          <td class="text-right num"><strong>${fmtQty(c.total_quantity)}</strong></td>
          <td class="text-right num">${fmtQty(c.zero_stock_count)}</td>
          <td class="text-right num">
            ${fmtCost(c.wac_known_value)}
            ${!c.wac_complete ? `<div class="text-warning" style="font-size:0.75rem;">ناقص (${c.wac_missing_cost_items} مورد بدون قیمت)</div>` : ""}
          </td>
          <td class="text-right num">
            ${fmtCost(c.lpc_known_value)}
            ${!c.lpc_complete ? `<div class="text-warning" style="font-size:0.75rem;">ناقص (${c.lpc_missing_cost_items} مورد بدون قیمت)</div>` : ""}
          </td>
        </tr>`
        )
        .join("");
    }
  } catch (err) {
    toast(err.message, "error");
  }
}

document.addEventListener("DOMContentLoaded", () => {
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

  loadAnalytics();
});
