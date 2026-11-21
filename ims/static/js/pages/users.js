import { apiFetch } from "../api.js";
import { escapeHtml, fmtDate, fmtQty, toast } from "../ui.js";

async function loadUsers() {
  const tbody = document.getElementById("users-tbody");
  try {
    const data = await apiFetch("/api/users");
    const users = data.users || [];
    tbody.innerHTML = users
      .map(
        (u) => `
      <tr>
        <td class="num">${u.id}</td>
        <td><strong>${escapeHtml(u.first_name)} ${escapeHtml(u.last_name)}</strong></td>
        <td class="mono">@${escapeHtml(u.user_name)}</td>
        <td class="text-right num">${fmtQty(u.transaction_count)}</td>
        <td class="text-muted">${escapeHtml(fmtDate(u.created_at))}</td>
      </tr>`
      )
      .join("");
  } catch (err) {
    toast(err.message, "error");
  }
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("add-user-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await apiFetch("/api/users", {
        method: "POST",
        body: {
          first_name: document.getElementById("u-first").value,
          last_name: document.getElementById("u-last").value,
          user_name: document.getElementById("u-username").value,
          password: document.getElementById("u-password").value,
        },
      });
      e.target.reset();
      toast("کاربر جدید ایجاد شد.", "success");
      loadUsers();
    } catch (err) {
      toast(err.message, "error");
    }
  });

  document.getElementById("change-pw-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const newPw = document.getElementById("pw-new").value;
    const confirmPw = document.getElementById("pw-confirm").value;
    if (newPw !== confirmPw) {
      toast("رمز عبور جدید و تکرار آن یکسان نیستند.", "warning");
      return;
    }

    try {
      await apiFetch("/api/users/me/password", {
        method: "PUT",
        body: {
          current_password: document.getElementById("pw-current").value,
          new_password: newPw,
        },
      });
      e.target.reset();
      toast("رمز عبور با موفقیت تغییر یافت.", "success");
    } catch (err) {
      toast(err.message, "error");
    }
  });

  loadUsers();
});
