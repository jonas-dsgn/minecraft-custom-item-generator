"""Legacy formatting codes (&6, &l, &#RRGGBB ...) -> Minecraft text components.

Output formats (the target version decides which one commands need):
  * "snbt": Minecraft 1.21.5+ commands take SNBT text components:
        custom_name={text:"Ancient Sword",color:"gold",italic:false}
  * "json": Minecraft 1.21.2-1.21.4 commands take a JSON string:
        custom_name='{"text":"Ancient Sword","color":"gold","italic":false}'
Data-pack JSON files (recipes) always take the component as a plain JSON object.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

TEXT_SNBT = "snbt"
TEXT_JSON = "json"

COLOR_CODES = {
    "0": "black", "1": "dark_blue", "2": "dark_green", "3": "dark_aqua",
    "4": "dark_red", "5": "dark_purple", "6": "gold", "7": "gray",
    "8": "dark_gray", "9": "blue", "a": "green", "b": "aqua",
    "c": "red", "d": "light_purple", "e": "yellow", "f": "white",
}
COLOR_HEX = {
    "black": "#000000", "dark_blue": "#0000AA", "dark_green": "#00AA00",
    "dark_aqua": "#00AAAA", "dark_red": "#AA0000", "dark_purple": "#AA00AA",
    "gold": "#FFAA00", "gray": "#AAAAAA", "dark_gray": "#555555",
    "blue": "#5555FF", "green": "#55FF55", "aqua": "#55FFFF",
    "red": "#FF5555", "light_purple": "#FF55FF", "yellow": "#FFFF55",
    "white": "#FFFFFF",
}
LORE_DEFAULT_COLOR = "#AA00AA"      # lore without a color code is dark purple in game
FORMAT_CODES = {
    "l": "bold", "o": "italic", "n": "underlined",
    "m": "strikethrough", "k": "obfuscated",
}
_FLAGS = ("bold", "italic", "underlined", "strikethrough", "obfuscated")
_HEX6 = re.compile(r"[0-9a-fA-F]{6}")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True)
class Segment:
    text: str
    color: str | None = None
    bold: bool = False
    italic: bool = False
    underlined: bool = False
    strikethrough: bool = False
    obfuscated: bool = False


def _fresh_state() -> dict[str, Any]:
    return {"color": None, **{flag: False for flag in _FLAGS}}


def parse_legacy(text: str, strip: bool = True) -> list[Segment]:
    """Split text with &-codes (or §-codes) into formatted segments.

    Like legacy Minecraft: a color code resets formatting, &r resets everything,
    '&&' is a literal '&', unknown codes are kept as plain text.
    `strip=False` keeps leading/trailing spaces (lore lines use it for indentation).
    """
    text = _CONTROL.sub("", text)
    if strip:
        text = text.strip()
    segments: list[Segment] = []
    buf: list[str] = []
    state = _fresh_state()

    def flush() -> None:
        if buf:
            segments.append(Segment("".join(buf), **state))
            buf.clear()

    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch in "&§" and i + 1 < n:
            nxt = text[i + 1]
            if ch == "&" and nxt == "&":
                buf.append("&")
                i += 2
                continue
            if nxt == "#" and _HEX6.fullmatch(text[i + 2:i + 8] or "x"):
                flush()
                state = _fresh_state()
                state["color"] = "#" + text[i + 2:i + 8].lower()
                i += 8
                continue
            code = nxt.lower()
            if code in COLOR_CODES:
                flush()
                state = _fresh_state()
                state["color"] = COLOR_CODES[code]
                i += 2
                continue
            if code in FORMAT_CODES:
                flush()
                state[FORMAT_CODES[code]] = True
                i += 2
                continue
            if code == "r":
                flush()
                state = _fresh_state()
                i += 2
                continue
        buf.append(ch)
        i += 1
    flush()
    return segments


def _segment_dict(seg: Segment) -> dict[str, Any]:
    d: dict[str, Any] = {"text": seg.text}
    if seg.color:
        d["color"] = seg.color
    for flag in _FLAGS:
        if getattr(seg, flag):
            d[flag] = True
    return d


def build_component(text: str) -> dict[str, Any] | None:
    """Return a text component for the display name, or None for 'no custom name'.

    Custom names are italic by default in-game; italic is switched off unless the
    text asks for it with &o.
    """
    segments = parse_legacy(text)
    if not segments:
        return None
    if len(segments) == 1:
        d = _segment_dict(segments[0])
        d.setdefault("italic", False)
        return d
    return {"text": "", "italic": False, "extra": [_segment_dict(s) for s in segments]}


def build_lore_line(text: str) -> dict[str, Any]:
    """One lore line as a text component. Never None: an empty line is a blank lore line.

    Same rules as the display name (italic is switched off unless the text asks for it with
    &o), but spaces are kept and an empty line stays an empty line. Without a color code the
    game draws lore in its default dark purple.
    """
    segments = parse_legacy(text, strip=False)
    if not segments:
        return {"text": "", "italic": False}
    if len(segments) == 1:
        d = _segment_dict(segments[0])
        d.setdefault("italic", False)
        return d
    return {"text": "", "italic": False, "extra": [_segment_dict(s) for s in segments]}


def find_unknown_codes(text: str) -> list[str]:
    """Codes that parse_legacy keeps as plain text, e.g. ['&z', '&#12'] (for warnings).

    '&&' (literal &) and a lone trailing '&' are valid and not reported.
    """
    text = _CONTROL.sub("", text)
    found: list[str] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch in "&§" and i + 1 < n:
            nxt = text[i + 1]
            if ch == "&" and nxt == "&":
                i += 2
                continue
            if nxt == "#":
                if _HEX6.fullmatch(text[i + 2:i + 8] or "x"):
                    i += 8
                    continue
                found.append(text[i:i + 2])
            elif nxt.lower() not in COLOR_CODES and nxt.lower() not in FORMAT_CODES and nxt.lower() != "r":
                found.append(text[i:i + 2])
        i += 1
    return found


# ---------------------------------------------------------------- serializers

def to_snbt(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(value, list):
        return "[" + ",".join(to_snbt(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{" + ",".join(f"{k}:{to_snbt(v)}" for k, v in value.items()) + "}"
    return str(value)


def to_json_string_arg(component: dict[str, Any]) -> str:
    """JSON text inside a single-quoted SNBT string (Minecraft <= 1.21.4)."""
    raw = json.dumps(component, ensure_ascii=False, separators=(",", ":"))
    return "'" + raw.replace("\\", "\\\\").replace("'", "\\'") + "'"


def format_component_arg(component: dict[str, Any], text_format: str) -> str:
    if text_format == TEXT_JSON:
        return to_json_string_arg(component)
    return to_snbt(component)


# -------------------------------------------------------------------- preview

def segments_to_html(segments: list[Segment], default_color: str = "#FFFFFF") -> str:
    """Rich text for the previews. Lore passes the game's default lore color (dark purple)."""
    from html import escape
    parts = []
    for seg in segments:
        color = COLOR_HEX.get(seg.color or "", seg.color or default_color)
        style = [f"color:{color}", "white-space:pre-wrap"]
        if seg.bold:
            style.append("font-weight:bold")
        if seg.italic:
            style.append("font-style:italic")
        deco = []
        if seg.underlined:
            deco.append("underline")
        if seg.strikethrough:
            deco.append("line-through")
        if deco:
            style.append("text-decoration:" + " ".join(deco))
        parts.append(f'<span style="{";".join(style)}">{escape(seg.text)}</span>')
    return "".join(parts)
