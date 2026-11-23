"""Shared validation, parsing, and temporary upload utilities."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
import re
import time
import uuid
from werkzeug.utils import secure_filename
from ims.db import AppError


ALLOWED_MOUNTING_TYPES = ("SMD", "DIP")
_MM_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_PERSIAN_CHARS = str.maketrans({"ي": "ی", "ك": "ک", "\u200c": " "})


def normalize_persian_text(value: str | None) -> str | None:
    """Normalize Arabic Yeh/Kaf, ZWNJ, and whitespace for uniform Farsi matching."""
    if value is None:
        return None
    normalized = str(value).translate(_PERSIAN_CHARS)
    collapsed = re.sub(r"\s+", " ", normalized).strip()
    return collapsed or None


def parse_positive_mm(value, field_name: str = "dimension") -> Decimal:
    """Parse a strictly positive NUMERIC(10,3) millimeter measurement."""
    parsed = parse_optional_mm(value, field_name=field_name, require_positive=True)
    if parsed is None:
        raise AppError(f"{field_name} (mm) is required and must be greater than zero.")
    return parsed


def parse_optional_mm(
    value,
    field_name: str = "dimension",
    *,
    require_positive: bool = True,
) -> Decimal | None:
    """Parse an optional NUMERIC(10,3) millimeter value, rejecting non-numeric strings like 'M5'."""
    if value is None or isinstance(value, bool):
        if isinstance(value, bool):
            raise AppError(f"{field_name} (mm) must be a valid number.")
        return None
    if isinstance(value, float) and value != value:
        return None

    text = str(value).translate(_MM_DIGITS).strip()
    if not text:
        return None

    try:
        dec = value if isinstance(value, Decimal) else Decimal(text)
    except InvalidOperation as exc:
        raise AppError(
            f"{field_name} (mm) must be a valid numeric value in millimeters."
        ) from exc

    if not dec.is_finite():
        raise AppError(f"{field_name} (mm) must be a finite numeric value.")
    if require_positive and dec <= 0:
        raise AppError(f"{field_name} (mm) must be greater than zero.")
    if not require_positive and dec < 0:
        raise AppError(f"{field_name} (mm) cannot be negative.")

    quantized = dec.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    if require_positive and quantized <= 0:
        raise AppError(f"{field_name} (mm) must be greater than zero.")
    return quantized


def clean_text(value, max_len: int | None = None) -> str | None:
    """Normalize text values: strip whitespace and turn blanks into None."""
    if value is None:
        return None
    if isinstance(value, bool):
        text = str(value)
    elif isinstance(value, int):
        text = str(value)
    elif isinstance(value, float):
        if value != value:  # NaN
            return None
        if value.is_integer():
            text = str(int(value))
        else:
            text = f"{value:.10g}"
    else:
        text = str(value)

    text = text.strip()
    if not text:
        return None
    if max_len is not None and len(text) > max_len:
        raise AppError(f"Text exceeds maximum length of {max_len} characters.")
    return text


def normalize_mounting_type(value) -> str | None:
    """Normalize SMD/DIP mounting type case-insensitively or reject invalid values."""
    cleaned = clean_text(value)
    if cleaned is None:
        return None
    upper = cleaned.upper()
    if upper not in ALLOWED_MOUNTING_TYPES:
        raise AppError(
            f"Invalid mounting type '{cleaned}'. Allowed values: SMD, DIP."
        )
    return upper


def parse_positive_int(value, field_name: str = "quantity") -> int:
    """Parse a strictly positive integer, rejecting floats and booleans."""
    if value is None or isinstance(value, bool):
        raise AppError(f"{field_name} must be a positive integer.")

    if isinstance(value, int):
        parsed = value
    elif isinstance(value, float):
        if value != value or not value.is_integer():
            raise AppError(f"{field_name} must be a whole positive integer.")
        parsed = int(value)
    else:
        text = str(value).strip()
        if not text:
            raise AppError(f"{field_name} must be a positive integer.")
        try:
            dec = Decimal(text)
        except InvalidOperation as exc:
            raise AppError(f"{field_name} must be a positive integer.") from exc
        if dec != dec.to_integral_value():
            raise AppError(f"{field_name} must be a whole positive integer.")
        parsed = int(dec)

    if parsed <= 0:
        raise AppError(f"{field_name} must be greater than zero.")
    return parsed


def parse_nonnegative_int(value, field_name: str = "quantity") -> int:
    """Parse a non-negative integer (>= 0), rejecting floats and booleans."""
    if value is None or isinstance(value, bool):
        raise AppError(f"{field_name} must be a non-negative integer.")

    if isinstance(value, int):
        parsed = value
    elif isinstance(value, float):
        if value != value or not value.is_integer():
            raise AppError(f"{field_name} must be a whole integer.")
        parsed = int(value)
    else:
        text = str(value).strip()
        if not text:
            raise AppError(f"{field_name} must be a non-negative integer.")
        try:
            dec = Decimal(text)
        except InvalidOperation as exc:
            raise AppError(f"{field_name} must be a non-negative integer.") from exc
        if dec != dec.to_integral_value():
            raise AppError(f"{field_name} must be a whole integer.")
        parsed = int(dec)

    if parsed < 0:
        raise AppError(f"{field_name} cannot be negative.")
    return parsed


def parse_optional_price(value, field_name: str = "price") -> Decimal | None:
    """Parse a non-negative NUMERIC(18,4) price or return None if empty."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str) and not value.strip():
        return None

    try:
        dec = value if isinstance(value, Decimal) else Decimal(str(value).strip())
    except InvalidOperation as exc:
        raise AppError(f"{field_name} must be a valid non-negative number.") from exc

    if not dec.is_finite() or dec < 0:
        raise AppError(f"{field_name} must be a valid non-negative number.")

    return dec.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def parse_optional_int(value, field_name: str = "value") -> int | None:
    """Parse an integer if present, or None if blank."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool):
        raise AppError(f"{field_name} must be an integer.")
    try:
        return int(str(value).strip())
    except (ValueError, TypeError) as exc:
        raise AppError(f"{field_name} must be an integer.") from exc


def parse_bool_param(value) -> bool:
    """Interpret query parameter booleans cleanly."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def purge_old_uploads(upload_dir: str | Path, max_age_seconds: int = 3600) -> None:
    """Remove stale temporary Excel uploads older than max_age_seconds."""
    root = Path(upload_dir)
    if not root.exists():
        return
    cutoff = time.time() - max_age_seconds
    for entry in root.iterdir():
        if entry.is_file() and entry.stat().st_mtime < cutoff:
            try:
                entry.unlink()
            except OSError:
                pass


def save_uploaded_xlsx(file_storage, upload_dir: str | Path, prefix: str = "upload") -> tuple[str, Path]:
    """Validate and save an uploaded .xlsx file under a unique ID."""
    if not file_storage or not file_storage.filename:
        raise AppError("Please select an Excel (.xlsx) file to upload.")

    filename = secure_filename(file_storage.filename)
    if not filename.lower().endswith(".xlsx"):
        raise AppError("Only .xlsx Excel workbooks are supported.")

    root = Path(upload_dir)
    root.mkdir(parents=True, exist_ok=True)
    purge_old_uploads(root)

    upload_id = f"{prefix}_{uuid.uuid4().hex}"
    dest = root / f"{upload_id}.xlsx"
    file_storage.save(dest)
    return upload_id, dest


def resolve_uploaded_xlsx(upload_id: str, upload_dir: str | Path) -> Path:
    """Safely resolve a temporary upload_id inside upload_dir."""
    clean_id = (upload_id or "").strip()
    if not clean_id or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for ch in clean_id):
        raise AppError("Invalid or missing upload identifier.")

    path = Path(upload_dir) / f"{clean_id}.xlsx"
    if not path.exists():
        raise AppError("Uploaded Excel file expired or was not found. Please upload the file again.", status_code=404)
    return path
