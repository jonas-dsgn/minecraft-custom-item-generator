"""Input validation for item names, namespaces and base item identifiers."""
from __future__ import annotations

import re

MAX_NAME_LENGTH = 100

_NAME_RE = re.compile(r"^[a-z0-9_-]+$")
_NAMESPACE_RE = re.compile(r"^[a-z0-9_.-]+$")
_BASE_ITEM_RE = re.compile(r"^(?:[a-z0-9_.-]+:)?[a-z0-9_./-]+$")

# Names Windows refuses to use as file names (with or without extension).
_WINDOWS_RESERVED = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


def _common_checks(value: str, what: str) -> str | None:
    if not value:
        return f"{what} is empty."
    if len(value) > MAX_NAME_LENGTH:
        return f"{what} is too long (max {MAX_NAME_LENGTH} characters)."
    if "/" in value or "\\" in value or ":" in value:
        return f"{what} must not contain path separators or drive/namespace markers."
    if ".." in value:
        return f"{what} must not contain '..'."
    return None


def validate_item_name(name: str) -> str | None:
    """Return an error message, or None if the item name is valid."""
    err = _common_checks(name, "Name")
    if err:
        return err
    if name.lower().endswith((".png", ".json")):
        return "Enter the name without a file extension."
    if name != name.lower():
        return "Name must be lowercase (Minecraft identifiers cannot contain uppercase letters)."
    if not _NAME_RE.fullmatch(name):
        return "Only lowercase letters, digits, '_' and '-' are allowed."
    if name in _WINDOWS_RESERVED:
        return "This name is reserved by Windows."
    return None


def validate_namespace(namespace: str) -> str | None:
    """Return an error message, or None if the namespace is valid."""
    if not namespace:
        return "Namespace is empty."
    if len(namespace) > MAX_NAME_LENGTH:
        return "Namespace is too long."
    if ".." in namespace or "/" in namespace or "\\" in namespace or ":" in namespace:
        return "Namespace must not contain path separators, ':' or '..'."
    if not _NAMESPACE_RE.fullmatch(namespace):
        return "Namespace may only contain lowercase letters, digits, '_', '-' and '.'."
    if namespace.split(".")[0] in _WINDOWS_RESERVED:
        return "Namespace is reserved by Windows."
    return None


def normalize_base_item(value: str) -> tuple[str | None, str | None]:
    """Return (normalized_id, error). A missing namespace defaults to 'minecraft:'."""
    value = value.strip()
    if not value:
        return None, "Base item is empty."
    if ".." in value or "\\" in value or value.count(":") > 1:
        return None, "Base item is not a valid item identifier."
    if not _BASE_ITEM_RE.fullmatch(value):
        return None, "Base item must look like 'minecraft:stick' (lowercase letters, digits, _ - . /)."
    if ":" not in value:
        value = f"minecraft:{value}"
    return value, None


def parse_names(text: str) -> tuple[list[str], list[tuple[str, str]]]:
    """Split raw input (newlines and/or commas) into valid names and errors.

    Whitespace is trimmed, empty entries and duplicates are ignored.
    Returns (valid_names, [(raw_name, error_message), ...]).
    """
    valid: list[str] = []
    errors: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw in re.split(r"[\r\n,]+", text):
        name = raw.strip()
        if not name or name in seen:
            continue
        seen.add(name)
        err = validate_item_name(name)
        if err:
            errors.append((name, err))
        else:
            valid.append(name)
    return valid, errors


# ------------------------------------------------------------ item_display settings

DISPLAY_MODES = (
    "fixed", "ground", "head", "gui",
    "firstperson_righthand", "firstperson_lefthand",
    "thirdperson_righthand", "thirdperson_lefthand",
)
DEFAULT_DISPLAY_MODE = "fixed"
DEFAULT_SCALE = (1.0, 1.0, 1.0)
MIN_SCALE = 0.001
MAX_SCALE = 1000.0


def parse_scale_value(text: str) -> tuple[float | None, str | None]:
    """Parse one scale axis. Returns (value, None) or (None, error message).

    Accepts plain decimals only (a comma is allowed as the decimal separator); no exponents,
    NaN or infinity, so the value can always be written as a valid SNBT float.
    """
    raw = text.strip().replace(",", ".")
    if not raw:
        return None, "is empty"
    if not re.fullmatch(r"[+-]?(\d+(\.\d*)?|\.\d+)", raw):
        return None, "is not a number"
    value = float(raw)
    if value < MIN_SCALE or value > MAX_SCALE:
        return None, f"must be between {MIN_SCALE:g} and {MAX_SCALE:g}"
    return round(value, 6), None


def check_display_settings(mode: str, scale: "tuple[float, float, float] | list[float]") -> str | None:
    """Return an error message for an invalid display mode or scale, else None."""
    if mode not in DISPLAY_MODES:
        return f"Unknown display mode '{mode}'."
    if len(scale) != 3:
        return "Scale needs exactly three values (X, Y, Z)."
    for axis, value in zip("XYZ", scale):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value \
                or not (MIN_SCALE <= value <= MAX_SCALE):
            return f"Scale {axis} must be a number between {MIN_SCALE:g} and {MAX_SCALE:g}."
    return None


def format_snbt_float(value: float) -> str:
    """1 -> '1.0f', 0.25 -> '0.25f'. Never uses exponent notation."""
    text = f"{round(float(value), 6):.6f}".rstrip("0")
    if text.endswith("."):
        text += "0"
    return text + "f"
