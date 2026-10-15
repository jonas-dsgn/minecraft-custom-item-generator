"""Formatting-code reference (shared by the name and lore editors) and insertion logic.

No Qt in here: the widget only feeds in cursor numbers and applies the result.
"""
from __future__ import annotations

from dataclasses import dataclass

from .text_components import (
    COLOR_CODES, COLOR_HEX, FORMAT_CODES, TEXT_SNBT, build_lore_line, format_component_arg,
)


@dataclass(frozen=True)
class CodeInfo:
    code: str                 # the character after '&', e.g. "6"
    label: str                # "Gold"
    kind: str                 # "color" | "format" | "reset"
    hex: str | None = None    # color preview, colors only

    @property
    def text(self) -> str:
        return "&" + self.code


def _title(name: str) -> str:
    return name.replace("_", " ").title()


COLOR_REFERENCE: tuple[CodeInfo, ...] = tuple(
    CodeInfo(code, _title(name), "color", COLOR_HEX[name]) for code, name in COLOR_CODES.items()
)

_FORMAT_LABELS = {
    "k": "Obfuscated", "l": "Bold", "m": "Strikethrough", "n": "Underline", "o": "Italic",
}
FORMAT_REFERENCE: tuple[CodeInfo, ...] = tuple(
    CodeInfo(code, _FORMAT_LABELS[code], "format") for code in ("k", "l", "m", "n", "o")
) + (CodeInfo("r", "Reset", "reset"),)

HEX_PREFIX = "&#"
LITERAL_AMPERSAND = "&&"


def hex_code(rgb: str) -> str:
    """'#FF8800' or 'ff8800' -> '&#ff8800'."""
    return HEX_PREFIX + rgb.lstrip("#").lower()


def contrast_text_color(color_hex: str) -> str:
    """Black or white, whichever is readable on the given #RRGGBB background."""
    r, g, b = (int(color_hex[i:i + 2], 16) for i in (1, 3, 5))
    return "#000000" if (0.299 * r + 0.587 * g + 0.114 * b) > 140 else "#FFFFFF"


def code_snippet(code: str, text_format: str = TEXT_SNBT) -> str:
    """The component syntax a code produces for the target version, e.g.
    '{text:"Text",color:"gold",italic:false}' (1.21.5+) or the JSON-string form (1.21.4)."""
    return format_component_arg(build_lore_line(f"&{code}Text"), text_format)


# ------------------------------------------------------------------ insertion

def plan_insert(caret: int, anchor: int, length: int) -> tuple[int, int]:
    """Where caret and selection anchor end up after inserting `length` characters at `caret`.

    Nothing is ever replaced: a selection stays selected (the same characters), and the code
    goes in at the caret.
      * no selection (anchor == caret): the caret moves behind the inserted code
      * caret at the END of the selection: the code lands after it, the selection is unchanged
      * caret at the START of the selection: the code lands before it, the selection moves with
        the text and the caret stays at its start (so repeated clicks keep their order)
    Returns (new_caret, new_anchor). Positions are in the editor's own units; only `length`
    (ASCII codes) is added, so UTF-16 vs code point differences cannot matter.
    """
    if anchor == caret:
        return caret + length, caret + length
    if anchor < caret:
        return caret, anchor
    return caret + length, anchor + length
