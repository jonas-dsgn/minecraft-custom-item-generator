"""Per-item data (display name, base item, recipe) and its persistent store.

The project had no saved item data before, so the store is a single small JSON file in
the datapack root (Minecraft ignores unknown files there):
    <datapack>/item_generator_items.json
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .attributes import AttributeModifier, normalize_id
from .components import RARITIES, ItemProperties
from .item_rules import MIN_STACK, max_stack_limit
from .recipes import Recipe
from .text_components import TEXT_JSON, TEXT_SNBT
from .validation import DEFAULT_DISPLAY_MODE, DEFAULT_SCALE, check_display_settings

STORE_FILENAME = "item_generator_items.json"
STORE_VERSION = 3           # 2 = lore / stack size / glint / rarity / ...; 3 = + enchantments,
                            # attributes, durability, fire resistance, custom data
DEFAULT_BASE_ITEM = "minecraft:stick"


class StoreError(Exception):
    pass


@dataclass
class ItemRecord:
    name: str
    base_item: str = DEFAULT_BASE_ITEM
    display_name: str = ""                  # legacy &-codes; "" = no custom name
    recipe: Recipe | None = None
    # Also write function/display/<name>.mcfunction (summons an item_display). Off by default.
    generate_display: bool = False
    display_mode: str = DEFAULT_DISPLAY_MODE      # item_display mode (not size)
    display_scale: tuple[float, float, float] = DEFAULT_SCALE   # X, Y, Z
    # Raw extra components kept verbatim in /give commands, e.g. {"max_stack_size": "1"}.
    # Not editable in the UI; edit the store file by hand. Not copied into recipes.
    extra_components: dict[str, str] = field(default_factory=dict)
    # Item properties (store version 2). Written to the file only when they are not default.
    lore: list[str] = field(default_factory=list)   # legacy &-codes, one entry per lore line
    max_stack_size: int | None = None                # None = the base item's own default
    glint: bool = False                              # enchantment_glint_override: true
    rarity: str = ""                                 # "" = item default
    unbreakable: bool = False
    hide_tooltip: bool = False
    # Store version 3
    enchantments: list[tuple[str, int]] = field(default_factory=list)   # (id, level), in order
    attributes: list[AttributeModifier] = field(default_factory=list)
    max_damage: int | None = None                    # durability; None = the base item's own
    fire_resistant: bool = False                     # damage_resistant: #minecraft:is_fire
    custom_data: str = ""                            # SNBT compound, written as typed

    def properties(self) -> ItemProperties:
        return ItemProperties(
            lore=tuple(self.lore), max_stack_size=self.max_stack_size, glint=self.glint,
            rarity=self.rarity, unbreakable=self.unbreakable, hide_tooltip=self.hide_tooltip,
            enchantments=tuple(self.enchantments), attributes=tuple(self.attributes),
            max_damage=self.max_damage, fire_resistant=self.fire_resistant,
            custom_data=self.custom_data)

    def uses_v3_fields(self) -> bool:
        return bool(self.enchantments or self.attributes or self.max_damage is not None
                    or self.fire_resistant or self.custom_data.strip())

    def uses_v2_fields(self) -> bool:
        return bool(self.lore or self.max_stack_size is not None or self.glint or self.rarity
                    or self.unbreakable or self.hide_tooltip)

    def required_version(self) -> int:
        """Lowest store version that can hold this item without losing data."""
        return 3 if self.uses_v3_fields() else 2 if self.uses_v2_fields() else 1

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"base_item": self.base_item, "display_name": self.display_name}
        if self.lore:
            d["lore"] = list(self.lore)
        if self.max_stack_size is not None:
            d["max_stack_size"] = self.max_stack_size
        if self.glint:
            d["glint"] = True
        if self.rarity:
            d["rarity"] = self.rarity
        if self.unbreakable:
            d["unbreakable"] = True
        if self.hide_tooltip:
            d["hide_tooltip"] = True
        if self.enchantments:
            d["enchantments"] = {ench: level for ench, level in self.enchantments}
        if self.attributes:
            d["attributes"] = [m.to_dict() for m in self.attributes]
        if self.max_damage is not None:
            d["max_damage"] = self.max_damage
        if self.fire_resistant:
            d["fire_resistant"] = True
        if self.custom_data.strip():
            d["custom_data"] = self.custom_data
        if self.generate_display:
            d["generate_display"] = True
        if self.display_mode != DEFAULT_DISPLAY_MODE:
            d["display_mode"] = self.display_mode
        if tuple(self.display_scale) != DEFAULT_SCALE:
            d["display_scale"] = list(self.display_scale)
        if self.extra_components:
            d["extra_components"] = dict(self.extra_components)
        if self.recipe is not None:
            d["recipe"] = self.recipe.to_dict()
        return d

    @classmethod
    def from_dict(cls, name: str, d: Mapping[str, Any],
                  warnings: list[str] | None = None) -> "ItemRecord":
        """Build a record from the stored dict. Values that cannot be used are not applied
        and are reported through `warnings` (never dropped silently)."""
        def warn(message: str) -> None:
            if warnings is not None:
                warnings.append(f"{name}: {message}")

        lore: list[str] = []
        raw_lore = d.get("lore")
        if isinstance(raw_lore, list):
            lore = [str(x) for x in raw_lore]
        elif raw_lore is not None:
            warn("'lore' must be a list of strings; it was ignored.")
        stack = d.get("max_stack_size")
        if stack is not None:
            limit = max_stack_limit(TEXT_SNBT)
            if isinstance(stack, bool) or not isinstance(stack, int) or not MIN_STACK <= stack <= limit:
                warn(f"'max_stack_size' {stack!r} is not a whole number from {MIN_STACK} to "
                     f"{limit}; it was ignored.")
                stack = None
        rarity = d.get("rarity") or ""
        if rarity not in ("",) + RARITIES:
            warn(f"'rarity' {rarity!r} is not one of {', '.join(RARITIES)}; it was ignored.")
            rarity = ""
        enchantments: list[tuple[str, int]] = []
        raw_ench = d.get("enchantments")
        if isinstance(raw_ench, dict):
            for ench, level in raw_ench.items():
                if isinstance(level, bool) or not isinstance(level, int):
                    warn(f"enchantment {ench!r} has level {level!r}, which is not a whole number; "
                         "it was ignored.")
                else:
                    enchantments.append((normalize_id(str(ench)), level))
        elif raw_ench is not None:
            warn("'enchantments' must be an object of id: level; it was ignored.")
        attributes: list[AttributeModifier] = []
        raw_attrs = d.get("attributes")
        if isinstance(raw_attrs, list):
            for n, entry in enumerate(raw_attrs, 1):
                try:
                    attributes.append(AttributeModifier.from_dict(entry))
                except ValueError as exc:
                    warn(f"attribute modifier {n} was ignored: {exc}.")
        elif raw_attrs is not None:
            warn("'attributes' must be a list; it was ignored.")
        max_damage = d.get("max_damage")
        if max_damage is not None and (isinstance(max_damage, bool) or not isinstance(max_damage, int)
                                       or max_damage < 1):
            warn(f"'max_damage' {max_damage!r} is not a whole number of at least 1; it was ignored.")
            max_damage = None
        custom_data = d.get("custom_data") or ""
        if not isinstance(custom_data, str):
            warn("'custom_data' must be SNBT text; it was ignored.")
            custom_data = ""
        recipe = d.get("recipe")
        extras = d.get("extra_components") or {}
        mode = d.get("display_mode", DEFAULT_DISPLAY_MODE)
        raw_scale = d.get("display_scale", DEFAULT_SCALE)
        try:
            scale = tuple(float(x) for x in raw_scale)
        except (TypeError, ValueError):
            scale = DEFAULT_SCALE
        if check_display_settings(str(mode), scale) is not None:   # damaged file: fall back
            mode, scale = DEFAULT_DISPLAY_MODE, DEFAULT_SCALE
        return cls(
            name=name,
            base_item=str(d.get("base_item") or DEFAULT_BASE_ITEM),
            display_name=str(d.get("display_name") or ""),
            recipe=Recipe.from_dict(recipe) if isinstance(recipe, dict) else None,
            generate_display=d.get("generate_display") is True,
            display_mode=str(mode),
            display_scale=scale,  # type: ignore[arg-type]
            extra_components={str(k): str(v) for k, v in extras.items()}
            if isinstance(extras, dict) else {},
            lore=lore,
            max_stack_size=stack,
            glint=d.get("glint") is True,
            rarity=str(rarity),
            unbreakable=d.get("unbreakable") is True,
            hide_tooltip=d.get("hide_tooltip") is True,
            enchantments=enchantments,
            attributes=attributes,
            max_damage=max_damage,
            fire_resistant=d.get("fire_resistant") is True,
            custom_data=custom_data,
        )


class ProjectStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.text_format = TEXT_SNBT
        self.loaded_from_file = False
        self.read_error: str | None = None
        self.warnings: list[str] = []      # stored values that could not be applied
        self._items: dict[str, dict[str, ItemRecord]] = {}

    @classmethod
    def load(cls, path: Path) -> "ProjectStore":
        store = cls(path)
        if not path.is_file():
            return store
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("top level must be an object")
            if int(data.get("version", 1)) > STORE_VERSION:
                raise ValueError("file was written by a newer version of this tool")
            fmt = data.get("text_format", TEXT_SNBT)
            store.text_format = fmt if fmt in (TEXT_SNBT, TEXT_JSON) else TEXT_SNBT
            for ns, block in (data.get("namespaces") or {}).items():
                for name, raw in ((block or {}).get("items") or {}).items():
                    store._items.setdefault(ns, {})[name] = ItemRecord.from_dict(
                        name, raw, store.warnings)
            store.loaded_from_file = True
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            store._items = {}
            store.read_error = f"{path.name} could not be read ({exc}). It will not be modified."
        return store

    def items(self, namespace: str) -> dict[str, ItemRecord]:
        return self._items.setdefault(namespace, {})

    def put(self, namespace: str, record: ItemRecord) -> None:
        self.items(namespace)[record.name] = record

    def save(self) -> None:
        if self.read_error:
            raise StoreError(self.read_error)
        needed = max((r.required_version() for block in self._items.values() for r in block.values()),
                     default=1)
        data = {
            # Only as new as the data needs, so builds that know fewer fields can still open it.
            "version": needed,
            "text_format": self.text_format,
            "namespaces": {
                ns: {"items": {n: r.to_dict() for n, r in sorted(items.items())}}
                for ns, items in sorted(self._items.items()) if items
            },
        }
        tmp = self.path.with_name(self.path.name + ".tmp")
        try:
            tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError as exc:
            tmp.unlink(missing_ok=True)
            raise StoreError(f"Could not save {self.path.name}: {exc}") from exc
        self.loaded_from_file = True
