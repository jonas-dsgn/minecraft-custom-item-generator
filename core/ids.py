"""Single source of truth for every identifier the generator emits.

Minecraft 1.21.4+ item model IDs refer to the *item definition* file:
    assets/minecraft/items/<name>.json   ->  minecraft:<name>
The definition then points at the model file:
    assets/minecraft/models/item/<name>.json  ->  minecraft:item/<name>
and the model points at the texture:
    assets/minecraft/textures/item/<name>.png ->  minecraft:item/<name>
"""
from __future__ import annotations

RESOURCE_NAMESPACE = "minecraft"


def item_model_id(name: str) -> str:
    """Value of the `item_model` component (the items/<name>.json definition)."""
    return f"{RESOURCE_NAMESPACE}:{name}"


def model_location(name: str) -> str:
    """Location of models/item/<name>.json, as referenced from the item definition."""
    return f"{RESOURCE_NAMESPACE}:item/{name}"


def texture_location(name: str) -> str:
    """Location of textures/item/<name>.png, as referenced from the model."""
    return f"{RESOURCE_NAMESPACE}:item/{name}"


def function_id(namespace: str, folder: str, name: str) -> str:
    """ID used with /function, e.g. customitems:display/andesite_greek_pillar."""
    return f"{namespace}:{folder}/{name}"
