/**
 * Centralized API fetch and file download helpers.
 */

export async function apiFetch(url, options = {}) {
  const opts = { ...options };
  const isFormData = opts.body instanceof FormData;

  if (!isFormData && opts.body && typeof opts.body !== "string") {
    opts.headers = {
      "Content-Type": "application/json",
      ...(opts.headers || {}),
    };
    opts.body = JSON.stringify(opts.body);
  }

  const response = await fetch(url, opts);

  if (response.status === 401 && !url.startsWith("/api/auth/login")) {
    window.location.href = "/login";
    throw new Error("Authentication required.");
  }

  const contentType = response.headers.get("content-type") || "";
  let payload = null;
  if (contentType.includes("application/json")) {
    payload = await response.json();
  } else if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed (${response.status})`);
  }

  if (!response.ok) {
    const err = new Error(
      (payload && payload.error) || `Request failed (${response.status})`
    );
    err.status = response.status;
    err.code = payload && payload.code;
    err.details = payload && payload.details;
    throw err;
  }

  return payload;
}

export function buildQuery(params) {
  const sp = new URLSearchParams();
  Object.entries(params || {}).forEach(([k, v]) => {
    if (v !== null && v !== undefined && String(v).trim() !== "") {
      sp.set(k, String(v).trim());
    }
  });
  const qs = sp.toString();
  return qs ? `?${qs}` : "";
}

export async function downloadExcel(url, options = {}, fallbackName = "report.xlsx") {
  const opts = { ...options };
  if (opts.body && typeof opts.body !== "string" && !(opts.body instanceof FormData)) {
    opts.headers = {
      "Content-Type": "application/json",
      ...(opts.headers || {}),
    };
    opts.body = JSON.stringify(opts.body);
  }

  const response = await fetch(url, opts);
  if (response.status === 401) {
    window.location.href = "/login";
    throw new Error("Authentication required.");
  }
  if (!response.ok) {
    const contentType = response.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      const data = await response.json();
      throw new Error(data.error || "Export failed.");
    }
    throw new Error(`Export failed (${response.status})`);
  }

  const blob = await response.blob();
  const disp = response.headers.get("Content-Disposition") || "";
  const match = disp.match(/filename="?([^"]+)"?/i);
  const filename = match ? match[1] : fallbackName;

  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(objectUrl);
}
