const _BREAKS = [
  -61, 9, 38, 199, 426, 686, 756, 818, 1111, 1181,
  1210, 1635, 2060, 2097, 2192, 2262, 2324, 2394, 2456, 3178,
];

export const JALALI_MONTH_NAMES = [
  "فروردین",
  "اردیبهشت",
  "خرداد",
  "تیر",
  "مرداد",
  "شهریور",
  "مهر",
  "آبان",
  "آذر",
  "دی",
  "بهمن",
  "اسفند",
];

const WEEKDAY_SHORT = ["ش", "ی", "د", "س", "چ", "پ", "ج"];
const TEHRAN_OFFSET_MS = 210 * 60 * 1000; // UTC+03:30 fixed year-round

function div(a, b) {
  return Math.trunc(a / b);
}

function mod(a, b) {
  return a - div(a, b) * b;
}

function jalCal(jy) {
  const gy = jy + 621;
  let leapJ = -14;
  let jp = _BREAKS[0];
  let jump = 0;

  for (let i = 1; i < _BREAKS.length; i += 1) {
    const jm = _BREAKS[i];
    jump = jm - jp;
    if (jy < jm) break;
    leapJ += div(jump, 33) * 8 + div(mod(jump, 33), 4);
    jp = jm;
  }

  let n = jy - jp;
  leapJ += div(n, 33) * 8 + div(mod(n, 33) + 3, 4);
  if (mod(jump, 33) === 4 && jump - n === 4) {
    leapJ += 1;
  }

  const leapG = div(gy, 4) - div((div(gy, 100) + 1) * 3, 4) - 150;
  const march = 20 + leapJ - leapG;

  if (jump - n < 6) {
    n = n - jump + div(jump + 4, 33) * 33;
  }

  let leap = mod(mod(n + 1, 33) - 1, 4);
  if (leap === -1) leap = 4;
  return { leap, gy, march };
}

function g2d(gy, gm, gd) {
  const d =
    div((gy + div(gm - 8, 6) + 100100) * 1461, 4) +
    div(153 * mod(gm + 9, 12) + 2, 5) +
    gd -
    34840408;
  return d - div(div(gy + 100100 + div(gm - 8, 6), 100) * 3, 4) + 752;
}

function d2g(jdn) {
  let j = 4 * jdn + 139361631;
  j += div(div(4 * jdn + 183187720, 146097) * 3, 4) * 4 - 3908;
  const i = div(mod(j, 1461), 4) * 5 + 308;
  const gd = div(mod(i, 153), 5) + 1;
  const gm = mod(div(i, 153), 12) + 1;
  const gy = div(j, 1461) - 100100 + div(8 - gm, 6);
  return [gy, gm, gd];
}

function j2d(jy, jm, jd) {
  const r = jalCal(jy);
  return g2d(r.gy, 3, r.march) + (jm - 1) * 31 - div(jm, 7) * (jm - 7) + jd - 1;
}

export function gregorianToJalali(gy, gm, gd) {
  const jdn = g2d(gy, gm, gd);
  const gy2 = d2g(jdn)[0];
  let jy = gy2 - 621;
  const r = jalCal(jy);
  const jdn1f = g2d(gy2, 3, r.march);
  let k = jdn - jdn1f;

  if (k >= 0) {
    if (k <= 185) {
      return [jy, 1 + div(k, 31), mod(k, 31) + 1];
    }
    k -= 186;
  } else {
    jy -= 1;
    k += 179;
    if (r.leap === 1) k += 1;
  }
  return [jy, 7 + div(k, 30), mod(k, 30) + 1];
}

export function jalaliToGregorian(jy, jm, jd) {
  return d2g(j2d(jy, jm, jd));
}

export function isJalaliLeap(jy) {
  return j2d(jy + 1, 1, 1) - j2d(jy, 1, 1) === 366;
}

export function jalaliMonthLength(jy, jm) {
  if (jm <= 6) return 31;
  if (jm <= 11) return 30;
  return isJalaliLeap(jy) ? 30 : 29;
}

export function normalizeDigits(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/[۰-۹]/g, (ch) => String(ch.charCodeAt(0) - 0x06f0))
    .replace(/[٠-٩]/g, (ch) => String(ch.charCodeAt(0) - 0x0660));
}

function pad2(n) {
  return String(n).padStart(2, "0");
}

function pad4(n) {
  return String(n).padStart(4, "0");
}

export function formatJalaliTuple(jy, jm, jd) {
  return `${pad4(jy)}/${pad2(jm)}/${pad2(jd)}`;
}

export function getTehranNowParts(dateInput = new Date()) {
  const base = dateInput instanceof Date ? dateInput : new Date(dateInput);
  if (Number.isNaN(base.getTime())) return null;
  const local = new Date(base.getTime() + TEHRAN_OFFSET_MS);
  const [jy, jm, jd] = gregorianToJalali(
    local.getUTCFullYear(),
    local.getUTCMonth() + 1,
    local.getUTCDate()
  );
  return {
    jy,
    jm,
    jd,
    hour: local.getUTCHours(),
    minute: local.getUTCMinutes(),
    second: local.getUTCSeconds(),
  };
}

export function formatJalaliDate(dateInput = new Date()) {
  const parts = getTehranNowParts(dateInput);
  if (!parts) return "";
  return formatJalaliTuple(parts.jy, parts.jm, parts.jd);
}

export function formatJalaliDateTime(dateInput, includeSeconds = false) {
  if (!dateInput) return "—";
  const parts = getTehranNowParts(dateInput);
  if (!parts) return String(dateInput);
  const d = formatJalaliTuple(parts.jy, parts.jm, parts.jd);
  const t = includeSeconds
    ? `${pad2(parts.hour)}:${pad2(parts.minute)}:${pad2(parts.second)}`
    : `${pad2(parts.hour)}:${pad2(parts.minute)}`;
  return `${d} ${t}`;
}

export function parseJalaliString(raw) {
  const cleaned = normalizeDigits(raw).trim();
  const match = cleaned.match(/^(\d{4})[/-](\d{1,2})[/-](\d{1,2})$/);
  if (!match) return null;
  const jy = Number(match[1]);
  const jm = Number(match[2]);
  const jd = Number(match[3]);
  if (jy < 1200 || jy > 1600 || jm < 1 || jm > 12) return null;
  if (jd < 1 || jd > jalaliMonthLength(jy, jm)) return null;
  return { jy, jm, jd };
}

let activePopover = null;
let activeInput = null;
let activeViewYear = 1405;
let activeViewMonth = 1;
let globalListenersAttached = false;

function closePopover() {
  if (activePopover) {
    activePopover.remove();
    activePopover = null;
  }
  activeInput = null;
}

function positionPopover(popover, input) {
  const rect = input.getBoundingClientRect();
  const popW = popover.offsetWidth || 280;
  const popH = popover.offsetHeight || 310;
  let top = rect.bottom + 6;
  if (top + popH > window.innerHeight - 8 && rect.top - popH - 6 >= 8) {
    top = rect.top - popH - 6;
  }
  let left = rect.right - popW;
  left = Math.max(8, Math.min(left, window.innerWidth - popW - 8));
  popover.style.top = `${Math.round(top)}px`;
  popover.style.left = `${Math.round(left)}px`;
}

function emitValueChange(input, nextVal) {
  const prev = input.value;
  input.value = nextVal;
  if (prev !== nextVal) {
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }
}

function renderPopover() {
  if (!activePopover || !activeInput) return;

  const today = getTehranNowParts();
  const selected = parseJalaliString(activeInput.value);
  const [gy1, gm1, gd1] = jalaliToGregorian(activeViewYear, activeViewMonth, 1);
  const startCol = (new Date(Date.UTC(gy1, gm1 - 1, gd1)).getUTCDay() + 1) % 7;
  const daysInMonth = jalaliMonthLength(activeViewYear, activeViewMonth);

  const minYear = Math.min(today.jy - 15, activeViewYear - 2);
  const maxYear = Math.max(today.jy + 10, activeViewYear + 2);

  const monthOptions = JALALI_MONTH_NAMES.map(
    (label, idx) =>
      `<option value="${idx + 1}" ${idx + 1 === activeViewMonth ? "selected" : ""}>${label}</option>`
  ).join("");

  let yearOptions = "";
  for (let y = minYear; y <= maxYear; y += 1) {
    yearOptions += `<option value="${y}" ${y === activeViewYear ? "selected" : ""}>${y}</option>`;
  }

  let dayCells = "";
  for (let blank = 0; blank < startCol; blank += 1) {
    dayCells += `<span class="jdate-empty"></span>`;
  }
  for (let day = 1; day <= daysInMonth; day += 1) {
    const isToday =
      today && today.jy === activeViewYear && today.jm === activeViewMonth && today.jd === day;
    const isSel =
      selected &&
      selected.jy === activeViewYear &&
      selected.jm === activeViewMonth &&
      selected.jd === day;
    const cls = ["jdate-day", isToday ? "is-today" : "", isSel ? "is-selected" : ""]
      .filter(Boolean)
      .join(" ");
    dayCells += `<button type="button" class="${cls}" data-jday="${day}">${day}</button>`;
  }

  activePopover.innerHTML = `
    <div class="jdate-header">
      <button type="button" class="btn btn-sm btn-ghost jdate-nav" data-jnav="-1" aria-label="ماه قبل">›</button>
      <div class="jdate-selects">
        <select class="select jdate-sel-month" aria-label="ماه">${monthOptions}</select>
        <select class="select jdate-sel-year num" aria-label="سال">${yearOptions}</select>
      </div>
      <button type="button" class="btn btn-sm btn-ghost jdate-nav" data-jnav="1" aria-label="ماه بعد">‹</button>
    </div>
    <div class="jdate-weekdays">
      ${WEEKDAY_SHORT.map((w) => `<span>${w}</span>`).join("")}
    </div>
    <div class="jdate-grid">
      ${dayCells}
    </div>
    <div class="jdate-footer">
      <button type="button" class="btn btn-sm btn-primary" data-jaction="today">امروز</button>
      <button type="button" class="btn btn-sm" data-jaction="clear">پاک کردن</button>
    </div>
  `;

  activePopover.querySelectorAll("[data-jnav]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const delta = Number(btn.dataset.jnav);
      activeViewMonth += delta;
      if (activeViewMonth < 1) {
        activeViewMonth = 12;
        activeViewYear -= 1;
      } else if (activeViewMonth > 12) {
        activeViewMonth = 1;
        activeViewYear += 1;
      }
      renderPopover();
      positionPopover(activePopover, activeInput);
    });
  });

  activePopover.querySelector(".jdate-sel-month").addEventListener("change", (e) => {
    activeViewMonth = Number(e.target.value);
    renderPopover();
    positionPopover(activePopover, activeInput);
  });

  activePopover.querySelector(".jdate-sel-year").addEventListener("change", (e) => {
    activeViewYear = Number(e.target.value);
    renderPopover();
    positionPopover(activePopover, activeInput);
  });

  activePopover.querySelectorAll("[data-jday]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const day = Number(btn.dataset.jday);
      const formatted = formatJalaliTuple(activeViewYear, activeViewMonth, day);
      const target = activeInput;
      closePopover();
      emitValueChange(target, formatted);
    });
  });

  activePopover.querySelector('[data-jaction="today"]').addEventListener("click", () => {
    const nowParts = getTehranNowParts();
    const formatted = formatJalaliTuple(nowParts.jy, nowParts.jm, nowParts.jd);
    const target = activeInput;
    closePopover();
    emitValueChange(target, formatted);
  });

  activePopover.querySelector('[data-jaction="clear"]').addEventListener("click", () => {
    const target = activeInput;
    closePopover();
    emitValueChange(target, "");
  });

  positionPopover(activePopover, activeInput);
}

function openPopoverFor(input) {
  if (activeInput === input && activePopover) return;
  closePopover();

  const parsed = parseJalaliString(input.value);
  const nowParts = getTehranNowParts();
  activeViewYear = parsed ? parsed.jy : nowParts.jy;
  activeViewMonth = parsed ? parsed.jm : nowParts.jm;
  activeInput = input;

  activePopover = document.createElement("div");
  activePopover.className = "jdate-popover";
  activePopover.setAttribute("role", "dialog");
  activePopover.setAttribute("aria-label", "تقویم شمسی");
  document.body.appendChild(activePopover);
  renderPopover();
}

function attachGlobalListeners() {
  if (globalListenersAttached) return;
  globalListenersAttached = true;

  document.addEventListener("mousedown", (e) => {
    if (!activePopover) return;
    const toggleTarget = e.target.closest("[data-jdate-toggle]");
    if (activePopover.contains(e.target) || e.target === activeInput) return;
    if (toggleTarget && activeInput && toggleTarget.dataset.jdateToggle === activeInput.id) return;
    closePopover();
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && activePopover) {
      closePopover();
    }
  });

  window.addEventListener("resize", () => {
    if (activePopover && activeInput) {
      positionPopover(activePopover, activeInput);
    }
  });
}

export function attachJalaliDatepicker(inputEl) {
  if (!inputEl || inputEl.dataset.jdateBound === "1") return;
  inputEl.dataset.jdateBound = "1";
  attachGlobalListeners();

  inputEl.addEventListener("focus", () => openPopoverFor(inputEl));
  inputEl.addEventListener("click", () => openPopoverFor(inputEl));

  inputEl.addEventListener("input", () => {
    const normalized = normalizeDigits(inputEl.value);
    if (normalized !== inputEl.value) {
      inputEl.value = normalized;
    }
    const parsed = parseJalaliString(inputEl.value);
    if (parsed && activePopover && activeInput === inputEl) {
      activeViewYear = parsed.jy;
      activeViewMonth = parsed.jm;
      renderPopover();
    }
  });

  inputEl.addEventListener("blur", () => {
    const trimmed = normalizeDigits(inputEl.value).trim();
    if (!trimmed) {
      inputEl.value = "";
      return;
    }
    const parsed = parseJalaliString(trimmed);
    if (parsed) {
      inputEl.value = formatJalaliTuple(parsed.jy, parsed.jm, parsed.jd);
    }
  });

  const toggleBtn = inputEl.id
    ? document.querySelector(`[data-jdate-toggle="${inputEl.id}"]`)
    : null;
  if (toggleBtn) {
    toggleBtn.addEventListener("click", () => {
      if (activeInput === inputEl && activePopover) {
        closePopover();
      } else {
        openPopoverFor(inputEl);
      }
    });
  }
}

export function initJalaliDatepickers(root = document) {
  root.querySelectorAll("[data-jalali-date]").forEach((el) => attachJalaliDatepicker(el));
}
