"""Minecraft file generation. No UI code in here."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Collection, Mapping, Sequence

from .components import ComponentPlan, ItemProperties, build_components
from .ids import model_location, texture_location
from .items import ItemRecord
from .project_paths import DatapackPaths, ResourcePackPaths
from .recipes import build_recipe_json, recipe_json_text, validate_recipe
from .text_components import TEXT_SNBT, build_component, format_component_arg
from .validation import (
    DEFAULT_DISPLAY_MODE, DEFAULT_SCALE, check_display_settings, format_snbt_float,
    normalize_base_item, validate_item_name,
)


class Level(str, Enum):
    OK = "OK"
    INFO = "INFO"
    WARNING = "WARNING"
    SKIPPED = "SKIPPED"
    ERROR = "ERROR"


@dataclass
class LogEntry:
    level: Level
    message: str

    def __str__(self) -> str:
        return f"[{self.level.value}] {self.message}"


@dataclass
class BatchSummary:
    processed: int = 0
    created: int = 0
    skipped: int = 0
    items_skipped: int = 0
    warnings: int = 0
    errors: int = 0

    def text(self) -> str:
        return (
            f"Items processed: {self.processed} | Files created: {self.created} | "
            f"Existing files skipped: {self.skipped} | Items skipped: {self.items_skipped} | "
            f"Warnings: {self.warnings} | Errors: {self.errors}"
        )


@dataclass
class BatchResult:
    entries: list[LogEntry] = field(default_factory=list)
    summary: BatchSummary = field(default_factory=BatchSummary)
    completed: list[str] = field(default_factory=list)   # items fully processed without error

    def log(self, level: Level, message: str) -> None:
        self.entries.append(LogEntry(level, message))
        if level is Level.WARNING:
            self.summary.warnings += 1
        elif level is Level.ERROR:
            self.summary.errors += 1


@dataclass
class GenerationOptions:
    namespace: str
    base_item: str = "minecraft:stick"
    generate_give: bool = True
    generate_display: bool = False      # independent of generate_give
    display_mode: str = DEFAULT_DISPLAY_MODE
    display_scale: tuple[float, float, float] = DEFAULT_SCALE
    allow_missing_textures: bool = False
    overwrite: bool = False
    text_format: str = TEXT_SNBT
    # Known item data (display names, base items, extra components) by item name.
    records: Mapping[str, ItemRecord] = field(default_factory=dict)


# ---------------------------------------------------------------- content

def item_definition_content(name: str) -> str:
    data = {"model": {"type": "minecraft:model", "model": model_location(name)}}
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def item_model_content(name: str) -> str:
    data = {
        "parent": "minecraft:item/generated",
        "textures": {"layer0": texture_location(name)},
    }
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def analyze_item(
    name: str, base_item: str, display_name: str = "", text_format: str = TEXT_SNBT,
    extra_components: Mapping[str, str] | None = None, props: ItemProperties | None = None,
) -> ComponentPlan:
    """Components of one item plus every error and warning found while building them."""
    return build_components(name, display_name, text_format, extra_components, props, base_item)


def _checked(plan: ComponentPlan) -> ComponentPlan:
    if plan.errors:
        raise ValueError(" ".join(plan.errors))
    return plan


def build_give_command(
    name: str,
    base_item: str,
    display_name: str = "",
    text_format: str = TEXT_SNBT,
    extra_components: Mapping[str, str] | None = None,
    props: ItemProperties | None = None,
) -> str:
    """Build the /give command (without the leading slash).

    item_model is the ID of the items/<name>.json definition, NOT the model path.
    Raises ValueError if the item data is invalid (see analyze_item for warnings).
    """
    plan = _checked(analyze_item(name, base_item, display_name, text_format, extra_components, props))
    return f"give @p {base_item}[{','.join(plan.give_arguments())}]"


def give_function_content(
    name: str,
    base_item: str,
    display_name: str = "",
    text_format: str = TEXT_SNBT,
    extra_components: Mapping[str, str] | None = None,
    props: ItemProperties | None = None,
) -> str:
    # One command per line, no leading slash.
    return build_give_command(name, base_item, display_name, text_format, extra_components,
                              props) + "\n"


def build_display_command(
    name: str,
    base_item: str,
    display_name: str = "",
    text_format: str = TEXT_SNBT,
    extra_components: Mapping[str, str] | None = None,
    display_mode: str = DEFAULT_DISPLAY_MODE,
    scale: Sequence[float] = DEFAULT_SCALE,
    props: ItemProperties | None = None,
) -> str:
    """Build the /summon item_display command (without the leading slash).

    Uses the same components as the give command (model, name, lore, stack size, ...).
    `display_mode` (item_display) only chooses the transform context (fixed, gui, head, ...);
    the size comes from `scale` in the transformation. The defaults, "fixed" and 1.0 on
    every axis, show a full-block model at exactly one block. All four transformation
    fields are written because the summon NBT needs a complete transformation.
    """
    problem = check_display_settings(display_mode, tuple(scale))
    if problem:
        raise ValueError(problem)
    plan = _checked(analyze_item(name, base_item, display_name, text_format, extra_components, props))
    return (
        f'summon minecraft:item_display ~ ~ ~ {{item:{{id:"{base_item}",count:1,'
        f'components:{{{",".join(plan.display_arguments())}}}}},item_display:"{display_mode}",'
        f'transformation:{{left_rotation:[0f,0f,0f,1f],right_rotation:[0f,0f,0f,1f],'
        f'translation:[0f,0f,0f],scale:[{",".join(format_snbt_float(x) for x in scale)}]}}}}'
    )


def display_function_content(
    name: str,
    base_item: str,
    display_name: str = "",
    text_format: str = TEXT_SNBT,
    extra_components: Mapping[str, str] | None = None,
    display_mode: str = DEFAULT_DISPLAY_MODE,
    scale: Sequence[float] = DEFAULT_SCALE,
    props: ItemProperties | None = None,
) -> str:
    return build_display_command(name, base_item, display_name, text_format, extra_components,
                                 display_mode, scale, props) + "\n"


# ------------------------------------------------------------ safe writing

class _Transaction:
    """Writes files and can roll them all back if a later write fails."""

    def __init__(self) -> None:
        # (path, original_bytes or None if the file did not exist before)
        self._actions: list[tuple[Path, bytes | None]] = []

    def write(self, path: Path, text: str, overwrite: bool) -> str:
        """Return 'created', 'overwritten' or 'skipped'."""
        if path.exists():
            if not overwrite:
                return "skipped"
            original = path.read_bytes()
            tmp = path.with_name(path.name + ".tmp")
            try:
                tmp.write_text(text, encoding="utf-8", newline="\n")
                os.replace(tmp, path)
            except BaseException:
                tmp.unlink(missing_ok=True)
                raise
            self._actions.append((path, original))
            return "overwritten"

        try:
            handle = open(path, "x", encoding="utf-8", newline="\n")
        except FileExistsError:
            return "skipped"
        try:
            with handle:
                handle.write(text)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        self._actions.append((path, None))
        return "created"

    def delete(self, path: Path) -> bool:
        """Delete a file (restorable by rollback). Returns False if it did not exist."""
        if not path.is_file():
            return False
        original = path.read_bytes()
        path.unlink()
        self._actions.append((path, original))
        return True

    def rollback(self) -> None:
        for path, original in reversed(self._actions):
            try:
                if original is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_bytes(original)
            except OSError:
                pass
        self._actions.clear()


def _rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _ensure_dir(path: Path, root: Path, result: BatchResult) -> bool:
    if path.is_dir():
        return True
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        result.log(Level.ERROR, f"Could not create directory {_rel(path, root)}: {exc}")
        return False
    result.log(Level.INFO, f"Created missing directory {_rel(path, root)}/")
    return True


def _write_logged(
    tx: _Transaction, path: Path, label: str, text: str,
    overwrite: bool, result: BatchResult,
) -> None:
    outcome = tx.write(path, text, overwrite)
    shown = f"{label}/{path.name}"
    if outcome == "created":
        result.summary.created += 1
        result.log(Level.OK, f"Created {shown}")
    elif outcome == "overwritten":
        result.summary.created += 1
        result.log(Level.OK, f"Overwrote {shown}")
    else:
        result.summary.skipped += 1
        result.log(Level.SKIPPED, f"{shown} already exists")


# ----------------------------------------------------------------- scanning

def list_existing_models(rp: ResourcePackPaths) -> tuple[list[str], list[str]]:
    """Return (valid model names, file names ignored because they are not valid ids).

    A model is anything in models/item/ or already defined in items/ (the item_model ID
    is the items/<name>.json file name either way).
    """
    valid: set[str] = set()
    ignored: list[str] = []
    for folder in (rp.models_dir, rp.items_dir):
        if not folder.is_dir():
            continue
        for p in sorted(folder.iterdir(), key=lambda x: x.name.lower()):
            if p.is_file() and p.suffix.lower() == ".json":
                if validate_item_name(p.stem) is None:
                    valid.add(p.stem)
                elif p.name not in ignored:
                    ignored.append(p.name)
    return sorted(valid), ignored


def find_missing_textures(rp: ResourcePackPaths, names: list[str]) -> list[str]:
    return [n for n in names if not rp.texture_path(n).is_file()]


# --------------------------------------------------------------- generation

def _prepare_function_dirs(
    dp: DatapackPaths | None, options: GenerationOptions, result: BatchResult,
) -> bool:
    """Create give/ and/or display/ once. Returns False if generation cannot continue."""
    if not (options.generate_give or options.generate_display):
        return True
    if dp is None:
        result.log(Level.ERROR, "Datapack folder is required to generate functions.")
        return False
    if options.generate_give and not _ensure_dir(dp.give_dir(options.namespace), dp.root, result):
        return False
    if options.generate_display and not _ensure_dir(dp.display_dir(options.namespace), dp.root, result):
        return False
    return True


def _write_item_functions(
    tx: _Transaction, dp: DatapackPaths | None, options: GenerationOptions,
    name: str, result: BatchResult,
) -> None:
    """Shared by texture items (mode A) and existing models (mode B)."""
    if dp is None:
        return
    rec = options.records.get(name)
    base = rec.base_item if rec else options.base_item
    shown_name = rec.display_name if rec else ""
    extras = rec.extra_components if rec else None
    props = rec.properties() if rec else None
    if rec is not None:
        for message in analyze_item(name, base, shown_name, options.text_format, extras,
                                    props).warnings:
            result.log(Level.WARNING, f"{name}: {message}")
    if options.generate_give:
        _write_logged(tx, dp.give_function_path(options.namespace, name), "give",
                      give_function_content(name, base, shown_name, options.text_format, extras,
                                            props),
                      options.overwrite, result)
    if options.generate_display:
        # An item whose display function is already configured keeps its own mode/scale.
        keep = rec is not None and rec.generate_display
        mode = rec.display_mode if keep else options.display_mode
        scale = rec.display_scale if keep else options.display_scale
        _write_logged(tx, dp.display_function_path(options.namespace, name), "display",
                      display_function_content(name, base, shown_name, options.text_format, extras,
                                               mode, scale, props),
                      options.overwrite, result)


def generate_items(
    rp: ResourcePackPaths,
    dp: DatapackPaths | None,
    names: list[str],
    options: GenerationOptions,
) -> BatchResult:
    """Mode A: item definition + model (+ give function) for each texture name."""
    result = BatchResult()

    if not _ensure_dir(rp.items_dir, rp.root, result):
        return result
    if not _ensure_dir(rp.models_dir, rp.root, result):
        return result

    if not _prepare_function_dirs(dp, options, result):
        return result

    for name in names:
        result.summary.processed += 1

        if not rp.texture_path(name).is_file():
            result.log(Level.WARNING, f"Texture not found: {name}.png")
            if not options.allow_missing_textures:
                result.summary.items_skipped += 1
                result.log(Level.SKIPPED, f"{name}: item skipped (missing texture)")
                continue
            result.log(Level.INFO, f"{name}: generating JSON anyway")

        tx = _Transaction()
        try:
            _write_logged(tx, rp.item_definition_path(name), "items",
                          item_definition_content(name), options.overwrite, result)
            _write_logged(tx, rp.model_path(name), "models/item",
                          item_model_content(name), options.overwrite, result)
            _write_item_functions(tx, dp, options, name, result)
            result.completed.append(name)
        except (OSError, ValueError) as exc:
            tx.rollback()
            result.log(Level.ERROR, f"{name}: failed ({exc}). Files from this item were rolled back.")
    return result


def generate_item_definitions(
    rp: ResourcePackPaths, names: list[str], overwrite: bool = False,
    dp: DatapackPaths | None = None, options: GenerationOptions | None = None,
) -> BatchResult:
    """Mode B: items/<name>.json for existing models (models are never touched).

    With `options`, give/display functions are written through the same pipeline as mode A.
    """
    result = BatchResult()
    if not _ensure_dir(rp.items_dir, rp.root, result):
        return result
    if options is not None and not _prepare_function_dirs(dp, options, result):
        return result

    for name in names:
        result.summary.processed += 1
        if not rp.model_path(name).is_file() and not rp.item_definition_path(name).is_file():
            result.log(Level.WARNING, f"Model not found: models/item/{name}.json")
        tx = _Transaction()
        try:
            _write_logged(tx, rp.item_definition_path(name), "items",
                          item_definition_content(name), overwrite, result)
            if options is not None:
                _write_item_functions(tx, dp, options, name, result)
            result.completed.append(name)
        except (OSError, ValueError) as exc:
            tx.rollback()
            result.log(Level.ERROR, f"{name}: failed ({exc}). Files from this item were rolled back.")
    return result


# ------------------------------------------- editing / regenerating existing items

_GIVE_BASE_RE = re.compile(r"^\s*give\s+@\S+\s+([a-z0-9_.:/-]+)\[")


def recover_base_item(function_path: Path) -> str | None:
    """Read the base item out of an existing give function (so edits keep it)."""
    try:
        first = function_path.read_text(encoding="utf-8").splitlines()[0]
    except (OSError, IndexError, UnicodeDecodeError):
        return None
    match = _GIVE_BASE_RE.match(first)
    if not match:
        return None
    base, err = normalize_base_item(match.group(1))
    return None if err else base


def collect_records(
    dp: DatapackPaths, namespace: str, stored: Mapping[str, ItemRecord], default_base: str,
) -> dict[str, ItemRecord]:
    """Stored items plus items that only exist as give functions (made before the store)."""
    records = dict(stored)
    give_dir = dp.give_dir(namespace)
    if give_dir.is_dir():
        for path in sorted(give_dir.glob("*.mcfunction")):
            name = path.stem
            if name not in records and validate_item_name(name) is None:
                records[name] = ItemRecord(name, base_item=recover_base_item(path) or default_base)
    return dict(sorted(records.items()))


@dataclass
class PlannedFile:
    path: Path
    label: str
    content: str
    delete: bool = False          # remove this file instead of writing it

    @property
    def exists(self) -> bool:
        return self.path.is_file()

    @property
    def changed(self) -> bool:
        if self.delete:
            return self.exists
        try:
            return self.path.read_text(encoding="utf-8") != self.content
        except (OSError, UnicodeDecodeError):
            return True


def plan_item_files(
    dp: DatapackPaths,
    namespace: str,
    records: Mapping[str, ItemRecord],
    names: Sequence[str],
    text_format: str,
    display_was_enabled: Collection[str] = (),
) -> tuple[list[PlannedFile], list[str]]:
    """Files that must be (re)written for these items. Returns (files, errors).

    `display_was_enabled` lists items whose display function was generated earlier; if such an
    item no longer has the option on, only its own display function is planned for removal
    (a display function this tool never generated is never deleted).

    Besides each item's give function, this includes every recipe owned by one of the
    items or producing one of them, so recipe results never go stale after a rename.
    """
    files: dict[Path, PlannedFile] = {}
    errors: list[str] = []
    wanted = set(names)

    for name in names:
        rec = records.get(name)
        if rec is None:
            errors.append(f"{name}: unknown item.")
            continue
        try:
            content = give_function_content(
                rec.name, rec.base_item, rec.display_name, text_format, rec.extra_components,
                rec.properties())
        except ValueError as exc:
            errors.append(f"{name}: {exc}")
            continue
        path = dp.give_function_path(namespace, name)
        files[path] = PlannedFile(path, "give", content)

        display_path = dp.display_function_path(namespace, name)
        if rec.generate_display:
            files[display_path] = PlannedFile(display_path, "display", display_function_content(
                rec.name, rec.base_item, rec.display_name, text_format, rec.extra_components,
                rec.display_mode, rec.display_scale, rec.properties()))
        elif name in display_was_enabled and display_path.is_file():
            files[display_path] = PlannedFile(display_path, "display", "", delete=True)

    for rec in records.values():
        recipe = rec.recipe
        if recipe is None:
            continue
        if rec.name not in wanted and recipe.output_custom_name() not in wanted:
            continue
        check = validate_recipe(recipe, records)
        if not check.ok:
            errors.append(f"Recipe '{recipe.recipe_id}' ({rec.name}): " + " ".join(check.errors))
            continue
        path = dp.recipe_file(namespace, recipe.recipe_id)
        try:
            recipe_data = build_recipe_json(recipe, records, text_format)
        except ValueError as exc:
            errors.append(f"Recipe '{recipe.recipe_id}' ({rec.name}): {exc}")
            continue
        files[path] = PlannedFile(path, "recipe", recipe_json_text(recipe_data))
    return list(files.values()), errors


def item_warnings(
    records: Mapping[str, ItemRecord], names: Sequence[str], text_format: str,
) -> list[str]:
    """Everything worth reporting about these items that does not block generation, e.g.
    extra components the target version does not support and are left out of the commands."""
    out: list[str] = []
    for name in names:
        rec = records.get(name)
        if rec is None:
            continue
        plan = analyze_item(rec.name, rec.base_item, rec.display_name, text_format,
                            rec.extra_components, rec.properties())
        out += [f"{name}: {message}" for message in plan.warnings]
    return out


def regenerate_items(
    dp: DatapackPaths,
    namespace: str,
    records: Mapping[str, ItemRecord],
    names: Sequence[str],
    text_format: str,
    overwrite: bool = True,
    display_was_enabled: Collection[str] = (),
) -> BatchResult:
    """(Re)write give/display functions and recipes for the given items, all-or-nothing."""
    result = BatchResult()
    result.summary.processed = len(names)
    files, errors = plan_item_files(dp, namespace, records, names, text_format,
                                    display_was_enabled)
    for message in errors:
        result.log(Level.ERROR, message)
    if errors:
        result.log(Level.INFO, "Nothing was written.")
        return result
    for message in item_warnings(records, names, text_format):
        result.log(Level.WARNING, message)

    tx = _Transaction()
    try:
        for pf in files:
            if pf.delete:
                if tx.delete(pf.path):
                    result.log(Level.OK, f"Removed {pf.label}/{pf.path.name}")
                continue
            if not _ensure_dir(pf.path.parent, dp.root, result):
                raise OSError("could not create the output directory")
            if pf.exists and not pf.changed:
                result.summary.skipped += 1
                result.log(Level.SKIPPED, f"{pf.label}/{pf.path.name} is already up to date")
                continue
            _write_logged(tx, pf.path, pf.label, pf.content, overwrite, result)
        result.completed.extend(names)
    except OSError as exc:
        tx.rollback()
        result.summary.created = 0
        result.log(Level.ERROR, f"Failed ({exc}). All files from this operation were rolled back.")
    return result
