"""Crafting recipes: model, validation and JSON generation.

Targets the Minecraft 1.21.2+ recipe schema (also valid for 26.x):
  * ingredients are plain strings: "minecraft:diamond", "#minecraft:planks"
  * the result is {"id", "count", "components"}
  * files live in data/<namespace>/recipe/ (singular)

Vanilla recipes cannot match item components on INPUTS, so a custom item used as an
ingredient is exported as its base item (e.g. any stick) and a warning is raised.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Mapping

from .components import build_components, recipe_components
from .text_components import TEXT_SNBT
from .validation import validate_item_name

if TYPE_CHECKING:
    from .items import ItemRecord

CUSTOM_PREFIX = "custom:"
KINDS = ("shaped", "shapeless")
MAX_COUNT = 99
KEY_LETTERS = "ABCDEFGHI"
_VANILLA_RE = re.compile(r"^#?[a-z0-9_.-]+:[a-z0-9_./-]+$")


def is_custom(ref: str) -> bool:
    return ref.startswith(CUSTOM_PREFIX)


def custom_name(ref: str) -> str:
    return ref[len(CUSTOM_PREFIX):]


def normalize_ingredient(raw: str) -> str:
    """'' stays empty; 'diamond' -> 'minecraft:diamond'; '#planks' -> '#minecraft:planks'."""
    s = (raw or "").strip().lower()
    if not s or is_custom(s):
        return s
    tag = s.startswith("#")
    body = s[1:] if tag else s
    if ":" not in body:
        body = "minecraft:" + body
    return ("#" if tag else "") + body


def normalize_output(raw: str) -> str:
    s = normalize_ingredient(raw)
    return s


@dataclass
class Recipe:
    kind: str = "shaped"
    recipe_id: str = ""
    output: str = ""              # "custom:<item name>" or a vanilla item id
    count: int = 1
    slots: list[str] = field(default_factory=lambda: [""] * 9)   # row-major 3x3
    category: str = "misc"

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind, "recipe_id": self.recipe_id, "output": self.output,
            "count": self.count, "slots": list(self.slots), "category": self.category,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Recipe":
        slots = [str(s) for s in (d.get("slots") or [])][:9]
        slots += [""] * (9 - len(slots))
        try:
            count = int(d.get("count", 1))
        except (TypeError, ValueError):
            count = 1
        kind = d.get("kind", "shaped")
        return cls(
            kind=kind if kind in KINDS else "shaped",
            recipe_id=str(d.get("recipe_id", "")),
            output=str(d.get("output", "")),
            count=count, slots=slots, category=str(d.get("category", "misc")),
        )

    def ingredients(self) -> list[str]:
        return [normalize_ingredient(s) for s in self.slots if s.strip()]

    def output_custom_name(self) -> str | None:
        return custom_name(self.output) if is_custom(self.output) else None


@dataclass
class RecipeCheck:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_recipe(recipe: Recipe, records: Mapping[str, "ItemRecord"]) -> RecipeCheck:
    check = RecipeCheck()
    if recipe.kind not in KINDS:
        check.errors.append("Recipe type must be shaped or shapeless.")
    err = validate_item_name(recipe.recipe_id) if recipe.recipe_id else "Recipe ID is empty."
    if err:
        check.errors.append(f"Recipe ID: {err}")
    if not 1 <= recipe.count <= MAX_COUNT:
        check.errors.append(f"Output count must be between 1 and {MAX_COUNT}.")

    out = normalize_output(recipe.output)
    if not out:
        check.errors.append("Output item is empty.")
    elif is_custom(out):
        if custom_name(out) not in records:
            check.errors.append(f"Output item '{custom_name(out)}' is not a known custom item.")
    elif out.startswith("#") or not _VANILLA_RE.fullmatch(out):
        check.errors.append(f"Output '{recipe.output}' is not a valid item ID (e.g. minecraft:diamond).")

    if len(recipe.slots) != 9:
        check.errors.append("A recipe needs exactly 9 grid slots.")
    ingredients = recipe.ingredients()
    if not ingredients:
        check.errors.append("The recipe has no ingredients.")
    seen_custom: set[str] = set()
    for ing in ingredients:
        if is_custom(ing):
            name = custom_name(ing)
            if name not in records:
                check.errors.append(f"Ingredient '{name}' is not a known custom item.")
            elif name not in seen_custom:
                seen_custom.add(name)
                check.warnings.append(
                    f"Custom ingredient '{name}' will match ANY {records[name].base_item} "
                    "(vanilla recipes cannot check item components on inputs)."
                )
        elif not _VANILLA_RE.fullmatch(ing):
            check.errors.append(f"Ingredient '{ing}' is not a valid item ID or #tag.")
    return check


def resolve_ingredient(ref: str, records: Mapping[str, "ItemRecord"]) -> str:
    return records[custom_name(ref)].base_item if is_custom(ref) else ref


def result_json(recipe: Recipe, records: Mapping[str, "ItemRecord"],
                text_format: str = TEXT_SNBT) -> dict[str, Any]:
    """Recipe result. A custom item carries the same components as its give command (model,
    name, lore, stack size, ...), written as JSON for the target version."""
    out = normalize_output(recipe.output)
    if is_custom(out):
        rec = records[custom_name(out)]
        plan = build_components(rec.name, rec.display_name, text_format, None,
                                rec.properties(), rec.base_item)
        if plan.errors:
            raise ValueError(f"Item '{rec.name}': " + " ".join(plan.errors))
        return {"id": rec.base_item, "count": recipe.count, "components": recipe_components(plan)}
    return {"id": out, "count": recipe.count}


def build_recipe_json(recipe: Recipe, records: Mapping[str, "ItemRecord"],
                      text_format: str = TEXT_SNBT) -> dict[str, Any]:
    check = validate_recipe(recipe, records)
    if not check.ok:
        raise ValueError("; ".join(check.errors))
    slots = [normalize_ingredient(s) for s in recipe.slots]
    result = result_json(recipe, records, text_format)

    if recipe.kind == "shapeless":
        return {
            "type": "minecraft:crafting_shapeless",
            "category": recipe.category,
            "ingredients": [resolve_ingredient(s, records) for s in slots if s],
            "result": result,
        }

    grid = [slots[0:3], slots[3:6], slots[6:9]]
    rows = [r for r in range(3) if any(grid[r])]
    cols = [c for c in range(3) if any(grid[r][c] for r in range(3))]
    letters: dict[str, str] = {}
    pattern: list[str] = []
    for r in range(rows[0], rows[-1] + 1):
        line = ""
        for c in range(cols[0], cols[-1] + 1):
            ref = grid[r][c]
            if not ref:
                line += " "
                continue
            item = resolve_ingredient(ref, records)
            if item not in letters:
                letters[item] = KEY_LETTERS[len(letters)]
            line += letters[item]
        pattern.append(line)
    return {
        "type": "minecraft:crafting_shaped",
        "category": recipe.category,
        "key": {letter: item for item, letter in letters.items()},
        "pattern": pattern,
        "result": result,
    }


def recipe_json_text(data: Mapping[str, Any]) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"
