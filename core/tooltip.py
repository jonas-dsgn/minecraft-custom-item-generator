"""What an item's tooltip looks like in game, as lines of colored text segments.

Order (as in the 1.21 client): name, enchantments, lore, attribute modifiers grouped by slot,
"Unbreakable". Colors and number formats follow the vanilla client: rarity colors the name,
enchantments are gray (curses red), modifiers are blue when positive and red when negative,
numbers are rounded to two decimals, multiplier operations are shown as percentages.

This is a close representation, not the game's renderer: fonts, spacing and a few
version-specific details differ, and items whose own default rarity is not "common" (golden
apple, ...) show the rarity you chose, or white.
"""
from __future__ import annotations

from dataclasses import replace

from .attributes import (
    CURSES, SINGLE_LEVEL_ENCHANTMENTS, SLOT_HEADINGS, SLOT_TOOLTIP_ORDER, _path, _title,
    attribute_label, enchantment_label,
)
from .components import ItemProperties
from .text_components import Segment, parse_legacy

RARITY_COLORS = {"common": "white", "uncommon": "yellow", "rare": "aqua", "epic": "light_purple"}
_UPGRADE = {"common": "rare", "uncommon": "rare", "rare": "epic", "epic": "epic"}   # if enchanted
_ROMAN = ("I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X")

Line = list[Segment]          # an empty list is a blank line


def effective_rarity(rarity: str, enchanted: bool) -> str:
    base = rarity or "common"
    return _UPGRADE.get(base, base) if enchanted else base


def level_text(level: int) -> str:
    return _ROMAN[level - 1] if 1 <= level <= len(_ROMAN) else str(level)


def format_number(value: float) -> str:
    """Java's '#.##': up to two decimals, no trailing zeros."""
    text = f"{round(float(value), 2):.2f}".rstrip("0").rstrip(".")
    return text if text not in ("", "-0") else "0"


def _fill(segments: list[Segment], color: str) -> list[Segment]:
    """Segments without their own color take the line's default color."""
    return [seg if seg.color else replace(seg, color=color) for seg in segments]


def attribute_line(attr_type: str, amount: float, operation: str) -> Line | None:
    """One modifier line, e.g. '+7 Attack Damage' (blue) or '-10% Speed' (red). None for 0."""
    if amount == 0:
        return None
    if operation == "add_value":
        shown = amount * 10 if _path(attr_type) == "knockback_resistance" else amount
        suffix = ""
    else:
        shown, suffix = amount * 100, "%"
    sign, color = ("+", "blue") if shown > 0 else ("-", "red")
    return [Segment(f"{sign}{format_number(abs(shown))}{suffix} {attribute_label(attr_type)}",
                    color=color)]


def build_tooltip(base_item: str, display_name: str, props: ItemProperties) -> list[Line] | None:
    """Tooltip lines, or None when the tooltip is hidden (the 'Hide tooltip' option)."""
    if props.hide_tooltip:
        return None
    rarity = effective_rarity(props.rarity, bool(props.enchantments))
    name_color = RARITY_COLORS.get(rarity, "white")

    name = parse_legacy(display_name)
    lines: list[Line] = [_fill(name or [Segment(_title(_path(base_item)))], name_color)]

    for ench, level in props.enchantments:
        path = _path(ench)
        text = enchantment_label(ench)
        if not (level == 1 and path in SINGLE_LEVEL_ENCHANTMENTS):
            text += f" {level_text(level)}"
        lines.append([Segment(text, color="red" if path in CURSES else "gray")])

    for text in props.lore:
        lines.append(_fill(parse_legacy(text, strip=False), "dark_purple"))

    groups: dict[str, list[Line]] = {}
    for m in props.attributes:
        line = attribute_line(m.type, m.amount, m.operation)
        if line is not None and m.slot in SLOT_HEADINGS:
            groups.setdefault(m.slot, []).append(line)
    for slot in SLOT_TOOLTIP_ORDER:
        if slot in groups:
            lines.append([])
            lines.append([Segment(SLOT_HEADINGS[slot], color="gray")])
            lines.extend(groups[slot])

    if props.unbreakable:
        lines.append([Segment("Unbreakable", color="blue")])
    return lines


def item_traits(base_item: str, props: ItemProperties) -> list[str]:
    """Properties that are real but not part of the tooltip text (shown under the preview)."""
    traits: list[str] = []
    if props.glint or props.enchantments:
        traits.append("glint" if props.glint else "glint (enchanted)")
    if props.max_stack_size is not None:
        traits.append(f"stack {props.max_stack_size}")
    if props.max_damage is not None:
        traits.append(f"durability {props.max_damage}")
    if props.fire_resistant:
        traits.append("fire resistant")
    if props.custom_data.strip():
        traits.append("custom data")
    return traits
