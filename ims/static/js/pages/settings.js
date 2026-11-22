import { apiFetch } from "../api.js";
import { toast } from "../ui.js";

document.addEventListener("DOMContentLoaded", () => {
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
});
