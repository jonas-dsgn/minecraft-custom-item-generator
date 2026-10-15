"""Attribute modifiers and enchantments: data, validation and syntax per target version.

Syntax by target version (both use the attribute ids introduced in 1.21.2, without 'generic.'):
  1.21.5+  attribute_modifiers=[{...},{...}]            enchantments={"minecraft:sharpness":5}
  1.21.4   attribute_modifiers={modifiers:[{...}]}      enchantments={levels:{"minecraft:sharpness":5}}
The 1.21.4 forms are the full records of that version (show_in_tooltip keeps its default); the
1.21.5 forms are what remained when the wrapper objects were removed. This tool has not been
run against a live game, so check a freshly generated item once on your target version.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

from .text_components import TEXT_JSON, TEXT_SNBT

MAX_ATTRIBUTES = 64
MAX_ENCHANT_LEVEL = 255

SLOTS = ("any", "mainhand", "offhand", "hand", "head", "chest", "legs", "feet", "armor", "body",
         "saddle")
SLOTS_SINCE_1_21_5 = frozenset({"saddle"})        # not valid on the 1.21.4 target
SLOT_LABELS = {
    "any": "Any slot", "mainhand": "Main hand", "offhand": "Off hand", "hand": "Either hand",
    "head": "Head", "chest": "Chest", "legs": "Legs", "feet": "Feet", "armor": "Any armor",
    "body": "Body (animal)", "saddle": "Saddle",
}
# Heading shown in the tooltip above each slot group ("When in Main Hand:").
SLOT_HEADINGS = {
    "any": "When Equipped:", "mainhand": "When in Main Hand:", "offhand": "When in Off Hand:",
    "hand": "When in Hand:", "feet": "When on Feet:", "legs": "When on Legs:",
    "chest": "When on Body:", "head": "When on Head:", "armor": "When on Armor:",
    "body": "When on Body:", "saddle": "When on Saddle:",
}
SLOT_TOOLTIP_ORDER = ("any", "mainhand", "offhand", "hand", "feet", "legs", "chest", "head",
                      "armor", "body", "saddle")

OPERATIONS = ("add_value", "add_multiplied_base", "add_multiplied_total")
OPERATION_LABELS = {
    "add_value": "Add (+n)",
    "add_multiplied_base": "Multiply base (+n%)",
    "add_multiplied_total": "Multiply total (xn%)",
}

# Attribute ids as of 1.21.2 (no 'generic.' / 'player.' prefix) that make sense on items.
KNOWN_ATTRIBUTES = (
    "attack_damage", "attack_speed", "attack_knockback", "armor", "armor_toughness",
    "max_health", "movement_speed", "knockback_resistance", "luck", "max_absorption",
    "step_height", "gravity", "jump_strength", "scale", "safe_fall_distance",
    "fall_damage_multiplier", "burning_time", "explosion_knockback_resistance",
    "movement_efficiency", "oxygen_bonus", "water_movement_efficiency", "sneaking_speed",
    "mining_efficiency", "submerged_mining_speed", "sweeping_damage_ratio",
    "block_break_speed", "block_interaction_range", "entity_interaction_range",
)
LEGACY_ATTRIBUTE_PREFIXES = ("generic.", "player.", "zombie.")

KNOWN_ENCHANTMENTS = (
    "protection", "fire_protection", "feather_falling", "blast_protection",
    "projectile_protection", "respiration", "aqua_affinity", "thorns", "depth_strider",
    "frost_walker", "binding_curse", "soul_speed", "swift_sneak", "sharpness", "smite",
    "bane_of_arthropods", "knockback", "fire_aspect", "looting", "sweeping_edge", "efficiency",
    "silk_touch", "unbreaking", "fortune", "power", "punch", "flame", "infinity",
    "luck_of_the_sea", "lure", "loyalty", "impaling", "riptide", "channeling", "multishot",
    "quick_charge", "piercing", "density", "breach", "wind_burst", "mending", "vanishing_curse",
)
CURSES = frozenset({"binding_curse", "vanishing_curse"})
# The game shows no level number for these at level 1.
SINGLE_LEVEL_ENCHANTMENTS = frozenset({
    "aqua_affinity", "binding_curse", "vanishing_curse", "silk_touch", "flame", "infinity",
    "channeling", "multishot", "mending",
})

_ID_RE = re.compile(r"[a-z0-9_.-]+:[a-z0-9_./-]+")
_SMALL_WORDS = {"of", "the"}


def normalize_id(text: str) -> str:
    """'attack_damage' -> 'minecraft:attack_damage'; ids with a namespace stay as typed."""
    text = text.strip()
    return text if ":" in text or not text else f"minecraft:{text}"


def is_valid_id(text: str) -> bool:
    return bool(_ID_RE.fullmatch(text))


def _path(item_id: str) -> str:
    return item_id.split(":", 1)[1] if ":" in item_id else item_id


def _title(path: str) -> str:
    words = path.replace("/", " ").replace(".", " ").split("_")
    return " ".join(w if w in _SMALL_WORDS and i else w.capitalize() for i, w in enumerate(words)).strip()


def attribute_label(attr_id: str) -> str:
    """Name the game shows for an attribute, e.g. 'Attack Damage' ('Speed' for movement_speed)."""
    path = _path(attr_id)
    return "Speed" if path == "movement_speed" else _title(path)


def enchantment_label(ench_id: str) -> str:
    path = _path(ench_id)
    if path.endswith("_curse"):
        return f"Curse of {_title(path[:-len('_curse')])}"
    return _title(path)


# ----------------------------------------------------------- attribute modifiers

@dataclass(frozen=True)
class AttributeModifier:
    type: str                      # 'minecraft:attack_damage'
    amount: float
    operation: str = "add_value"
    slot: str = "any"

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "amount": self.amount, "operation": self.operation,
                "slot": self.slot}

    @classmethod
    def from_dict(cls, d: Any) -> "AttributeModifier":
        """Raises ValueError with a readable reason if the stored entry is unusable."""
        if not isinstance(d, dict):
            raise ValueError("entry is not an object")
        amount = d.get("amount")
        if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not math.isfinite(amount):
            raise ValueError("'amount' must be a finite number")
        type_ = d.get("type")
        if not isinstance(type_, str) or not type_.strip():
            raise ValueError("'type' (the attribute) is missing")
        return cls(normalize_id(type_), float(amount), str(d.get("operation", "add_value")),
                   str(d.get("slot", "any")))


def modifier_id(item_name: str, attr_type: str, index: int) -> str:
    """Stable, unique id for one modifier of an item (Minecraft requires one per modifier)."""
    return f"minecraft:{item_name}_{_path(attr_type).replace('/', '_')}_{index}"


def check_attributes(attrs: tuple[AttributeModifier, ...] | list[AttributeModifier],
                     text_format: str = TEXT_SNBT) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if len(attrs) > MAX_ATTRIBUTES:
        errors.append(f"{len(attrs)} attribute modifiers; at most {MAX_ATTRIBUTES} are supported.")
    for n, m in enumerate(attrs, 1):
        where = f"Attribute modifier {n}"
        path = _path(m.type)
        if not is_valid_id(m.type):
            errors.append(f"{where}: '{m.type}' is not a valid attribute id (lowercase letters, "
                          "digits, _ . - and one ':').")
            continue
        if path.startswith(LEGACY_ATTRIBUTE_PREFIXES):
            fixed = path.split(".", 1)[1]
            errors.append(f"{where}: '{m.type}' uses the pre-1.21.2 name. Use "
                          f"'minecraft:{fixed}' (both supported target versions need the new name).")
            continue
        if m.operation not in OPERATIONS:
            errors.append(f"{where}: operation '{m.operation}' must be one of {', '.join(OPERATIONS)}.")
        if m.slot not in SLOTS:
            errors.append(f"{where}: slot '{m.slot}' must be one of {', '.join(SLOTS)}.")
        elif m.slot in SLOTS_SINCE_1_21_5 and text_format == TEXT_JSON:
            errors.append(f"{where}: slot '{m.slot}' needs target version 1.21.5 or newer.")
        if not isinstance(m.amount, (int, float)) or isinstance(m.amount, bool) \
                or not math.isfinite(m.amount):
            errors.append(f"{where}: amount must be a finite number.")
            continue
        if m.type.startswith("minecraft:") and path not in KNOWN_ATTRIBUTES:
            warnings.append(f"{where}: '{m.type}' is not in this tool's attribute list (mob-only, "
                            "newer than the list, or misspelled); it could not be verified.")
        elif not m.type.startswith("minecraft:"):
            warnings.append(f"{where}: '{m.type}' belongs to another namespace and could not be "
                            "verified.")
        if m.amount == 0:
            warnings.append(f"{where}: amount 0 changes nothing and is not shown in the tooltip.")
    return errors, warnings


def format_double(value: float) -> str:
    """7 -> '7.0d', 0.25 -> '0.25d'. Never uses exponent notation."""
    text = f"{round(float(value), 6):.6f}".rstrip("0")
    if text.endswith("."):
        text += "0"
    if text == "-0.0":                      # a tiny negative number rounds to zero
        text = "0.0"
    return text + "d"


def attributes_value(item_name: str, attrs: tuple[AttributeModifier, ...] | list[AttributeModifier],
                     text_format: str) -> tuple[str, Any]:
    """(SNBT for the command, JSON for a recipe result) for an already validated list."""
    snbt, js = [], []
    for n, m in enumerate(attrs, 1):
        mid = modifier_id(item_name, m.type, n)
        snbt.append(f'{{type:"{m.type}",id:"{mid}",amount:{format_double(m.amount)},'
                    f'operation:"{m.operation}",slot:"{m.slot}"}}')
        js.append({"type": m.type, "id": mid, "amount": round(float(m.amount), 6),
                   "operation": m.operation, "slot": m.slot})
    listing = "[" + ",".join(snbt) + "]"
    if text_format == TEXT_JSON:                       # 1.21.4: full record
        return "{modifiers:" + listing + "}", {"modifiers": js}
    return listing, js


# ------------------------------------------------------------------ enchantments

def check_enchantments(pairs: tuple[tuple[str, int], ...] | list[tuple[str, int]]
                       ) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for ench, level in pairs:
        if not is_valid_id(ench):
            errors.append(f"Enchantment '{ench}' is not a valid id (lowercase letters, digits, "
                          "_ . - and one ':').")
            continue
        if ench in seen:
            errors.append(f"Enchantment {ench} is listed twice.")
        seen.add(ench)
        if isinstance(level, bool) or not isinstance(level, int) or not 1 <= level <= MAX_ENCHANT_LEVEL:
            errors.append(f"Enchantment {ench}: level must be a whole number from 1 to "
                          f"{MAX_ENCHANT_LEVEL}.")
        if ench.startswith("minecraft:") and _path(ench) not in KNOWN_ENCHANTMENTS:
            warnings.append(f"Enchantment {ench} is not in this tool's list (newer than the list "
                            "or misspelled); it could not be verified.")
        elif not ench.startswith("minecraft:"):
            warnings.append(f"Enchantment {ench} belongs to another namespace and could not be "
                            "verified.")
    return errors, warnings


def enchantments_value(pairs: tuple[tuple[str, int], ...] | list[tuple[str, int]],
                       text_format: str) -> tuple[str, Any]:
    body = ",".join(f'"{e}":{lvl}' for e, lvl in pairs)
    levels = {e: lvl for e, lvl in pairs}
    if text_format == TEXT_JSON:                       # 1.21.4: full record
        return "{levels:{" + body + "}}", {"levels": levels}
    return "{" + body + "}", levels
