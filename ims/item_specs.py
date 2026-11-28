"""Centralized specification schema, validation, and formatting for all IMS item types."""

from decimal import Decimal
from ims.db import AppError
from ims.utils import (
    clean_text,
    normalize_mounting_type,
    normalize_persian_text,
    parse_positive_mm,
)

SPEC_TYPES_ORDER = (
    "electronic_item",
    "screw",
    "nut",
    "spacer",
    "washer",
    "o_ring",
)

_ELECTRONIC_ROOT_KEYS = {
    "electronic",
    "electronics",
    "الکترونیک",
    "الکترونیکی",
    "قطعات الکترونیک",
    "قطعات الکترونیکی",
}

_MECHANICAL_ROOT_KEYS = {
    "mechanical",
    "mechanics",
    "مکانیک",
    "مکانیکی",
    "قطعات مکانیک",
    "قطعات مکانیکی",
}

_MECHANICAL_LEAF_MAP = {
    "spacer": "spacer",
    "spacers": "spacer",
    "اسپیسر": "spacer",
    "اسپیسرها": "spacer",
    "screw": "screw",
    "screws": "screw",
    "پیچ": "screw",
    "پیچ‌ها": "screw",
    "پیچ ها": "screw",
    "nut": "nut",
    "nuts": "nut",
    "مهره": "nut",
    "مهره‌ها": "nut",
    "مهره ها": "nut",
    "washer": "washer",
    "washers": "washer",
    "واشر": "washer",
    "واشرها": "washer",
    "o-ring": "o_ring",
    "o_ring": "o_ring",
    "oring": "o_ring",
    "o-rings": "o_ring",
    "o_rings": "o_ring",
    "orings": "o_ring",
    "اورینگ": "o_ring",
    "او-رینگ": "o_ring",
    "اورینگ‌ها": "o_ring",
    "اورینگ ها": "o_ring",
}

_MATERIAL_LABELS_FA = {
    "STAINLESS_STEEL": "استیل ضدزنگ (Stainless Steel)",
    "PLASTIC": "پلاستیک (Plastic)",
    "BLACK": "مشکی (Black)",
    "WHITE": "سفید / گالوانیزه (White)",
    "IRON": "آهن (Iron)",
    "PAPER": "کاغذی / فیبری (Paper)",
    "NBR": "NBR",
    "VITON": "وایتون (VITON)",
    "SILICONE": "سیلیکون (SILICONE)",
}

_MATERIAL_SYNONYMS = {
    "stainless_steel": "STAINLESS_STEEL",
    "stainless steel": "STAINLESS_STEEL",
    "stainless": "STAINLESS_STEEL",
    "ss": "STAINLESS_STEEL",
    "استیل": "STAINLESS_STEEL",
    "استیل ضدزنگ": "STAINLESS_STEEL",
    "استیل ضد زنگ": "STAINLESS_STEEL",
    "استنلس": "STAINLESS_STEEL",
    "استنلس استیل": "STAINLESS_STEEL",
    "plastic": "PLASTIC",
    "nylon": "PLASTIC",
    "پلاستیک": "PLASTIC",
    "پلاستیکی": "PLASTIC",
    "نایلون": "PLASTIC",
    "نایلونی": "PLASTIC",
    "black": "BLACK",
    "مشکی": "BLACK",
    "سیاه": "BLACK",
    "خشکه": "BLACK",
    "white": "WHITE",
    "سفید": "WHITE",
    "گالوانیزه": "WHITE",
    "iron": "IRON",
    "steel": "IRON",
    "آهن": "IRON",
    "آهنی": "IRON",
    "اهن": "IRON",
    "اهنی": "IRON",
    "فولاد": "IRON",
    "فولادی": "IRON",
    "paper": "PAPER",
    "کاغذی": "PAPER",
    "کاغذ": "PAPER",
    "فیبری": "PAPER",
    "فیبر": "PAPER",
    "nbr": "NBR",
    "لاستیک": "NBR",
    "لاستیکی": "NBR",
    "ان بی آر": "NBR",
    "viton": "VITON",
    "وایتون": "VITON",
    "ویتون": "VITON",
    "silicone": "SILICONE",
    "سیلیکون": "SILICONE",
    "سیلیکونی": "SILICONE",
}

_SPACER_TYPE_SYNONYMS = {
    "f": "F",
    "female-male": "F",
    "male-female": "F",
    "نری مادگی": "F",
    "نری-مادگی": "F",
    "مادگی نری": "F",
    "مادگی-نری": "F",
    "h": "H",
    "hex": "H",
    "female-female": "H",
    "دو سر مادگی": "H",
    "دوسر مادگی": "H",
    "مادگی مادگی": "H",
    "مادگی-مادگی": "H",
    "شش گوش": "H",
    "شش‌گوش": "H",
}

_WASHER_TYPE_SYNONYMS = {
    "plain": "PLAIN",
    "flat": "PLAIN",
    "تخت": "PLAIN",
    "ساده": "PLAIN",
    "معمولی": "PLAIN",
    "spring": "SPRING",
    "lock": "SPRING",
    "فنری": "SPRING",
    "قفل شو": "SPRING",
    "قفل‌شو": "SPRING",
}

_SCREW_HEAD_SYNONYMS = {
    "سرخزینه": "سرخزینه",
    "سر خزینه": "سرخزینه",
    "countersunk": "سرخزینه",
    "flat": "سرخزینه",
    "آلنی": "آلنی",
    "النی": "آلنی",
    "socket": "آلنی",
    "allen": "آلنی",
    "قارچی": "قارچی",
    "mushroom": "قارچی",
    "pan": "قارچی",
    "button": "قارچی",
    "مغزی": "مغزی",
    "set": "مغزی",
    "grub": "مغزی",
}

_SCREW_DRIVE_SYNONYMS = {
    "چهارسو": "چهارسو",
    "چهار سو": "چهارسو",
    "phillips": "چهارسو",
    "ph": "چهارسو",
    "آلنی": "آلنی",
    "النی": "آلنی",
    "hex": "آلنی",
    "allen": "آلنی",
}


def _opt(value: str, label_fa: str, label_en: str | None = None) -> dict:
    return {
        "value": value,
        "label_fa": label_fa,
        "label_en": label_en or value,
    }


SPEC_DEFINITIONS: dict[str, dict] = {
    "electronic_item": {
        "key": "electronic_item",
        "table": "electronic_item",
        "root_category": "Electronic",
        "default_subcategory": "Other electronic components",
        "sheet_name": "Electronic Items",
        "label_fa": "قطعات الکترونیک",
        "label_en": "Electronic Items",
        "fields": [
            {
                "name": "model",
                "label_fa": "مدل / پارت نامبر / مقدار",
                "label_en": "Model / Value",
                "kind": "text",
                "required": False,
                "max_len": 150,
                "excel_header": "Model / Value",
                "excel_aliases": ("model", "part", "name", "item_name", "item name", "value", "model / value"),
            },
            {
                "name": "package_size",
                "label_fa": "سایز پکیج (Package Size)",
                "label_en": "Package Size",
                "kind": "text",
                "required": False,
                "max_len": 50,
                "placeholder": "مثلاً 0603، 0805 یا TQFP-32",
                "excel_header": "Package Size",
                "excel_aliases": ("package_size", "package size", "package", "footprint", "size"),
            },
            {
                "name": "mounting_type",
                "label_fa": "نوع نصب",
                "label_en": "Mounting Type",
                "kind": "enum",
                "required": False,
                "options": [
                    _opt("SMD", "SMD", "SMD"),
                    _opt("DIP", "DIP", "DIP"),
                ],
                "excel_header": "Mounting Type",
                "excel_aliases": ("mounting_type", "mounting type", "mounting", "mount"),
            },
            {
                "name": "voltage",
                "label_fa": "ولتاژ",
                "label_en": "Voltage",
                "kind": "text",
                "required": False,
                "max_len": 80,
                "excel_header": "Voltage",
                "excel_aliases": ("voltage", "volt", "rated_voltage"),
            },
            {
                "name": "material",
                "label_fa": "متریال",
                "label_en": "Material",
                "kind": "text",
                "required": False,
                "max_len": 100,
                "excel_header": "Material",
                "excel_aliases": ("material",),
            },
        ],
    },
    "screw": {
        "key": "screw",
        "table": "screw",
        "root_category": "Mechanical",
        "default_subcategory": "Screw",
        "sheet_name": "Screws",
        "label_fa": "پیچ",
        "label_en": "Screws",
        "fields": [
            {
                "name": "diameter",
                "label_fa": "قطر",
                "label_en": "Diameter",
                "kind": "mm",
                "unit": "mm",
                "required": True,
                "excel_header": "Diameter (mm)",
                "excel_aliases": ("diameter", "diameter (mm)", "dia", "d"),
            },
            {
                "name": "length",
                "label_fa": "طول",
                "label_en": "Length",
                "kind": "mm",
                "unit": "mm",
                "required": True,
                "excel_header": "Length (mm)",
                "excel_aliases": ("length", "length (mm)", "len", "l"),
            },
            {
                "name": "material",
                "label_fa": "جنس / متریال",
                "label_en": "Material",
                "kind": "enum",
                "required": False,
                "options": [
                    _opt("STAINLESS_STEEL", _MATERIAL_LABELS_FA["STAINLESS_STEEL"], "STAINLESS_STEEL"),
                    _opt("BLACK", _MATERIAL_LABELS_FA["BLACK"], "BLACK"),
                    _opt("WHITE", _MATERIAL_LABELS_FA["WHITE"], "WHITE"),
                ],
                "excel_header": "Material",
                "excel_aliases": ("material",),
            },
            {
                "name": "head_type",
                "label_fa": "نوع سر پیچ",
                "label_en": "Head Type",
                "kind": "enum",
                "required": False,
                "options": [
                    _opt("سرخزینه", "سرخزینه", "سرخزینه"),
                    _opt("آلنی", "آلنی", "آلنی"),
                    _opt("قارچی", "قارچی", "قارچی"),
                    _opt("مغزی", "مغزی", "مغزی"),
                ],
                "excel_header": "Head Type",
                "excel_aliases": ("head_type", "head type", "head"),
            },
            {
                "name": "drive_type",
                "label_fa": "نوع آچارخور (درایو)",
                "label_en": "Drive Type",
                "kind": "enum",
                "required": False,
                "options": [
                    _opt("چهارسو", "چهارسو", "چهارسو"),
                    _opt("آلنی", "آلنی", "آلنی"),
                ],
                "excel_header": "Drive Type",
                "excel_aliases": ("drive_type", "drive type", "drive"),
            },
        ],
    },
    "nut": {
        "key": "nut",
        "table": "nut",
        "root_category": "Mechanical",
        "default_subcategory": "Nut",
        "sheet_name": "Nuts",
        "label_fa": "مهره",
        "label_en": "Nuts",
        "fields": [
            {
                "name": "diameter",
                "label_fa": "قطر",
                "label_en": "Diameter",
                "kind": "mm",
                "unit": "mm",
                "required": True,
                "excel_header": "Diameter (mm)",
                "excel_aliases": ("diameter", "diameter (mm)", "dia", "d"),
            },
            {
                "name": "material",
                "label_fa": "جنس / متریال",
                "label_en": "Material",
                "kind": "enum",
                "required": False,
                "options": [
                    _opt("STAINLESS_STEEL", _MATERIAL_LABELS_FA["STAINLESS_STEEL"], "STAINLESS_STEEL"),
                    _opt("IRON", _MATERIAL_LABELS_FA["IRON"], "IRON"),
                    _opt("PLASTIC", _MATERIAL_LABELS_FA["PLASTIC"], "PLASTIC"),
                ],
                "excel_header": "Material",
                "excel_aliases": ("material",),
            },
        ],
    },
    "spacer": {
        "key": "spacer",
        "table": "spacer",
        "root_category": "Mechanical",
        "default_subcategory": "Spacer",
        "sheet_name": "Spacers",
        "label_fa": "اسپیسر",
        "label_en": "Spacers",
        "fields": [
            {
                "name": "diameter",
                "label_fa": "قطر",
                "label_en": "Diameter",
                "kind": "mm",
                "unit": "mm",
                "required": True,
                "excel_header": "Diameter (mm)",
                "excel_aliases": ("diameter", "diameter (mm)", "dia", "d"),
            },
            {
                "name": "length",
                "label_fa": "طول",
                "label_en": "Length",
                "kind": "mm",
                "unit": "mm",
                "required": True,
                "excel_header": "Length (mm)",
                "excel_aliases": ("length", "length (mm)", "len", "l"),
            },
            {
                "name": "material",
                "label_fa": "جنس / متریال",
                "label_en": "Material",
                "kind": "enum",
                "required": False,
                "options": [
                    _opt("STAINLESS_STEEL", _MATERIAL_LABELS_FA["STAINLESS_STEEL"], "STAINLESS_STEEL"),
                    _opt("PLASTIC", _MATERIAL_LABELS_FA["PLASTIC"], "PLASTIC"),
                ],
                "excel_header": "Material",
                "excel_aliases": ("material",),
            },
            {
                "name": "spacer_type",
                "label_fa": "نوع اسپیسر",
                "label_en": "Spacer Type",
                "kind": "enum",
                "required": False,
                "options": [
                    _opt("F", "نری-مادگی (F)", "F"),
                    _opt("H", "دوسر مادگی (H)", "H"),
                ],
                "excel_header": "Spacer Type",
                "excel_aliases": ("spacer_type", "spacer type", "type"),
            },
        ],
    },
    "washer": {
        "key": "washer",
        "table": "washer",
        "root_category": "Mechanical",
        "default_subcategory": "Washer",
        "sheet_name": "Washers",
        "label_fa": "واشر",
        "label_en": "Washers",
        "fields": [
            {
                "name": "diameter",
                "label_fa": "قطر",
                "label_en": "Diameter",
                "kind": "mm",
                "unit": "mm",
                "required": True,
                "excel_header": "Diameter (mm)",
                "excel_aliases": ("diameter", "diameter (mm)", "dia", "d"),
            },
            {
                "name": "washer_type",
                "label_fa": "نوع واشر",
                "label_en": "Washer Type",
                "kind": "enum",
                "required": False,
                "options": [
                    _opt("PLAIN", "تخت (PLAIN)", "PLAIN"),
                    _opt("SPRING", "فنری (SPRING)", "SPRING"),
                ],
                "excel_header": "Washer Type",
                "excel_aliases": ("washer_type", "washer type", "type"),
            },
            {
                "name": "material",
                "label_fa": "جنس / متریال",
                "label_en": "Material",
                "kind": "enum",
                "required": False,
                "options": [
                    _opt("STAINLESS_STEEL", _MATERIAL_LABELS_FA["STAINLESS_STEEL"], "STAINLESS_STEEL"),
                    _opt("IRON", _MATERIAL_LABELS_FA["IRON"], "IRON"),
                    _opt("PLASTIC", _MATERIAL_LABELS_FA["PLASTIC"], "PLASTIC"),
                    _opt("PAPER", _MATERIAL_LABELS_FA["PAPER"], "PAPER"),
                ],
                "excel_header": "Material",
                "excel_aliases": ("material",),
            },
        ],
    },
    "o_ring": {
        "key": "o_ring",
        "table": "o_ring",
        "root_category": "Mechanical",
        "default_subcategory": "O-Ring",
        "sheet_name": "O-Rings",
        "label_fa": "اورینگ",
        "label_en": "O-Rings",
        "fields": [
            {
                "name": "inner_diameter",
                "label_fa": "قطر داخلی",
                "label_en": "Inner Diameter",
                "kind": "mm",
                "unit": "mm",
                "required": True,
                "excel_header": "Inner Diameter (mm)",
                "excel_aliases": ("inner_diameter", "inner diameter", "inner diameter (mm)", "id", "d_in"),
            },
            {
                "name": "outer_diameter",
                "label_fa": "قطر خارجی",
                "label_en": "Outer Diameter",
                "kind": "mm",
                "unit": "mm",
                "required": True,
                "excel_header": "Outer Diameter (mm)",
                "excel_aliases": ("outer_diameter", "outer diameter", "outer diameter (mm)", "od", "d_out"),
            },
            {
                "name": "cross_section",
                "label_fa": "ضخامت مقطع (محاسبه خودکار)",
                "label_en": "Cross Section",
                "kind": "computed_mm",
                "unit": "mm",
                "required": False,
                "read_only": True,
                "excel_header": "Cross Section (mm)",
                "excel_aliases": (),
            },
            {
                "name": "material",
                "label_fa": "جنس / متریال",
                "label_en": "Material",
                "kind": "enum",
                "required": False,
                "options": [
                    _opt("NBR", "NBR", "NBR"),
                    _opt("VITON", "وایتون (VITON)", "VITON"),
                    _opt("SILICONE", "سیلیکون (SILICONE)", "SILICONE"),
                ],
                "excel_header": "Material",
                "excel_aliases": ("material",),
            },
        ],
    },
}


def get_spec_definition(spec_type: str) -> dict:
    """Return the specification definition for spec_type or raise AppError."""
    if spec_type not in SPEC_DEFINITIONS:
        raise AppError(f"Unsupported item specification type: '{spec_type}'.")
    return SPEC_DEFINITIONS[spec_type]


def is_electronic_root_name(name: str | None) -> bool:
    norm = normalize_persian_text(clean_text(name))
    return bool(norm and norm.lower() in _ELECTRONIC_ROOT_KEYS)


def is_mechanical_root_name(name: str | None) -> bool:
    norm = normalize_persian_text(clean_text(name))
    return bool(norm and norm.lower() in _MECHANICAL_ROOT_KEYS)


def resolve_spec_type(
    root_name: str | None,
    leaf_name: str | None,
    is_leaf: bool = True,
    explicit_spec_type: str | None = None,
) -> str | None:
    """Map category metadata/hierarchy names dynamically to one of the 6 spec table keys."""
    if not is_leaf:
        return None
    if explicit_spec_type in SPEC_DEFINITIONS:
        return explicit_spec_type
    if not root_name:
        return None
    root_key = (normalize_persian_text(clean_text(root_name)) or "").lower()
    leaf_key = (normalize_persian_text(clean_text(leaf_name)) or "").lower()
    if root_key in _ELECTRONIC_ROOT_KEYS:
        return "electronic_item"
    if root_key in _MECHANICAL_ROOT_KEYS:
        return _MECHANICAL_LEAF_MAP.get(leaf_key)
    return None


def _normalize_enum(raw_val, field_name: str, allowed: tuple[str, ...], synonyms: dict[str, str]) -> str | None:
    if raw_val is None:
        return None
    cleaned = normalize_persian_text(clean_text(raw_val))
    if not cleaned:
        return None
    if cleaned in allowed:
        return cleaned
    lowered = cleaned.lower()
    if lowered in synonyms and synonyms[lowered] in allowed:
        return synonyms[lowered]
    uppered = cleaned.upper()
    if uppered in allowed:
        return uppered
    raise AppError(
        f"Invalid {field_name} '{cleaned}'. Allowed values: {', '.join(allowed)}."
    )


def compute_o_ring_cross_section(inner_diameter: Decimal, outer_diameter: Decimal) -> Decimal:
    """Compute O-Ring cross section = (outer_diameter - inner_diameter) / 2."""
    return ((outer_diameter - inner_diameter) / Decimal("2")).quantize(Decimal("0.001"))


def validate_specs(spec_type: str, raw_specs: dict | None) -> dict:
    """Validate and normalize specification fields strictly for spec_type."""
    defn = get_spec_definition(spec_type)
    raw = raw_specs if isinstance(raw_specs, dict) else {}
    cleaned: dict = {}

    for field in defn["fields"]:
        fname = field["name"]
        kind = field["kind"]
        if kind == "computed_mm":
            continue

        val = raw.get(fname)
        if spec_type == "electronic_item" and fname == "package_size" and val is None and "size" in raw:
            val = raw.get("size")

        if kind == "text":
            cleaned[fname] = clean_text(val, max_len=field.get("max_len"))
        elif kind == "mm":
            if field.get("required"):
                cleaned[fname] = parse_positive_mm(val, field["label_en"])
            else:
                from ims.utils import parse_optional_mm
                cleaned[fname] = parse_optional_mm(val, field["label_en"])
        elif kind == "enum":
            allowed = tuple(opt["value"] for opt in field["options"])
            if spec_type == "electronic_item" and fname == "mounting_type":
                cleaned[fname] = normalize_mounting_type(val)
            elif fname == "material":
                cleaned[fname] = _normalize_enum(val, field["label_en"], allowed, _MATERIAL_SYNONYMS)
            elif fname == "spacer_type":
                cleaned[fname] = _normalize_enum(val, field["label_en"], allowed, _SPACER_TYPE_SYNONYMS)
            elif fname == "washer_type":
                cleaned[fname] = _normalize_enum(val, field["label_en"], allowed, _WASHER_TYPE_SYNONYMS)
            elif fname == "head_type":
                cleaned[fname] = _normalize_enum(val, field["label_en"], allowed, _SCREW_HEAD_SYNONYMS)
            elif fname == "drive_type":
                cleaned[fname] = _normalize_enum(val, field["label_en"], allowed, _SCREW_DRIVE_SYNONYMS)
            else:
                cleaned[fname] = _normalize_enum(val, field["label_en"], allowed, {})

    if spec_type == "o_ring":
        inner_d = cleaned["inner_diameter"]
        outer_d = cleaned["outer_diameter"]
        if outer_d <= inner_d:
            raise AppError("O-Ring outer diameter (mm) must be strictly greater than inner diameter.")

    return cleaned


def format_mm(val) -> str:
    """Format a millimeter measurement cleanly without redundant trailing zeros."""
    if val is None or val == "":
        return ""
    dec = Decimal(str(val))
    normalized = format(dec.normalize(), "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return normalized


def _option_label_fa(spec_type: str, field_name: str, value: str | None) -> str:
    if value is None:
        return ""
    for field in SPEC_DEFINITIONS[spec_type]["fields"]:
        if field["name"] == field_name:
            for opt in field.get("options", ()):
                if opt["value"] == value:
                    return opt["label_fa"]
    return str(value)


def build_spec_summary(spec_type: str | None, specs: dict | None) -> str:
    """Build a concise human-readable Farsi specification summary string."""
    if not spec_type or spec_type not in SPEC_DEFINITIONS or not specs:
        return "—"

    if spec_type == "electronic_item":
        parts = [
            specs.get("model"),
            f"پکیج: {specs['package_size']}" if specs.get("package_size") else None,
            specs.get("mounting_type"),
            specs.get("voltage"),
            specs.get("material"),
        ]
        return " • ".join(p for p in parts if p) or "—"

    if spec_type == "spacer":
        parts = []
        if specs.get("diameter") is not None and specs.get("length") is not None:
            parts.append(f"قطر {format_mm(specs['diameter'])} × طول {format_mm(specs['length'])} mm")
        if specs.get("spacer_type"):
            parts.append(f"نوع {_option_label_fa('spacer', 'spacer_type', specs['spacer_type'])}")
        if specs.get("material"):
            parts.append(_option_label_fa("spacer", "material", specs["material"]))
        return " • ".join(parts) or "—"

    if spec_type == "screw":
        parts = []
        if specs.get("diameter") is not None and specs.get("length") is not None:
            parts.append(f"قطر {format_mm(specs['diameter'])} × طول {format_mm(specs['length'])} mm")
        if specs.get("head_type"):
            parts.append(f"سر {specs['head_type']}")
        if specs.get("drive_type"):
            parts.append(f"درایو {specs['drive_type']}")
        if specs.get("material"):
            parts.append(_option_label_fa("screw", "material", specs["material"]))
        return " • ".join(parts) or "—"

    if spec_type == "nut":
        parts = []
        if specs.get("diameter") is not None:
            parts.append(f"قطر {format_mm(specs['diameter'])} mm")
        if specs.get("material"):
            parts.append(_option_label_fa("nut", "material", specs["material"]))
        return " • ".join(parts) or "—"

    if spec_type == "washer":
        parts = []
        if specs.get("diameter") is not None:
            parts.append(f"قطر {format_mm(specs['diameter'])} mm")
        if specs.get("washer_type"):
            parts.append(_option_label_fa("washer", "washer_type", specs["washer_type"]))
        if specs.get("material"):
            parts.append(_option_label_fa("washer", "material", specs["material"]))
        return " • ".join(parts) or "—"

    if spec_type == "o_ring":
        parts = []
        if specs.get("inner_diameter") is not None and specs.get("outer_diameter") is not None:
            dim_text = f"داخلی {format_mm(specs['inner_diameter'])} × خارجی {format_mm(specs['outer_diameter'])}"
            if specs.get("cross_section") is not None:
                dim_text += f" × ضخامت {format_mm(specs['cross_section'])}"
            parts.append(f"{dim_text} mm")
        if specs.get("material"):
            parts.append(_option_label_fa("o_ring", "material", specs["material"]))
        return " • ".join(parts) or "—"

    return "—"


def build_display_name(
    spec_type: str | None,
    specs: dict | None,
    subcategory_name: str | None,
    item_code: str,
) -> str:
    """Build a short display label for an item across dashboards, carts, and BOM reports."""
    if spec_type == "electronic_item" and specs and specs.get("model"):
        if specs.get("package_size"):
            return f"{specs['model']} ({specs['package_size']})"
        return str(specs["model"])
    summary = build_spec_summary(spec_type, specs)
    if summary != "—":
        return f"{subcategory_name}: {summary}" if subcategory_name else summary
    return subcategory_name or item_code


def get_public_schema() -> dict:
    """Return JSON-serializable specification schema metadata for the UI."""
    types = {}
    for key in SPEC_TYPES_ORDER:
        defn = SPEC_DEFINITIONS[key]
        types[key] = {
            "key": defn["key"],
            "root_category": defn["root_category"],
            "default_subcategory": defn["default_subcategory"],
            "sheet_name": defn["sheet_name"],
            "label_fa": defn["label_fa"],
            "label_en": defn["label_en"],
            "fields": [
                {
                    "name": f["name"],
                    "label_fa": f["label_fa"],
                    "label_en": f["label_en"],
                    "kind": f["kind"],
                    "unit": f.get("unit"),
                    "required": bool(f.get("required")),
                    "read_only": bool(f.get("read_only")),
                    "max_len": f.get("max_len"),
                    "placeholder": f.get("placeholder"),
                    "options": f.get("options", []),
                }
                for f in defn["fields"]
            ],
        }
    return {"order": list(SPEC_TYPES_ORDER), "types": types}
