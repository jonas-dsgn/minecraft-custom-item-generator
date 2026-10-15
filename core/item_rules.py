"""Vanilla item facts needed to validate item components (stack size).

This is a curated table, not the game registry. Anything not covered is reported as
"unverified" instead of being guessed.
"""
from __future__ import annotations

from dataclasses import dataclass

from .text_components import TEXT_JSON, TEXT_SNBT
from .vanilla_items import VANILLA_ITEMS

# Allowed range of the max_stack_size component, by target version. Both supported targets
# (1.21.4 and 1.21.5+) use 1..99; the table is here so a future target can differ.
MIN_STACK = 1
_MAX_STACK = {TEXT_SNBT: 99, TEXT_JSON: 99}


def max_stack_limit(text_format: str) -> int:
    return _MAX_STACK.get(text_format, 99)


_TOOL_MATERIALS = ("wooden", "stone", "copper", "iron", "golden", "diamond", "netherite")
_TOOLS = ("sword", "pickaxe", "axe", "shovel", "hoe")
_ARMOR_MATERIALS = ("leather", "chainmail", "copper", "iron", "golden", "diamond", "netherite")
_ARMOR = ("helmet", "chestplate", "leggings", "boots")

# Items with the max_damage component: Minecraft rejects max_stack_size > 1 on them.
DAMAGEABLE: frozenset[str] = frozenset(
    [f"{m}_{t}" for m in _TOOL_MATERIALS for t in _TOOLS]
    + [f"{m}_{a}" for m in _ARMOR_MATERIALS for a in _ARMOR]
    + ["turtle_helmet", "wolf_armor", "bow", "crossbow", "trident", "mace", "shield", "shears",
       "flint_and_steel", "fishing_rod", "carrot_on_a_stick", "warped_fungus_on_a_stick",
       "elytra", "brush"]
)

_STACK_16 = {"ender_pearl", "snowball", "egg", "blue_egg", "brown_egg", "honey_bottle",
             "armor_stand", "written_book", "bucket"}
_STACK_1 = {"potion", "splash_potion", "lingering_potion", "saddle", "totem_of_undying",
            "enchanted_book", "writable_book", "cake", "minecart", "mushroom_stew",
            "rabbit_stew", "beetroot_soup", "suspicious_stew", "goat_horn", "bundle",
            "shulker_box", "knowledge_book"}


@dataclass(frozen=True)
class ItemFacts:
    default_stack: int
    damageable: bool
    known: bool          # False: not in the table; restrictions could not be checked


def _bare(item_id: str) -> str | None:
    """'minecraft:stick' -> 'stick'; None for any other namespace."""
    namespace, _, path = item_id.partition(":")
    return path if namespace == "minecraft" and path else None


def item_facts(item_id: str) -> ItemFacts:
    path = _bare(item_id)
    if path is None:
        return ItemFacts(64, False, False)
    if path in DAMAGEABLE:
        return ItemFacts(1, True, True)
    if path in _STACK_16 or path.endswith(("_sign", "_hanging_sign", "_banner")):
        return ItemFacts(16, False, True)
    if (path in _STACK_1 or path.startswith("music_disc_")
            or path.endswith(("_boat", "_raft", "_bed", "_minecart", "_bucket", "_bundle",
                              "_shulker_box"))):
        return ItemFacts(1, False, True)
    return ItemFacts(64, False, f"minecraft:{path}" in _CURATED)


_CURATED = frozenset(VANILLA_ITEMS)


def validate_stack_size(base_item: str, size: int | None,
                        text_format: str = TEXT_SNBT) -> tuple[list[str], list[str]]:
    """Check a max_stack_size against the base item and the target version.

    Returns (errors, warnings). `size` None means "item default" and is always fine.
    """
    if size is None:
        return [], []
    limit = max_stack_limit(text_format)
    if isinstance(size, bool) or not isinstance(size, int) or not MIN_STACK <= size <= limit:
        return [f"Stack size must be a whole number from {MIN_STACK} to {limit} "
                f"for this target version."], []
    facts = item_facts(base_item)
    if facts.damageable and size > 1:
        return [f"{base_item} is damageable, and Minecraft rejects a stack size above 1 on "
                f"damageable items. Use 1 or pick another base item."], []
    if not facts.known and size > 1:
        return [], [f"Stack size {size} could not be checked against {base_item} (not in this "
                    "tool's item table). If the item is damageable, Minecraft will reject it."]
    return [], []
