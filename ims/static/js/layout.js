import { apiFetch } from "./api.js";
import { initJalaliDatepickers } from "./jalali_datepicker.js";

document.addEventListener("DOMContentLoaded", () => {
  initJalaliDatepickers();
  const sidebar = document.getElementById("app-sidebar");
  const backdrop = document.getElementById("sidebar-backdrop");
  const openBtn = document.getElementById("sidebar-open-btn");
  const closeBtn = document.getElementById("sidebar-close-btn");
  const logoutBtn = document.getElementById("logout-btn");

  const setDrawerOpen = (open) => {
    if (!sidebar || !backdrop) return;
    sidebar.classList.toggle("open", open);
    backdrop.classList.toggle("open", open);
    if (openBtn) openBtn.setAttribute("aria-expanded", String(open));
  };

  if (openBtn) openBtn.addEventListener("click", () => setDrawerOpen(true));
  if (closeBtn) closeBtn.addEventListener("click", () => setDrawerOpen(false));
  if (backdrop) backdrop.addEventListener("click", () => setDrawerOpen(false));

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      setDrawerOpen(false);
    }
  });

  if (logoutBtn) {
    logoutBtn.addEventListener("click", async () => {
      try {
        await apiFetch("/api/auth/logout", { method: "POST" });
      } finally {
        window.location.href = "/login";
      }
    });
  }
});
