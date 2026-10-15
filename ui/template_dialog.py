"""'New Pack Template' dialog: pick a name and a place, get an empty resource pack and datapack."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout,
)

from core.templates import (
    DEFAULT_PRESET, FORMATS_CHECKED_ON, PRESETS, FormatRange, TemplateError, TemplateOptions,
    TemplateResult, check_options, create_templates, plan_templates,
)
from ui.widgets import NoWheelComboBox, NoWheelSpinBox

CUSTOM_KEY = "custom"


class PackTemplateDialog(QDialog):
    def __init__(self, start_dir: str, namespace: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("New Pack Template")
        self.setMinimumWidth(560)
        self.created: TemplateResult | None = None      # set after a successful Create
        self.load_into_tool = True

        root = QVBoxLayout(self)
        intro = QLabel("Creates an empty resource pack and datapack with the right folders and "
                       "pack.mcmeta. Nothing is overwritten.")
        intro.setObjectName("hint")
        intro.setWordWrap(True)
        root.addWidget(intro)

        form = QFormLayout()
        self.name_edit = QLineEdit("My Items")
        self.name_edit.setToolTip("Used for the folder names: '<name> - Resource Pack' and "
                                  "'<name> - Data Pack'.")
        self.desc_edit = QLineEdit()
        self.desc_edit.setPlaceholderText("Shown in the pack list (empty = the pack name)")
        self.ns_edit = QLineEdit(namespace)
        self.ns_edit.setToolTip("Namespace of the datapack: functions go to data/<namespace>/function/.")
        self.preset_combo = NoWheelComboBox()
        for preset in PRESETS:
            self.preset_combo.addItem(preset.label, preset.key)
        self.preset_combo.addItem("Custom formats...", CUSTOM_KEY)
        self.preset_combo.setToolTip(f"Pack formats of these versions were checked on {FORMATS_CHECKED_ON}. "
                                     "Use Custom for versions released after that.")
        form.addRow("Pack name", self.name_edit)
        form.addRow("Description", self.desc_edit)
        form.addRow("Namespace", self.ns_edit)
        form.addRow("Minecraft version", self.preset_combo)
        root.addLayout(form)

        self.custom_box = QGroupBox("Custom pack formats (from the release notes of your version)")
        grid = QGridLayout(self.custom_box)
        self.dp_min_major, self.dp_min_minor, self.dp_max_major = self._spin(107), self._spin(1), self._spin(121)
        self.rp_min_major, self.rp_min_minor, self.rp_max_major = self._spin(88), self._spin(0), self._spin(97)
        for row, (title, widgets) in enumerate((
                ("Data pack", (self.dp_min_major, self.dp_min_minor, self.dp_max_major)),
                ("Resource pack", (self.rp_min_major, self.rp_min_minor, self.rp_max_major)))):
            grid.addWidget(QLabel(title), row, 0)
            grid.addWidget(QLabel("min"), row, 1)
            grid.addWidget(widgets[0], row, 2)
            grid.addWidget(QLabel("."), row, 3)
            grid.addWidget(widgets[1], row, 4)
            grid.addWidget(QLabel("max (any minor)"), row, 5)
            grid.addWidget(widgets[2], row, 6)
        grid.setColumnStretch(7, 1)
        root.addWidget(self.custom_box)

        where = QHBoxLayout()
        self.dir_edit = QLineEdit(start_dir)
        self.dir_edit.setPlaceholderText("Folder to create the packs in")
        self.browse_btn = QPushButton("Browse...")
        where.addWidget(QLabel("Save in"))
        where.addWidget(self.dir_edit, 1)
        where.addWidget(self.browse_btn)
        root.addLayout(where)

        self.rp_chk = QCheckBox("Resource pack")
        self.rp_chk.setChecked(True)
        self.dp_chk = QCheckBox("Datapack")
        self.dp_chk.setChecked(True)
        self.load_chk = QCheckBox("Use the new packs in this tool")
        self.load_chk.setChecked(True)
        checks = QHBoxLayout()
        for chk in (self.rp_chk, self.dp_chk, self.load_chk):
            checks.addWidget(chk)
        checks.addStretch(1)
        root.addLayout(checks)

        root.addWidget(QLabel("This will be created"))
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        self.preview.setMinimumHeight(220)
        root.addWidget(self.preview, 1)

        self.error_lbl = QLabel("")
        self.error_lbl.setWordWrap(True)
        self.error_lbl.setStyleSheet("color:#ff6b6b;")
        root.addWidget(self.error_lbl)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.create_btn = self.buttons.addButton("Create Template Pack", QDialogButtonBox.AcceptRole)
        self.create_btn.setDefault(True)
        self.buttons.rejected.connect(self.reject)
        self.create_btn.clicked.connect(self._create)
        root.addWidget(self.buttons)

        self.browse_btn.clicked.connect(self._browse)
        for edit in (self.name_edit, self.desc_edit, self.ns_edit, self.dir_edit):
            edit.textChanged.connect(self._refresh)
        for w in (self.rp_chk, self.dp_chk):
            w.toggled.connect(self._refresh)
        self.preset_combo.currentIndexChanged.connect(self._refresh)
        for spin in (self.dp_min_major, self.dp_min_minor, self.dp_max_major,
                     self.rp_min_major, self.rp_min_minor, self.rp_max_major):
            spin.valueChanged.connect(self._refresh)
        self._refresh()

    @staticmethod
    def _spin(value: int) -> NoWheelSpinBox:
        spin = NoWheelSpinBox()
        spin.setRange(0, 9999)
        spin.setValue(value)
        return spin

    # ----------------------------------------------------------------- options
    def options(self) -> TemplateOptions:
        if self.preset_combo.currentData() == CUSTOM_KEY:
            data = FormatRange((self.dp_min_major.value(), self.dp_min_minor.value()),
                               self.dp_max_major.value())
            resource = FormatRange((self.rp_min_major.value(), self.rp_min_minor.value()),
                                   self.rp_max_major.value())
        else:
            preset = next((p for p in PRESETS if p.key == self.preset_combo.currentData()), DEFAULT_PRESET)
            data, resource = preset.data_pack, preset.resource_pack
        return TemplateOptions(
            parent=Path(self.dir_edit.text().strip()), name=self.name_edit.text(),
            description=self.desc_edit.text(), namespace=self.ns_edit.text().strip(),
            data_pack_formats=data, resource_pack_formats=resource,
            create_resource_pack=self.rp_chk.isChecked(), create_data_pack=self.dp_chk.isChecked())

    def _refresh(self) -> None:
        self.custom_box.setVisible(self.preset_combo.currentData() == CUSTOM_KEY)
        self.ns_edit.setEnabled(self.dp_chk.isChecked())
        opts = self.options()
        errors = check_options(opts)
        self.error_lbl.setText("\n".join(errors))
        self.create_btn.setEnabled(not errors)
        if errors:
            self.preview.setPlainText("")
            return
        plan = plan_templates(opts)
        parts = [f"in {opts.parent}", "", plan.tree_text()]
        for root in (plan.resource_root, plan.data_root):
            if root is not None:
                parts += ["", f"{root.name}/pack.mcmeta", plan.files[root / "pack.mcmeta"].rstrip("\n")]
        self.preview.setPlainText("\n".join(parts))

    # ----------------------------------------------------------------- actions
    def _browse(self) -> None:
        start = self.dir_edit.text().strip() or str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "Choose where to save the template", start)
        if folder:
            self.dir_edit.setText(folder)

    def _create(self) -> None:
        try:
            self.created = create_templates(self.options())
        except (TemplateError, ValueError) as exc:
            QMessageBox.warning(self, "Template not created", str(exc))
            return
        self.load_into_tool = self.load_chk.isChecked()
        self.accept()
