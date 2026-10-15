"""Recipe editor dialog (shaped / shapeless) with live validation and JSON preview."""
from __future__ import annotations

from html import escape
from typing import Mapping

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QApplication, QComboBox, QCompleter, QDialog, QDialogButtonBox, QFormLayout, QFrame,
    QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QScrollArea,
    QSpinBox, QVBoxLayout, QWidget,
)

from core.items import ItemRecord
from core.recipes import (
    CUSTOM_PREFIX, MAX_COUNT, Recipe, build_recipe_json, normalize_ingredient,
    normalize_output, recipe_json_text, validate_recipe,
)
from core.vanilla_items import VANILLA_ITEMS, VANILLA_TAGS
from ui.widgets import NoWheelComboBox


class RecipeDialog(QDialog):
    def __init__(self, owner: str, records: Mapping[str, ItemRecord], namespace: str,
                 recipe: Recipe | None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Recipe for {owner}")
        self.setMinimumSize(420, 320)
        screen = (parent.screen() if parent is not None else QApplication.primaryScreen())
        avail = screen.availableGeometry() if screen else None
        if avail is not None:     # never larger than the screen
            self.resize(min(820, int(avail.width() * 0.95)), min(560, int(avail.height() * 0.9)))
        else:
            self.resize(820, 560)
        self.owner = owner
        self.records = records
        self.namespace = namespace
        self.recipe: Recipe | None = None   # set when the user saves

        start = recipe or Recipe(recipe_id=owner, output=f"{CUSTOM_PREFIX}{owner}")
        customs = [f"{CUSTOM_PREFIX}{n}" for n in sorted(records)]
        self._choices = [""] + customs + VANILLA_TAGS + VANILLA_ITEMS

        # The two columns live in a scroll area; Save/Cancel stay pinned below it.
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        root = QHBoxLayout(body)
        root.setContentsMargins(0, 0, 0, 0)
        left = QVBoxLayout()
        root.addLayout(left, 0)
        right = QVBoxLayout()
        root.addLayout(right, 1)

        # --- settings
        form = QFormLayout()
        self.kind_combo = NoWheelComboBox()
        self.kind_combo.addItem("Shaped (3x3 pattern)", "shaped")
        self.kind_combo.addItem("Shapeless (any arrangement)", "shapeless")
        self.kind_combo.setCurrentIndex(0 if start.kind == "shaped" else 1)
        form.addRow("Type", self.kind_combo)

        self.id_edit = QLineEdit(start.recipe_id)
        self.id_edit.setToolTip(f"Saved as data/{namespace}/recipe/<id>.json")
        form.addRow("Recipe ID", self.id_edit)

        self.output_combo = NoWheelComboBox()
        self.output_combo.setEditable(True)
        self.output_combo.setInsertPolicy(QComboBox.NoInsert)
        self.output_combo.addItems(customs)
        self.output_combo.setEditText(start.output)
        self.output_combo.setToolTip("custom:<item> keeps the item model and display name; "
                                     "or type a vanilla ID such as minecraft:diamond.")
        form.addRow("Output item", self.output_combo)

        self.count_spin = QSpinBox()
        self.count_spin.setRange(1, MAX_COUNT)
        self.count_spin.setValue(max(1, min(MAX_COUNT, start.count)))
        form.addRow("Output count", self.count_spin)
        left.addLayout(form)

        # --- grid
        grid_box = QGroupBox("Crafting grid")
        grid = QGridLayout(grid_box)
        self.slots: list[QComboBox] = []
        for i in range(9):
            combo = NoWheelComboBox()
            combo.setEditable(True)
            combo.setInsertPolicy(QComboBox.NoInsert)
            combo.addItems(self._choices)
            combo.setMinimumWidth(210)
            combo.setEditText(start.slots[i])
            combo.lineEdit().setPlaceholderText("(empty)")
            completer = combo.completer()
            completer.setCaseSensitivity(Qt.CaseInsensitive)
            completer.setFilterMode(Qt.MatchContains)
            completer.setCompletionMode(QCompleter.PopupCompletion)
            grid.addWidget(combo, i // 3, i % 3)
            self.slots.append(combo)
        left.addWidget(grid_box)

        self.mode_hint = QLabel()
        self.mode_hint.setObjectName("hint")
        self.mode_hint.setWordWrap(True)
        left.addWidget(self.mode_hint)
        left.addStretch(1)

        # --- preview
        right.addWidget(QLabel("Preview (data/%s/recipe/<id>.json)" % namespace))
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.preview.setMinimumHeight(140)
        self.preview.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        right.addWidget(self.preview, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.RichText)
        right.addWidget(self.status)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        self.save_button = buttons.button(QDialogButtonBox.Save)
        outer.addWidget(buttons)

        self.kind_combo.currentIndexChanged.connect(self._update)
        self.id_edit.textChanged.connect(self._update)
        self.output_combo.editTextChanged.connect(self._update)
        self.count_spin.valueChanged.connect(self._update)
        for combo in self.slots:
            combo.editTextChanged.connect(self._update)
        self._update()

    # ------------------------------------------------------------------
    def _collect(self) -> Recipe:
        return Recipe(
            kind=self.kind_combo.currentData(),
            recipe_id=self.id_edit.text().strip(),
            output=normalize_output(self.output_combo.currentText()),
            count=self.count_spin.value(),
            slots=[normalize_ingredient(c.currentText()) for c in self.slots],
        )

    def _update(self, *_args) -> None:
        recipe = self._collect()
        if recipe.kind == "shapeless":
            self.mode_hint.setText("Shapeless: slot positions are ignored; every filled slot "
                                   "becomes one required ingredient.")
        else:
            self.mode_hint.setText("Shaped: positions matter. Empty rows/columns around the "
                                   "pattern are trimmed, so it can be placed anywhere in the grid.")
        check = validate_recipe(recipe, self.records)
        lines = [f'<span style="color:#ff6b6b">&#10007; {escape(e)}</span>' for e in check.errors]
        lines += [f'<span style="color:#e0a030">&#9888; {escape(w)}</span>' for w in check.warnings]
        if check.ok:
            lines.append('<span style="color:#6fcf73">&#10003; Recipe is valid.</span>')
            self.preview.setPlainText(recipe_json_text(build_recipe_json(recipe, self.records)))
        else:
            self.preview.setPlainText("// Fix the problems below to see the preview.")
        self.status.setText("<br>".join(lines))
        self.save_button.setEnabled(check.ok)

    def _save(self) -> None:
        recipe = self._collect()
        if validate_recipe(recipe, self.records).ok:
            self.recipe = recipe
            self.accept()
