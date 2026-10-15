"""Create an empty resource pack and datapack that this tool accepts right away.

`plan_templates` says exactly what would be written (nothing is touched), `create_templates`
writes it. Nothing is ever overwritten: if a target folder exists the request is refused, and
if writing fails half way, everything created so far is removed again.

Formats follow the pack.mcmeta reference for packs that only support 1.21.9 or newer
(data pack format >= 82, resource pack format >= 65): `min_format` / `max_format` are
required, `pack_format` and `supported_formats` must be absent. The numbers below were taken
from the Minecraft Java Edition release notes and are dated, because every new game version
adds one; the dialog's "Custom" choice covers versions newer than this table.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .project_paths import DEFAULT_NAMESPACE
from .validation import validate_namespace

FORMATS_CHECKED_ON = "2026-10-13"       # when PRESETS were last compared with the release notes
MIN_DATA_MAJOR = 82                     # below this, pack.mcmeta also needs pack_format
MIN_RESOURCE_MAJOR = 65
MAX_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 200

RESOURCE_SUFFIX = " - Resource Pack"
DATA_SUFFIX = " - Data Pack"

_BAD_NAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
             *(f"lpt{i}" for i in range(1, 10))}


@dataclass(frozen=True)
class FormatRange:
    """Supported pack formats. `max` may be a plain int: any minor version of that major."""
    min: tuple[int, int]
    max: tuple[int, int] | int

    def min_json(self) -> list[int]:
        return [self.min[0], self.min[1]]

    def max_json(self) -> list[int] | int:
        return self.max if isinstance(self.max, int) else [self.max[0], self.max[1]]

    def max_tuple(self) -> tuple[int, int]:
        return (self.max, 2 ** 31 - 1) if isinstance(self.max, int) else self.max


@dataclass(frozen=True)
class VersionPreset:
    key: str
    label: str
    data_pack: FormatRange
    resource_pack: FormatRange


# Data pack / resource pack formats: 26.2 = 107.1 / 88.0, 26.3 = 121.0 / 97.1.
PRESETS: tuple[VersionPreset, ...] = (
    VersionPreset("26.2+", "26.2 and newer (26.2 - 26.3)",
                  FormatRange((107, 1), 121), FormatRange((88, 0), 97)),
    VersionPreset("26.3", "26.3 only",
                  FormatRange((121, 0), 121), FormatRange((97, 1), 97)),
    VersionPreset("26.2", "26.2 only",
                  FormatRange((107, 1), 107), FormatRange((88, 0), 88)),
)
DEFAULT_PRESET = PRESETS[0]


def check_formats(data_pack: FormatRange, resource_pack: FormatRange) -> list[str]:
    errors: list[str] = []
    for what, rng, floor in (("Data pack", data_pack, MIN_DATA_MAJOR),
                             ("Resource pack", resource_pack, MIN_RESOURCE_MAJOR)):
        if any(n < 0 for n in rng.min) or rng.min[0] < floor:
            errors.append(f"{what}: the minimum format must be {floor} or higher (templates are for "
                          "Minecraft 1.21.9 and newer; older packs need pack_format).")
        elif rng.min > rng.max_tuple():
            errors.append(f"{what}: the minimum format is higher than the maximum.")
    return errors


def validate_pack_name(name: str) -> str | None:
    """Error message for a pack name that cannot be used as a folder name, else None."""
    if not name.strip():
        return "Pack name is empty."
    if name != name.strip():
        return "Pack name must not start or end with a space."
    if len(name) > MAX_NAME_LENGTH:
        return f"Pack name is too long (max {MAX_NAME_LENGTH} characters)."
    bad = _BAD_NAME_CHARS.search(name)
    if bad:
        if not bad.group().isprintable():
            return "Pack name must not contain control characters."
        return f"Pack name must not contain {bad.group()!r}."
    if name.endswith("."):
        return "Pack name must not end with a dot."
    if name.split(".")[0].lower() in _RESERVED:
        return "This pack name is reserved by Windows."
    return None


def mcmeta_text(description: str, formats: FormatRange) -> str:
    """pack.mcmeta for a pack that supports Minecraft 1.21.9 and newer only.

    Written by hand instead of json.dumps(indent=2) so the format lists stay on one line.
    """
    def js(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False)

    return (
        "{\n"
        '  "pack": {\n'
        f'    "description": {js(_CONTROL.sub("", description))},\n'
        f'    "min_format": {js(formats.min_json())},\n'
        f'    "max_format": {js(formats.max_json())}\n'
        "  }\n"
        "}\n"
    )


@dataclass(frozen=True)
class TemplateOptions:
    parent: Path                                  # where the pack folders are created
    name: str
    description: str = ""                         # defaults to the pack name
    namespace: str = DEFAULT_NAMESPACE            # data/<namespace>/ in the datapack
    data_pack_formats: FormatRange = DEFAULT_PRESET.data_pack
    resource_pack_formats: FormatRange = DEFAULT_PRESET.resource_pack
    create_resource_pack: bool = True
    create_data_pack: bool = True

    @property
    def resource_root(self) -> Path:
        return self.parent / f"{self.name}{RESOURCE_SUFFIX}"

    @property
    def data_root(self) -> Path:
        return self.parent / f"{self.name}{DATA_SUFFIX}"

    @property
    def shown_description(self) -> str:
        return self.description.strip() or self.name


def check_options(opts: TemplateOptions) -> list[str]:
    """Everything that stops the template from being created (empty list = ready)."""
    errors: list[str] = []
    if not (opts.create_resource_pack or opts.create_data_pack):
        errors.append("Select at least one pack to create.")
    name_error = validate_pack_name(opts.name)
    if name_error:
        errors.append(name_error)
    if len(opts.shown_description) > MAX_DESCRIPTION_LENGTH:
        errors.append(f"Description is too long (max {MAX_DESCRIPTION_LENGTH} characters).")
    if opts.create_data_pack:
        ns_error = validate_namespace(opts.namespace)
        if ns_error:
            errors.append(ns_error)
    format_errors = check_formats(opts.data_pack_formats, opts.resource_pack_formats)
    errors += [e for e in format_errors if e.startswith("Data pack") and opts.create_data_pack]
    errors += [e for e in format_errors if e.startswith("Resource pack") and opts.create_resource_pack]
    if str(opts.parent).strip() in ("", "."):
        errors.append("Choose where to save the template.")
    elif not opts.parent.is_absolute():
        # a relative folder would depend on where the program happens to be running
        errors.append("Enter the full path of the folder to save in.")
    elif not opts.parent.is_dir():
        errors.append("The save location does not exist or is not a folder.")
    if not name_error and opts.parent.is_absolute() and opts.parent.is_dir():
        for wanted, root in ((opts.create_resource_pack, opts.resource_root),
                             (opts.create_data_pack, opts.data_root)):
            if wanted and (root.exists() or root.is_symlink()):
                errors.append(f"'{root.name}' already exists in that location. Nothing is "
                              "overwritten; choose another name or location.")
    return errors


@dataclass
class TemplatePlan:
    resource_root: Path | None = None
    data_root: Path | None = None
    directories: list[Path] = field(default_factory=list)          # parents before children
    files: dict[Path, str] = field(default_factory=dict)

    def tree_text(self) -> str:
        """The folder tree as it will be created, for the preview."""
        lines: list[str] = []
        for root in (self.resource_root, self.data_root):
            if root is None:
                continue
            lines.append(f"{root.name}/")
            entries = sorted(
                [(p.relative_to(root), True) for p in self.directories if p != root and root in p.parents]
                + [(p.relative_to(root), False) for p in self.files if root in p.parents])
            leaves = {rel for rel, is_dir in entries if is_dir}
            for rel, is_dir in entries:
                if is_dir and any(other != rel and rel in other.parents for other in leaves):
                    continue                                       # only show deepest folders
                lines.append(f"    {rel.as_posix()}{'/' if is_dir else ''}")
        return "\n".join(lines)


def plan_templates(opts: TemplateOptions) -> TemplatePlan:
    """What would be written. Raises ValueError (all problems in the message) if not allowed."""
    errors = check_options(opts)
    if errors:
        raise ValueError(" ".join(errors))
    plan = TemplatePlan()
    description = opts.shown_description
    if opts.create_resource_pack:
        root = opts.resource_root
        plan.resource_root = root
        mc = root / "assets" / "minecraft"
        plan.directories += [root, root / "assets", mc, mc / "items", mc / "models",
                             mc / "models" / "item", mc / "textures", mc / "textures" / "item"]
        plan.files[root / "pack.mcmeta"] = mcmeta_text(description, opts.resource_pack_formats)
    if opts.create_data_pack:
        root = opts.data_root
        plan.data_root = root
        ns = root / "data" / opts.namespace
        plan.directories += [root, root / "data", ns, ns / "function", ns / "function" / "give"]
        plan.files[root / "pack.mcmeta"] = mcmeta_text(description, opts.data_pack_formats)
    return plan


@dataclass
class TemplateResult:
    resource_root: Path | None
    data_root: Path | None
    directories: int
    files: int


class TemplateError(OSError):
    """Writing the template failed; everything already created was removed again."""


def create_templates(opts: TemplateOptions) -> TemplateResult:
    """Write the template. Never overwrites; rolls back everything it created on failure."""
    plan = plan_templates(opts)
    roots = [r for r in (plan.resource_root, plan.data_root) if r is not None]
    created_roots: list[Path] = []
    try:
        for directory in plan.directories:
            if directory in roots:
                directory.mkdir()                                  # raises if it appeared meanwhile
                created_roots.append(directory)
            else:
                directory.mkdir(exist_ok=True)
        for path, text in plan.files.items():
            with open(path, "x", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
    except OSError as exc:
        import shutil
        for root in created_roots:                                 # only what this call created
            shutil.rmtree(root, ignore_errors=True)
        raise TemplateError(f"Could not create the template: {exc}") from exc
    return TemplateResult(plan.resource_root, plan.data_root, len(plan.directories), len(plan.files))
