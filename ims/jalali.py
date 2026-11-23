"""Zero-dependency Jalali (Shamsi) calendar utilities anchored to Iran Standard Time (UTC+03:30)."""

from datetime import date, datetime, timedelta, timezone
import re
from ims.db import AppError

TEHRAN_TZ = timezone(timedelta(hours=3, minutes=30))

_BREAKS = (
    -61, 9, 38, 199, 426, 686, 756, 818, 1111, 1181,
    1210, 1635, 2060, 2097, 2192, 2262, 2324, 2394, 2456, 3178,
)
_DIGIT_TRANSLATION = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_DATE_RE = re.compile(r"^(\d{4})[/-](\d{1,2})[/-](\d{1,2})$")


def _div(a: int, b: int) -> int:
    """Integer division truncating toward zero (matching JS/C/PostgreSQL semantics)."""
    return int(a / b) if (a < 0) ^ (b < 0) else a // b


def _mod(a: int, b: int) -> int:
    """Remainder paired with truncating integer division."""
    return a - _div(a, b) * b


def _jal_cal(jy: int) -> tuple[int, int, int]:
    gy = jy + 621
    leap_j = -14
    jp = _BREAKS[0]
    jump = 0
    for jm in _BREAKS[1:]:
        jump = jm - jp
        if jy < jm:
            break
        leap_j += _div(jump, 33) * 8 + _div(_mod(jump, 33), 4)
        jp = jm

    n = jy - jp
    leap_j += _div(n, 33) * 8 + _div(_mod(n, 33) + 3, 4)
    if _mod(jump, 33) == 4 and jump - n == 4:
        leap_j += 1

    leap_g = _div(gy, 4) - _div((_div(gy, 100) + 1) * 3, 4) - 150
    march = 20 + leap_j - leap_g

    if jump - n < 6:
        n = n - jump + _div(jump + 4, 33) * 33

    leap = _mod(_mod(n + 1, 33) - 1, 4)
    if leap == -1:
        leap = 4
    return leap, gy, march


def _g2d(gy: int, gm: int, gd: int) -> int:
    d = (
        _div((gy + _div(gm - 8, 6) + 100100) * 1461, 4)
        + _div(153 * _mod(gm + 9, 12) + 2, 5)
        + gd - 34840408
    )
    return d - _div(_div(gy + 100100 + _div(gm - 8, 6), 100) * 3, 4) + 752


def _d2g(jdn: int) -> tuple[int, int, int]:
    j = 4 * jdn + 139361631
    j += _div(_div(4 * jdn + 183187720, 146097) * 3, 4) * 4 - 3908
    i = _div(_mod(j, 1461), 4) * 5 + 308
    gd = _div(_mod(i, 153), 5) + 1
    gm = _mod(_div(i, 153), 12) + 1
    gy = _div(j, 1461) - 100100 + _div(8 - gm, 6)
    return gy, gm, gd


def _j2d(jy: int, jm: int, jd: int) -> int:
    _, gy, march = _jal_cal(jy)
    return _g2d(gy, 3, march) + (jm - 1) * 31 - _div(jm, 7) * (jm - 7) + jd - 1


def gregorian_to_jalali(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    """Convert Gregorian (gy, gm, gd) to Jalali (jy, jm, jd)."""
    jdn = _g2d(gy, gm, gd)
    gy2 = _d2g(jdn)[0]
    jy = gy2 - 621
    leap, _, march = _jal_cal(jy)
    jdn1f = _g2d(gy2, 3, march)
    k = jdn - jdn1f
    if k >= 0:
        if k <= 185:
            return jy, 1 + _div(k, 31), _mod(k, 31) + 1
        k -= 186
    else:
        jy -= 1
        k += 179
        if leap == 1:
            k += 1
    return jy, 7 + _div(k, 30), _mod(k, 30) + 1


def jalali_to_gregorian(jy: int, jm: int, jd: int) -> tuple[int, int, int]:
    """Convert Jalali (jy, jm, jd) to Gregorian (gy, gm, gd)."""
    return _d2g(_j2d(jy, jm, jd))


def is_jalali_leap(jy: int) -> bool:
    """Return True when the given Jalali year has 366 days."""
    return _j2d(jy + 1, 1, 1) - _j2d(jy, 1, 1) == 366


def jalali_month_length(jy: int, jm: int) -> int:
    """Return the exact number of days in Jalali month jm (1..12)."""
    if jm < 1 or jm > 12:
        raise ValueError(f"Jalali month out of range: {jm}")
    if jm <= 6:
        return 31
    if jm <= 11:
        return 30
    return 30 if is_jalali_leap(jy) else 29


def normalize_digits(text: str) -> str:
    """Translate Persian and Arabic-Indic numerals into ASCII 0-9."""
    return text.translate(_DIGIT_TRANSLATION)


def _to_tehran_dt(dt: datetime | None = None) -> datetime:
    if dt is None:
        return datetime.now(TEHRAN_TZ)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TEHRAN_TZ)


def format_jalali_datetime(dt: datetime | None, include_seconds: bool = True) -> str:
    """Format a datetime (assumed UTC if naive) as Tehran Jalali YYYY/MM/DD HH:MM(:SS)."""
    if dt is None:
        return ""
    local = _to_tehran_dt(dt)
    jy, jm, jd = gregorian_to_jalali(local.year, local.month, local.day)
    if include_seconds:
        return f"{jy:04d}/{jm:02d}/{jd:02d} {local.hour:02d}:{local.minute:02d}:{local.second:02d}"
    return f"{jy:04d}/{jm:02d}/{jd:02d} {local.hour:02d}:{local.minute:02d}"


def format_jalali_date(dt: datetime | None = None) -> str:
    """Format a datetime (default: now) as Tehran Jalali YYYY/MM/DD."""
    local = _to_tehran_dt(dt)
    jy, jm, jd = gregorian_to_jalali(local.year, local.month, local.day)
    return f"{jy:04d}/{jm:02d}/{jd:02d}"


def format_jalali_filename_stamp(dt: datetime | None = None) -> str:
    """Return a filesystem-safe Tehran Jalali timestamp stamp YYYYMMDD_HHMM."""
    local = _to_tehran_dt(dt)
    jy, jm, jd = gregorian_to_jalali(local.year, local.month, local.day)
    return f"{jy:04d}{jm:02d}{jd:02d}_{local.hour:02d}{local.minute:02d}"


def parse_filter_date_to_tehran_range(
    raw: str | None,
    field_name: str = "date",
) -> tuple[datetime, datetime] | None:
    """Parse a Jalali (YYYY/MM/DD) or Gregorian (YYYY-MM-DD) date into Tehran [start, end) bounds."""
    if raw is None:
        return None
    cleaned = normalize_digits(str(raw).strip())
    if not cleaned:
        return None

    m = _DATE_RE.match(cleaned)
    if not m:
        raise AppError(
            f"Invalid date for {field_name}: '{raw}'. Expected Jalali format YYYY/MM/DD."
        )

    year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))

    if 1200 <= year <= 1600:
        if month < 1 or month > 12:
            raise AppError(
                f"Invalid Jalali month in {field_name}: '{raw}'."
            )
        max_day = jalali_month_length(year, month)
        if day < 1 or day > max_day:
            raise AppError(
                f"Invalid Jalali day in {field_name}: '{raw}'."
            )
        gy, gm, gd = jalali_to_gregorian(year, month, day)
    elif 1900 <= year <= 2200:
        try:
            date(year, month, day)
        except ValueError as exc:
            raise AppError(f"Invalid date for {field_name}: '{raw}'.") from exc
        gy, gm, gd = year, month, day
    else:
        raise AppError(
            f"Invalid year in {field_name}: '{raw}'. Expected Jalali format YYYY/MM/DD."
        )

    start = datetime(gy, gm, gd, 0, 0, 0, tzinfo=TEHRAN_TZ)
    return start, start + timedelta(days=1)
