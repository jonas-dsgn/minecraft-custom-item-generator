"""Path helpers for the resource pack and the datapack."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

DEFAULT_NAMESPACE = "customfood"


@dataclass(frozen=True)
class ResourcePackPaths:
    root: Path

    @property
    def minecraft_dir(self) -> Path:
        return self.root / "assets" / "minecraft"

    @property
    def items_dir(self) -> Path:
        return self.minecraft_dir / "items"

    @property
    def models_dir(self) -> Path:
        return self.minecraft_dir / "models" / "item"

    @property
    def textures_dir(self) -> Path:
        return self.minecraft_dir / "textures" / "item"

    def item_definition_path(self, name: str) -> Path:
        return self.items_dir / f"{name}.json"

    def model_path(self, name: str) -> Path:
        return self.models_dir / f"{name}.json"

    def texture_path(self, name: str) -> Path:
        return self.textures_dir / f"{name}.png"

    def dir_checks(self) -> list[tuple[str, Path, bool]]:
        return [
            ("assets/minecraft/items/", self.items_dir, self.items_dir.is_dir()),
            ("assets/minecraft/models/item/", self.models_dir, self.models_dir.is_dir()),
            ("assets/minecraft/textures/item/", self.textures_dir, self.textures_dir.is_dir()),
        ]

    def status(self) -> tuple[str, str]:
        """Return (state, message); state is 'ok', 'partial' or 'invalid'."""
        if not self.root.is_dir():
            return "invalid", "Folder does not exist."
        if not self.minecraft_dir.is_dir():
            return "invalid", "Missing assets/minecraft/ - not a resource pack root?"
        missing = [label for label, _, ok in self.dir_checks() if not ok]
        if missing:
            return "partial", "Missing: " + ", ".join(missing)
        if not (self.root / "pack.mcmeta").is_file():
            return "partial", "pack.mcmeta not found (folders OK)."
        return "ok", "Valid resource pack structure."


@dataclass(frozen=True)
class DatapackPaths:
    root: Path

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    def namespace_dir(self, namespace: str) -> Path:
        return self.data_dir / namespace

    def function_dir(self, namespace: str) -> Path:
        """Use the directory name the pack already uses.

        Minecraft 1.21+ uses 'function'; older versions used 'functions'.
        New packs default to the modern singular name.
        """
        ns = self.namespace_dir(namespace)
        if (ns / "function").is_dir():
            return ns / "function"
        if (ns / "functions").is_dir():
            return ns / "functions"
        return ns / "function"

    def recipe_dir(self, namespace: str) -> Path:
        """'recipe' (1.21+), or the legacy 'recipes' folder if the pack already uses it."""
        ns = self.namespace_dir(namespace)
        if (ns / "recipe").is_dir():
            return ns / "recipe"
        if (ns / "recipes").is_dir():
            return ns / "recipes"
        return ns / "recipe"

    def recipe_file(self, namespace: str, recipe_id: str) -> Path:
        return self.recipe_dir(namespace) / f"{recipe_id}.json"

    def give_dir(self, namespace: str) -> Path:
        return self.function_dir(namespace) / "give"

    def give_function_path(self, namespace: str, name: str) -> Path:
        return self.give_dir(namespace) / f"{name}.mcfunction"

    def display_dir(self, namespace: str) -> Path:
        return self.function_dir(namespace) / "display"

    def display_function_path(self, namespace: str, name: str) -> Path:
        return self.display_dir(namespace) / f"{name}.mcfunction"

    def detect_namespaces(self) -> list[str]:
        """Namespaces present under data/ (the vanilla 'minecraft' one is excluded)."""
        if not self.data_dir.is_dir():
            return []
        try:
            return sorted(
                p.name for p in self.data_dir.iterdir()
                if p.is_dir() and p.name != "minecraft"
            )
        except OSError:
            return []

    def status(self, namespace: str) -> tuple[str, str]:
        if not self.root.is_dir():
            return "invalid", "Folder does not exist."
        if not self.data_dir.is_dir():
            return "invalid", "Missing data/ - not a datapack root?"
        if not (self.root / "pack.mcmeta").is_file():
            return "partial", "pack.mcmeta not found."
        if namespace and not self.namespace_dir(namespace).is_dir():
            return "partial", f"Namespace folder data/{namespace}/ will be created."
        if namespace and not self.function_dir(namespace).is_dir():
            return "partial", "Function folder will be created."
        return "ok", "Valid datapack structure."
