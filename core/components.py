"""Builds the item components of a custom item for /give, item_display and recipe results.

One place decides which components are written, in which syntax for the target version, and
what is reported: every give/display command and every recipe result goes through
`build_components`, so they cannot drift apart.

Command syntax (SNBT) differs by version in three places this module handles:
  * text components: SNBT objects (1.21.5+) or JSON strings (1.21.4)   -> text_format
  * hide_tooltip (1.21.4) was replaced by tooltip_display (1.21.5+)
  * the extra-component version table below
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping

from .attributes import (
    AttributeModifier, attributes_value, check_attributes, check_enchantments, enchantments_value,
)
from .ids import item_model_id
from .item_rules import item_facts, validate_stack_size
from .snbt import SnbtError, parse_compound
from .text_components import (
    TEXT_JSON, TEXT_SNBT, build_component, build_lore_line, find_unknown_codes,
    format_component_arg,
)

RARITIES = ("common", "uncommon", "rare", "epic")
MAX_LORE_LINES = 256

# Components the tool generates itself from first-class item data.
MANAGED = frozenset({
    "item_model", "custom_name", "lore", "max_stack_size", "enchantment_glint_override",
    "rarity", "unbreakable", "hide_tooltip", "tooltip_display", "enchantments",
    "attribute_modifiers", "max_damage", "damage_resistant", "custom_data",
})

# Components a stored "extra component" can name but a target version does not know.
# {bare name: (formats where it is unsupported, why)}
_UNSUPPORTED_EXTRA: dict[str, tuple[frozenset[str], str]] = {
    "hide_tooltip": (frozenset({TEXT_SNBT}), "was replaced by tooltip_display in 1.21.5"),
    "hide_additional_tooltip": (frozenset({TEXT_SNBT}), "was replaced by tooltip_display in 1.21.5"),
    "tooltip_display": (frozenset({TEXT_JSON}), "only exists from 1.21.5"),
    "fire_resistant": (frozenset({TEXT_SNBT, TEXT_JSON}),
                       "was replaced by damage_resistant in 1.21.2 "
                       "(use the 'Fire resistant' option)"),
}
_KEY_RE = re.compile(r"[a-z0-9_.:/-]+")


@dataclass(frozen=True)
class ItemProperties:
    """The editable item components beyond model and name."""
    lore: tuple[str, ...] = ()           # legacy &-codes, one entry per line
    max_stack_size: int | None = None    # None = the item's own default
    glint: bool = False                  # enchantment_glint_override: true
    rarity: str = ""                     # "" = item default
    unbreakable: bool = False
    hide_tooltip: bool = False
    enchantments: tuple[tuple[str, int], ...] = ()          # (id, level), in tooltip order
    attributes: tuple[AttributeModifier, ...] = ()
    max_damage: int | None = None                           # durability; None = item default
    fire_resistant: bool = False                            # damage_resistant: #is_fire
    custom_data: str = ""                                   # SNBT compound, written as typed


@dataclass
class ComponentPlan:
    entries: list[tuple[str, str]] = field(default_factory=list)   # (key, SNBT value) in order
    json: dict[str, Any] = field(default_factory=dict)             # "minecraft:x" -> JSON value
    errors: list[str] = field(default_factory=list)                # block generation
    warnings: list[str] = field(default_factory=list)              # reported, generation goes on

    def give_arguments(self) -> list[str]:
        return [f"{key}={value}" for key, value in self.entries]

    def display_arguments(self) -> list[str]:
        return [f'"{key if ":" in key else "minecraft:" + key}":{value}' for key, value in self.entries]


def build_components(
    name: str, display_name: str = "", text_format: str = TEXT_SNBT,
    extra_components: Mapping[str, str] | None = None, props: ItemProperties | None = None,
    base_item: str = "minecraft:stick",
) -> ComponentPlan:
    props = props or ItemProperties()
    plan = ComponentPlan()
    add = plan.entries.append

    # --- item model
    model = item_model_id(name)
    add(("item_model", f'"{model}"'))
    plan.json["minecraft:item_model"] = model

    # --- name
    for code in find_unknown_codes(display_name):
        plan.warnings.append(f"Name: unknown code {code} is written as plain text "
                             "(use && for a literal &).")
    name_component = build_component(display_name)
    if name_component is not None:
        add(("custom_name", format_component_arg(name_component, text_format)))
        plan.json["minecraft:custom_name"] = name_component

    # --- lore
    if len(props.lore) > MAX_LORE_LINES:
        plan.errors.append(f"Lore has {len(props.lore)} lines; Minecraft allows at most "
                           f"{MAX_LORE_LINES}.")
    if props.lore:
        lines = [build_lore_line(line) for line in props.lore]
        add(("lore", "[" + ",".join(format_component_arg(c, text_format) for c in lines) + "]"))
        plan.json["minecraft:lore"] = lines
        for number, line in enumerate(props.lore, 1):
            for code in find_unknown_codes(line):
                plan.warnings.append(f"Lore line {number}: unknown code {code} is written as "
                                     "plain text (use && for a literal &).")

    # --- enchantments and attribute modifiers (syntax differs between the target versions)
    if props.enchantments:
        errors, warnings = check_enchantments(props.enchantments)
        plan.errors += errors
        plan.warnings += warnings
        if not errors:
            snbt, js = enchantments_value(props.enchantments, text_format)
            add(("enchantments", snbt))
            plan.json["minecraft:enchantments"] = js
    if props.attributes:
        errors, warnings = check_attributes(props.attributes, text_format)
        plan.errors += errors
        plan.warnings += warnings
        if not errors:
            snbt, js = attributes_value(name, props.attributes, text_format)
            add(("attribute_modifiers", snbt))
            plan.json["minecraft:attribute_modifiers"] = js

    # --- stack size
    errors, warnings = validate_stack_size(base_item, props.max_stack_size, text_format)
    plan.errors += errors
    plan.warnings += warnings
    if props.max_stack_size is not None and not errors:
        add(("max_stack_size", str(props.max_stack_size)))
        plan.json["minecraft:max_stack_size"] = props.max_stack_size
    if props.max_damage is not None:
        errors, warnings = _check_max_damage(base_item, props.max_damage, props.max_stack_size)
        plan.errors += errors
        plan.warnings += warnings
        if not errors:
            add(("max_damage", str(props.max_damage)))
            plan.json["minecraft:max_damage"] = props.max_damage

    # --- simple flags
    if props.glint:
        add(("enchantment_glint_override", "true"))
        plan.json["minecraft:enchantment_glint_override"] = True
    if props.rarity:
        if props.rarity not in RARITIES:
            plan.errors.append(f"Rarity '{props.rarity}' is not one of: {', '.join(RARITIES)}.")
        else:
            add(("rarity", f'"{props.rarity}"'))
            plan.json["minecraft:rarity"] = props.rarity
    if props.unbreakable:
        add(("unbreakable", "{}"))
        plan.json["minecraft:unbreakable"] = {}
    if props.fire_resistant:
        add(("damage_resistant", '{types:"#minecraft:is_fire"}'))
        plan.json["minecraft:damage_resistant"] = {"types": "#minecraft:is_fire"}
    if props.hide_tooltip:
        if text_format == TEXT_JSON:                       # 1.21.4
            add(("hide_tooltip", "{}"))
            plan.json["minecraft:hide_tooltip"] = {}
        else:                                              # 1.21.5+
            add(("tooltip_display", "{hide_tooltip:true}"))
            plan.json["minecraft:tooltip_display"] = {"hide_tooltip": True}
    if props.custom_data.strip():
        text = props.custom_data.strip()
        try:
            parsed = parse_compound(text)
        except SnbtError as exc:
            plan.errors.append(f"Custom data: {exc}")
        else:
            add(("custom_data", text))
            plan.json["minecraft:custom_data"] = parsed.value
            if parsed.lossy:
                plan.warnings.append(
                    "Custom data: typed numbers (1b, 2s, 3f, 4L) and typed arrays become plain "
                    "int/double values in a recipe result, because JSON cannot express them; the "
                    "give and display commands keep the exact text.")

    # --- raw extra components from the project file: kept verbatim unless they clash
    editor_sets = {
        "lore": bool(props.lore), "max_stack_size": props.max_stack_size is not None,
        "enchantment_glint_override": props.glint, "rarity": bool(props.rarity),
        "unbreakable": props.unbreakable,
        "hide_tooltip": props.hide_tooltip, "tooltip_display": props.hide_tooltip,
        "enchantments": bool(props.enchantments), "attribute_modifiers": bool(props.attributes),
        "max_damage": props.max_damage is not None, "damage_resistant": props.fire_resistant,
        "custom_data": bool(props.custom_data.strip()),
    }
    for key, value in (extra_components or {}).items():
        bare = key.removeprefix("minecraft:")
        if not _KEY_RE.fullmatch(key) or "\n" in value or "\r" in value:
            plan.errors.append(f"Invalid extra component '{key}'.")
            continue
        if bare in ("item_model", "custom_name"):
            plan.warnings.append(f"Extra component {bare} ignored: the tool generates it "
                                 "from the item's model and name.")
            continue
        if editor_sets.get(bare):
            plan.warnings.append(f"Extra component {bare} ignored: the value set in the item "
                                 "editor is used instead.")
            continue
        unsupported = _UNSUPPORTED_EXTRA.get(bare)
        if unsupported and text_format in unsupported[0]:
            plan.warnings.append(f"Extra component {bare} is not supported by the target "
                                 f"version ({unsupported[1]}); it was left out of the commands.")
            continue
        add((key, value))
    return plan


def _check_max_damage(base_item: str, max_damage: int,
                      stack: int | None) -> tuple[list[str], list[str]]:
    """max_damage makes an item damageable, and damageable items cannot stack."""
    if isinstance(max_damage, bool) or not isinstance(max_damage, int) or max_damage < 1:
        return ["Max durability must be a whole number of at least 1."], []
    facts = item_facts(base_item)
    if facts.damageable:
        return [], []                      # already damageable; stack size is checked separately
    effective = stack if stack is not None else facts.default_stack
    if effective > 1:
        if facts.known or stack is not None:
            return [f"Max durability makes the item damageable, and damageable items cannot "
                    f"stack: set the stack size to 1 (it would be {effective})."], []
        return [], [f"Max durability needs a stack size of 1; {base_item}'s default could not "
                    "be checked, so set the stack size to 1 to be safe."]
    return [], []


def recipe_components(plan: ComponentPlan) -> dict[str, Any]:
    """JSON components for a recipe result (extras are not copied, as before)."""
    return dict(plan.json)
