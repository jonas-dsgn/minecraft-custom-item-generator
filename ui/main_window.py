"""Main window. All filesystem / Minecraft logic lives in core/."""
from __future__ import annotations

from html import escape
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QGridLayout,
    QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
    QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QTabWidget, QVBoxLayout, QWidget,
)

from core import generator as gen
from core.generator import BatchResult, Level
from core.attributes import AttributeModifier
from core.components import RARITIES
from core.tooltip import build_tooltip, item_traits
from core.item_rules import item_facts, max_stack_limit
from core.items import DEFAULT_BASE_ITEM, STORE_FILENAME, ItemRecord, ProjectStore, StoreError
from core.ids import function_id
from core.project_paths import DEFAULT_NAMESPACE, DatapackPaths, ResourcePackPaths
from core.recipes import Recipe
from core.text_components import TEXT_JSON, TEXT_SNBT, Segment
from core.validation import (
    DEFAULT_DISPLAY_MODE, DEFAULT_SCALE, normalize_base_item, parse_names, validate_namespace,
)
from ui.recipe_dialog import RecipeDialog
from ui.template_dialog import PackTemplateDialog
from ui.widgets import (
    AttributeEditor, DisplayOptionsWidget, EnchantmentEditor, FormatReferenceWidget, LoreEditor,
    NoWheelComboBox, NoWheelSpinBox, PageLayout, TooltipPreview,
)

COLORS = {"ok": "#4caf50", "partial": "#e0a030", "invalid": "#e05555", "none": "#777777"}
LEVEL_COLORS = {
    Level.OK: "#6fcf73", Level.INFO: "#8ab4f8", Level.WARNING: "#e0a030",
    Level.SKIPPED: "#b0b0b0", Level.ERROR: "#ff6b6b",
}

STYLE = """
QWidget { background-color: #1e1f22; color: #dcdde0; font-size: 13px; }
QGroupBox { border: 1px solid #3a3c40; border-radius: 6px; margin-top: 10px; padding: 8px 8px 6px 8px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #9aa0a6; }
QLineEdit, QPlainTextEdit, QListWidget, QComboBox {
    background-color: #2b2d31; border: 1px solid #3a3c40; border-radius: 4px; padding: 3px;
    selection-background-color: #3b6fb6;
}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus { border-color: #4a86d8; }
QPushButton { background-color: #34373c; border: 1px solid #44474d; border-radius: 4px; padding: 5px 12px; }
QPushButton:hover { background-color: #3f4348; }
QPushButton:disabled { color: #70737a; }
QPushButton#primary { background-color: #2f6fca; border-color: #3b7ddb; font-weight: bold; padding: 7px 16px; }
QPushButton#primary:hover { background-color: #3a7ddc; }
QCheckBox::indicator { width: 14px; height: 14px; }
QScrollArea { border: none; }
QScrollBar:vertical { background: #25262a; width: 14px; margin: 0; }
QScrollBar::handle:vertical { background: #4a4d53; min-height: 30px; border-radius: 5px; margin: 2px; }
QScrollBar::handle:vertical:hover { background: #5b5f66; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: #25262a; height: 14px; margin: 0; }
QScrollBar::handle:horizontal { background: #4a4d53; min-width: 30px; border-radius: 5px; margin: 2px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QWidget#footer { background-color: #25262a; border-top: 1px solid #3a3c40; }
QLabel#hint { color: #8d9299; }
QTabWidget::pane { border: 1px solid #3a3c40; border-radius: 6px; top: -1px; }
QTabBar::tab { background: #2b2d31; border: 1px solid #3a3c40; padding: 5px 14px; margin-right: 2px;
               border-top-left-radius: 4px; border-top-right-radius: 4px; }
QTabBar::tab:selected { background: #34373c; color: #ffffff; }
"""


class MainWindow(QMainWindow):
    # Minimum height of the tab area: tab C (item editor) needs more room than tabs A/B.
    TAB_MIN_HEIGHT = 400
    TAB_MIN_HEIGHT_EDITOR = 590

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Minecraft Custom Item Generator")
        self.setMinimumSize(560, 420)
        screen = QApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else None
        self.resize(min(1000, int(avail.width() * 0.92)) if avail else 1000,
                    min(900, int(avail.height() * 0.92)) if avail else 900)
        self.settings = QSettings("MinecraftItemGenerator", "ItemGenerator")
        self.rp: ResourcePackPaths | None = None
        self.dp: DatapackPaths | None = None
        self.store: ProjectStore | None = None
        self._current_item: str | None = None
        self._was_maximized = False
        self._item_recipe: Recipe | None = None
        self._build_ui()
        self._fullscreen_shortcut = QShortcut(QKeySequence("F11"), self)
        self._fullscreen_shortcut.activated.connect(self._toggle_fullscreen)
        self.setStyleSheet(STYLE)
        self._load_settings()

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        # Whole interface scrolls vertically (one scroll area, no nested ones); the footer with
        # the main action stays visible below it.
        shell = QWidget()
        shell_lay = QVBoxLayout(shell)
        shell_lay.setContentsMargins(0, 0, 0, 0)
        shell_lay.setSpacing(0)
        self.setCentralWidget(shell)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        central = QWidget()
        self.scroll.setWidget(central)
        shell_lay.addWidget(self.scroll, 1)
        root = PageLayout(central)
        root.setSpacing(6)

        root.addWidget(self._build_paths_group())
        root.addWidget(self._build_status_group())

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_mode_a(), "A. From textures")
        self.tabs.addTab(self._build_mode_b(), "B. Existing models")
        self.tabs.addTab(self._build_items_tab(), "C. Name && recipe")
        self.tabs.setMinimumHeight(self.TAB_MIN_HEIGHT)
        root.addWidget(self.tabs, 3)

        root.addWidget(self._build_settings_group())
        root.addWidget(self._build_log_group(), 2)
        shell_lay.addWidget(self._build_footer())
        self.tabs.currentChanged.connect(self._update_footer)
        self._update_footer()

    def _build_paths_group(self) -> QGroupBox:
        box = QGroupBox("Project paths")
        grid = QGridLayout(box)
        grid.setColumnStretch(2, 1)

        self.rp_edit = QLineEdit()
        self.rp_edit.setPlaceholderText("Resource pack root folder")
        self.rp_browse = QPushButton("Browse...")
        self.rp_dot = QLabel("●")
        self.rp_msg = QLabel("No folder selected")
        self.rp_msg.setObjectName("hint")

        self.dp_edit = QLineEdit()
        self.dp_edit.setPlaceholderText("Datapack root folder")
        self.dp_browse = QPushButton("Browse...")
        self.dp_dot = QLabel("●")
        self.dp_msg = QLabel("No folder selected")
        self.dp_msg.setObjectName("hint")

        for row, (title, edit, btn, dot, msg) in enumerate([
            ("Resource Pack Folder", self.rp_edit, self.rp_browse, self.rp_dot, self.rp_msg),
            ("Datapack Folder", self.dp_edit, self.dp_browse, self.dp_dot, self.dp_msg),
        ]):
            grid.addWidget(QLabel(title), row, 0)
            grid.addWidget(dot, row, 1)
            grid.addWidget(edit, row, 2)
            grid.addWidget(btn, row, 3)
            grid.addWidget(msg, row, 4)
            self._set_dot(dot, "none")

        self.template_btn = QPushButton("New Pack Template...")
        self.template_btn.setToolTip("Create an empty resource pack and datapack (folders and "
                                     "pack.mcmeta) in a folder you choose, ready to use here.")
        self.template_btn.clicked.connect(self._new_template)
        grid.addWidget(self.template_btn, 0, 5, 2, 1, Qt.AlignVCenter)   # beside both rows: no extra height

        self.rp_browse.clicked.connect(self._browse_rp)
        self.dp_browse.clicked.connect(self._browse_dp)
        self.rp_edit.editingFinished.connect(self._refresh_rp)
        self.dp_edit.editingFinished.connect(self._refresh_dp)
        return box

    def _build_status_group(self) -> QGroupBox:
        box = QGroupBox("Detected folders")
        grid = QGridLayout(box)
        grid.setVerticalSpacing(2)
        grid.setColumnStretch(2, 1)
        self.dir_rows: list[tuple[QLabel, QLabel, QLabel]] = []
        titles = ["items/", "models/item/", "textures/item/", "datapack give/", "datapack display/"]
        for row, title in enumerate(titles):
            name = QLabel(title)
            dot = QLabel("●")
            path = QLabel("-")
            path.setObjectName("hint")
            path.setTextInteractionFlags(Qt.TextSelectableByMouse)
            grid.addWidget(name, row, 0)
            grid.addWidget(dot, row, 1)
            grid.addWidget(path, row, 2)
            self._set_dot(dot, "none")
            self.dir_rows.append((name, dot, path))
        return box

    def _build_mode_a(self) -> QGroupBox:
        box = QGroupBox("A. Generate from texture names")
        lay = QVBoxLayout(box)
        hint = QLabel("One texture name per line (commas also work), without .png.\n"
                      "Textures are expected in textures/item/<name>.png and are never created.")
        hint.setObjectName("hint")
        lay.addWidget(hint)
        self.names_edit = QPlainTextEdit()
        self.names_edit.setPlaceholderText("mr_electrocks\nruby_sword\ncustom_apple")
        lay.addWidget(self.names_edit, 1)
        self.generate_btn = QPushButton("Generate Items")
        self.generate_btn.setObjectName("primary")
        self.generate_btn.clicked.connect(self._on_generate)
        lay.addWidget(self.generate_btn)
        return box

    def _build_mode_b(self) -> QGroupBox:
        box = QGroupBox("B. Existing models")
        lay = QVBoxLayout(box)
        hint = QLabel("Creates items/<model>.json (if missing) and the give / display functions "
                      "for the selected models,\nusing the datapack settings below. "
                      "No textures or model files are created or modified.")
        hint.setObjectName("hint")
        lay.addWidget(hint)

        row = QHBoxLayout()
        self.scan_btn = QPushButton("Scan Existing Models")
        self.select_all_btn = QPushButton("Select All")
        self.select_none_btn = QPushButton("Clear")
        row.addWidget(self.scan_btn)
        row.addStretch(1)
        row.addWidget(self.select_all_btn)
        row.addWidget(self.select_none_btn)
        lay.addLayout(row)

        self.models_list = QListWidget()
        self.models_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        lay.addWidget(self.models_list, 1)

        self.defs_btn = QPushButton("Generate Missing Item Definitions")
        lay.addWidget(self.defs_btn)

        self.scan_btn.clicked.connect(self._on_scan)
        self.select_all_btn.clicked.connect(self.models_list.selectAll)
        self.select_none_btn.clicked.connect(self.models_list.clearSelection)
        self.defs_btn.clicked.connect(self._on_generate_defs)
        return box

    def _build_items_tab(self) -> QGroupBox:
        box = QGroupBox("C. Item editor: name, lore, properties and crafting recipe")
        self.items_box = box
        outer = QHBoxLayout(box)

        left = QVBoxLayout()
        left.addWidget(QLabel("In-game tooltip"))
        self.tooltip = TooltipPreview()
        left.addWidget(self.tooltip)
        hint = QLabel("Items found in the datapack's give/ folder and in this tool's project file "
                      f"({STORE_FILENAME}).")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        left.addWidget(hint)
        self.items_list = QListWidget()
        self.items_list.setSelectionMode(QAbstractItemView.SingleSelection)
        left.addWidget(self.items_list, 1)
        row = QHBoxLayout()
        refresh = QPushButton("Refresh")
        self.regen_all_btn = QPushButton("Regenerate All Functions")
        self.regen_all_btn.setToolTip("Rewrite every give function (and recipe) from the saved item data.")
        row.addWidget(refresh)
        row.addWidget(self.regen_all_btn)
        left.addLayout(row)
        outer.addLayout(left, 2)

        right = QVBoxLayout()
        self.item_title = QLabel("Select an item from the list")
        self.item_title.setStyleSheet("font-weight: bold; font-size: 14px;")
        right.addWidget(self.item_title)

        self.item_form = QWidget()
        form = QVBoxLayout(self.item_form)
        form.setContentsMargins(0, 0, 0, 0)

        form.addWidget(QLabel("Display name"))
        self.display_edit = QLineEdit()
        self.display_edit.setPlaceholderText("e.g. &6Ancient Sword   (empty = no custom name)")
        form.addWidget(self.display_edit)

        # One clickable code reference for the name AND every lore line (replaces the old
        # static "Codes:" hint). It inserts into whichever of those fields was focused last.
        self.format_ref = FormatReferenceWidget()
        self.format_ref.track(self.display_edit, "Display name")
        self.format_ref.set_target(self.display_edit)
        form.addWidget(self.format_ref)

        form.addWidget(QLabel("Lore"))
        self.lore_editor = LoreEditor()
        self.lore_editor.lineCreated.connect(self._track_lore_line)
        self.lore_editor.lineRemoved.connect(
            lambda edit: self.format_ref.forget(edit, fallback=self.display_edit))
        # line numbers change on add / remove / reorder: keep "Inserting into: Lore line N" right
        self.lore_editor.changed.connect(self.format_ref.refresh_status)
        form.addWidget(self.lore_editor)

        form.addWidget(QLabel("Base item"))
        self.item_base_edit = QLineEdit()
        form.addWidget(self.item_base_edit)

        props = QGroupBox("Item properties")
        props_grid = QGridLayout(props)
        props_grid.setColumnStretch(1, 1)
        props_grid.addWidget(QLabel("Stack size"), 0, 0)
        self.stack_spin = NoWheelSpinBox()
        self.stack_spin.setRange(0, max_stack_limit(TEXT_SNBT))
        self.stack_spin.setToolTip("max_stack_size component. 'Default' leaves the base item's own "
                                   "stack size. Damageable items (tools, armor, ...) must stay at 1.")
        props_grid.addWidget(self.stack_spin, 0, 1)
        props_grid.addWidget(QLabel("Rarity"), 0, 2)
        self.rarity_combo = NoWheelComboBox()
        self.rarity_combo.addItem("Default", "")
        for rarity in RARITIES:
            self.rarity_combo.addItem(rarity.capitalize(), rarity)
        self.rarity_combo.setToolTip("rarity component: the color of the item name in tooltips.")
        props_grid.addWidget(self.rarity_combo, 0, 3)
        self.glint_chk = QCheckBox("Enchantment glint effect")
        self.glint_chk.setToolTip("enchantment_glint_override: true")
        self.unbreakable_chk = QCheckBox("Unbreakable")
        self.unbreakable_chk.setToolTip("unbreakable component (only does something on damageable items).")
        self.hide_tooltip_chk = QCheckBox("Hide tooltip")
        self.hide_tooltip_chk.setToolTip("1.21.5+: tooltip_display={hide_tooltip:true}; "
                                         "1.21.4: hide_tooltip={}")
        props_grid.addWidget(self.glint_chk, 1, 0, 1, 2)
        props_grid.addWidget(self.unbreakable_chk, 1, 2, 1, 2)
        props_grid.addWidget(self.hide_tooltip_chk, 2, 0, 1, 2)
        self.fire_chk = QCheckBox("Fire resistant")
        self.fire_chk.setToolTip("damage_resistant={types:\"#minecraft:is_fire\"}: the item survives "
                                 "fire and lava (replaces the old fire_resistant component).")
        props_grid.addWidget(self.fire_chk, 2, 2, 1, 2)
        props_grid.addWidget(QLabel("Max durability"), 3, 0)
        self.damage_spin = NoWheelSpinBox()
        self.damage_spin.setRange(0, 2_147_483_647)
        self.damage_spin.setSpecialValueText("Default")
        self.damage_spin.setToolTip("max_damage component. Makes the item damageable, so its stack "
                                    "size must be 1 unless the base item already is damageable.")
        props_grid.addWidget(self.damage_spin, 3, 1)
        props_grid.addWidget(QLabel("Custom data"), 4, 0)
        self.custom_data_edit = QLineEdit()
        self.custom_data_edit.setPlaceholderText('SNBT compound, e.g. {tier:3,owner:"ruby"}  (for your own functions)')
        self.custom_data_edit.setToolTip("custom_data component, written exactly as typed. Check it "
                                         "with /data get entity @s SelectedItem.components.")
        props_grid.addWidget(self.custom_data_edit, 4, 1, 1, 3)
        form.addWidget(props)

        ench_box = QGroupBox("Enchantments")
        ench_lay = QVBoxLayout(ench_box)
        self.ench_editor = EnchantmentEditor()
        ench_lay.addWidget(self.ench_editor)
        form.addWidget(ench_box)

        attr_box = QGroupBox("Attribute modifiers")
        attr_lay = QVBoxLayout(attr_box)
        self.attr_editor = AttributeEditor()
        attr_lay.addWidget(self.attr_editor)
        attr_hint = QLabel("Each modifier gets a unique id automatically. Amounts: 'Add' is a plain "
                           "number (7 = +7); the multiply operations use fractions (0.1 = +10%).")
        attr_hint.setObjectName("hint")
        attr_hint.setWordWrap(True)
        attr_lay.addWidget(attr_hint)
        form.addWidget(attr_box)

        self.display_chk = QCheckBox("Generate Item Display Function")
        self.display_chk.setToolTip("Also write function/display/<item>.mcfunction, which summons this item "
                                    "as an item_display (scale 1.0, fixed).")
        form.addWidget(self.display_chk)
        self.display_opts = DisplayOptionsWidget()
        self.display_opts.setEnabled(False)
        form.addWidget(self.display_opts)

        form.addWidget(QLabel("Generated commands"))
        self.item_notes = QLabel()
        self.item_notes.setTextFormat(Qt.RichText)
        self.item_notes.setWordWrap(True)
        self.item_notes.setVisible(False)
        form.addWidget(self.item_notes)
        self.cmd_preview = QPlainTextEdit()
        self.cmd_preview.setReadOnly(True)
        self.cmd_preview.setMinimumHeight(110)
        self.cmd_preview.setMaximumHeight(170)
        form.addWidget(self.cmd_preview)

        recipe_row = QHBoxLayout()
        self.recipe_lbl = QLabel("No recipe")
        self.recipe_lbl.setObjectName("hint")
        self.recipe_btn = QPushButton("Edit Recipe...")
        recipe_row.addWidget(self.recipe_lbl, 1)
        recipe_row.addWidget(self.recipe_btn)
        form.addLayout(recipe_row)

        self.save_item_btn = QPushButton("Save && Regenerate Files")
        self.save_item_btn.setObjectName("primary")
        form.addWidget(self.save_item_btn)
        form.addStretch(1)
        right.addWidget(self.item_form, 1)
        outer.addLayout(right, 3)

        self.item_form.setEnabled(False)
        refresh.clicked.connect(self._refresh_items_list)
        self.regen_all_btn.clicked.connect(self._regenerate_all)
        self.items_list.itemSelectionChanged.connect(self._on_item_selected)
        self.display_edit.textChanged.connect(self._update_item_preview)
        self.item_base_edit.textChanged.connect(self._update_item_preview)
        self.lore_editor.changed.connect(self._update_item_preview)
        self.lore_editor.changed.connect(self._schedule_tab_height)
        self.stack_spin.valueChanged.connect(self._update_item_preview)
        self.rarity_combo.currentIndexChanged.connect(self._update_item_preview)
        for chk in (self.glint_chk, self.unbreakable_chk, self.hide_tooltip_chk, self.fire_chk):
            chk.toggled.connect(self._update_item_preview)
        self.damage_spin.valueChanged.connect(self._update_item_preview)
        self.custom_data_edit.textChanged.connect(self._update_item_preview)
        for editor in (self.ench_editor, self.attr_editor):
            editor.changed.connect(self._update_item_preview)
            editor.changed.connect(self._schedule_tab_height)
        self.display_chk.toggled.connect(self.display_opts.setEnabled)
        self.display_chk.toggled.connect(self._update_item_preview)
        self.display_opts.changed.connect(self._update_item_preview)
        self.recipe_btn.clicked.connect(self._edit_recipe)
        self.save_item_btn.clicked.connect(self._save_item)
        return box

    def _build_settings_group(self) -> QGroupBox:
        box = QGroupBox("Datapack settings")
        grid = QGridLayout(box)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)

        grid.addWidget(QLabel("Namespace"), 0, 0)
        self.ns_combo = NoWheelComboBox()
        self.ns_combo.setEditable(True)
        self.ns_combo.setInsertPolicy(QComboBox.NoInsert)
        self.ns_combo.setEditText(DEFAULT_NAMESPACE)
        self.ns_combo.setToolTip("Datapack function namespace. Used as /function <namespace>:give/<item>")
        self.ns_combo.editTextChanged.connect(lambda _t: self._refresh_dp(detect=False))
        grid.addWidget(self.ns_combo, 0, 1)

        grid.addWidget(QLabel("Base item"), 0, 2)
        self.base_edit = QLineEdit("minecraft:stick")
        grid.addWidget(self.base_edit, 0, 3)

        self.give_chk = QCheckBox("Generate give functions automatically")
        self.give_chk.setChecked(True)
        self.missing_chk = QCheckBox("Generate JSON even if texture is missing")
        self.overwrite_chk = QCheckBox("Overwrite existing files (asks for confirmation)")
        grid.addWidget(self.give_chk, 1, 0, 1, 2)
        grid.addWidget(self.missing_chk, 1, 2, 1, 2)
        grid.addWidget(self.overwrite_chk, 2, 0, 1, 2)
        self.display_new_chk = QCheckBox("Generate Item Display Function")
        self.display_new_chk.setToolTip("Applies to items created in tabs A and B (textures and existing "
                                        "models). Off by default. Per-item setting: tab C.")
        grid.addWidget(self.display_new_chk, 3, 0, 1, 2)
        self.display_opts_new = DisplayOptionsWidget(compact=True, show_hint=False)
        self.display_opts_new.setEnabled(False)
        self.display_new_chk.toggled.connect(self.display_opts_new.setEnabled)
        grid.addWidget(self.display_opts_new, 4, 0, 1, 4)
        grid.addWidget(QLabel("Target version"), 2, 2)
        self.target_combo = NoWheelComboBox()
        self.target_combo.addItem("1.21.5 and newer (SNBT text, incl. 26.x)", TEXT_SNBT)
        self.target_combo.addItem("1.21.4 (JSON-string text)", TEXT_JSON)
        self.target_combo.setToolTip("Decides how custom names are written in /give commands.\n"
                                     "Recipes and item_model IDs are identical in both.")
        self.target_combo.currentIndexChanged.connect(self._on_target_changed)
        grid.addWidget(self.target_combo, 2, 3)
        return box

    def _build_log_group(self) -> QGroupBox:
        box = QGroupBox("Log")
        lay = QVBoxLayout(box)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        self.log_view.setMinimumHeight(70)
        lay.addWidget(self.log_view, 1)
        row = QHBoxLayout()
        self.summary_lbl = QLabel("")
        self.summary_lbl.setObjectName("hint")
        clear = QPushButton("Clear Log")
        clear.clicked.connect(self.log_view.clear)
        row.addWidget(self.summary_lbl, 1)
        row.addWidget(clear)
        lay.addLayout(row)
        return box

    def _build_footer(self) -> QWidget:
        """Always-visible bar: the primary action of the current tab."""
        bar = QWidget()
        bar.setObjectName("footer")
        row = QHBoxLayout(bar)
        row.setContentsMargins(10, 6, 10, 6)
        self.summary_footer = QLabel("")
        self.summary_footer.setObjectName("hint")
        row.addWidget(self.summary_footer, 1)
        self.action_btn = QPushButton("")
        self.action_btn.setObjectName("primary")
        self.action_btn.clicked.connect(self._run_footer_action)
        row.addWidget(self.action_btn)
        return bar

    def _update_footer(self, *_args) -> None:
        if not hasattr(self, "action_btn"):
            return
        index = self.tabs.currentIndex()
        self.tabs.setMinimumHeight(self._editor_tab_height() if index == 2 else self.TAB_MIN_HEIGHT)
        if index == 0:
            self.action_btn.setText("Generate Items")
            self.action_btn.setEnabled(True)
        elif index == 1:
            self.action_btn.setText("Generate Item Definitions")
            self.action_btn.setEnabled(True)
        else:
            self.action_btn.setText("Save && Regenerate Files")
            self.action_btn.setEnabled(self.item_form.isEnabled())

    def _editor_tab_height(self) -> int:
        """Tab C grows with its content (lore lines, notes); the page scrolls, nothing is squeezed."""
        box = self.items_box
        lay = box.layout()
        needed = box.minimumSizeHint().height()
        if lay is not None and lay.hasHeightForWidth() and box.width() > 0:
            # wrapped labels (hints, tooltip caption) need more height when the column is narrow
            margins = lay.contentsMargins()
            needed = max(needed, lay.minimumHeightForWidth(box.width()) + margins.top() + margins.bottom())
        return max(self.TAB_MIN_HEIGHT_EDITOR, needed + self.tabs.tabBar().sizeHint().height() + 12)

    def _schedule_tab_height(self) -> None:
        QTimer.singleShot(0, self._update_footer)

    def _run_footer_action(self) -> None:
        index = self.tabs.currentIndex()
        if index == 0:
            self._on_generate()
        elif index == 1:
            self._on_generate_defs()
        elif self.item_form.isEnabled():
            self._save_item()

    def _toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showMaximized() if self._was_maximized else self.showNormal()
        else:
            self._was_maximized = self.isMaximized()
            self.showFullScreen()

    # -------------------------------------------------------------- helpers
    @staticmethod
    def _set_dot(label: QLabel, state: str, tip: str = "") -> None:
        label.setStyleSheet(f"color: {COLORS[state]}; background: transparent;")
        label.setToolTip(tip)

    def _log(self, level: Level, message: str) -> None:
        color = LEVEL_COLORS[level]
        self.log_view.appendHtml(
            f'<span style="color:{color}">[{level.value}] {escape(message)}</span>'
        )

    def _log_plain(self, text: str) -> None:
        self.log_view.appendHtml(f'<span style="color:#dcdde0">{escape(text)}</span>')

    def _error(self, message: str) -> None:
        self._log(Level.ERROR, message)
        QMessageBox.warning(self, "Cannot continue", message)

    def _show_result(self, result: BatchResult) -> None:
        for entry in result.entries:
            self._log(entry.level, entry.message)
        text = result.summary.text()
        self._log_plain("--- " + text)
        self.summary_lbl.setText(text)
        self.summary_footer.setText(text)

    def _confirm_overwrite(self) -> bool:
        """Return True if overwriting is enabled AND confirmed."""
        if not self.overwrite_chk.isChecked():
            return False
        answer = QMessageBox.question(
            self, "Overwrite existing files?",
            "Existing files with the same names will be REPLACED.\n\n"
            "Choose 'No' to run without overwriting (existing files are skipped).",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            self._log(Level.INFO, "Overwrite not confirmed - existing files will be skipped.")
            return False
        return True

    # ----------------------------------------------------------- path logic
    def _browse_rp(self) -> None:
        start = self.rp_edit.text() or str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "Select Resource Pack Folder", start)
        if folder:
            self.rp_edit.setText(folder)
            self._refresh_rp()

    def _browse_dp(self) -> None:
        start = self.dp_edit.text() or str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "Select Datapack Folder", start)
        if folder:
            self.dp_edit.setText(folder)
            self._refresh_dp()

    def _new_template(self) -> None:
        """Export an empty resource pack + datapack, optionally load them into this tool."""
        start = self.settings.value("template_dir", "", str) or str(Path.home())
        dialog = PackTemplateDialog(start, self.ns_combo.currentText().strip() or DEFAULT_NAMESPACE, self)
        if dialog.exec() != QDialog.Accepted or dialog.created is None:
            return
        self._apply_template(dialog.created, dialog.options().namespace, dialog.load_into_tool)
        self.settings.setValue("template_dir", str(dialog.options().parent))

    def _apply_template(self, result, namespace: str, load: bool) -> None:
        """Log what was created and (if wanted) point the path fields at the new packs."""
        for label, root in (("Resource pack", result.resource_root), ("Datapack", result.data_root)):
            if root is not None:
                self._log(Level.INFO, f"{label} template created: {root}")
        if not load:
            return
        if result.resource_root is not None:
            self.rp_edit.setText(str(result.resource_root))
            self._refresh_rp()
        if result.data_root is not None:
            self.ns_combo.setEditText(namespace)
            self.dp_edit.setText(str(result.data_root))
            self._refresh_dp()

    def _refresh_rp(self) -> None:
        text = self.rp_edit.text().strip()
        if not text:
            self.rp = None
            self._set_dot(self.rp_dot, "none")
            self.rp_msg.setText("No folder selected")
            for i in range(3):
                self._set_dir_row(i, "none", "-")
            return
        self.rp = ResourcePackPaths(Path(text))
        state, msg = self.rp.status()
        self._set_dot(self.rp_dot, state, msg)
        self.rp_msg.setText(msg)
        for i, (_label, path, exists) in enumerate(self.rp.dir_checks()):
            self._set_dir_row(i, "ok" if exists else "invalid",
                              f"{path}  ({'exists' if exists else 'missing'})")

    def _set_dir_row(self, index: int, state: str, text: str) -> None:
        _name, dot, path = self.dir_rows[index]
        self._set_dot(dot, state)
        path.setText(text)

    def _refresh_dp(self, detect: bool = True) -> None:
        text = self.dp_edit.text().strip()
        if not text:
            self.dp = None
            self._set_dot(self.dp_dot, "none")
            self.dp_msg.setText("No folder selected")
            self._set_dir_row(3, "none", "-")
            self._set_dir_row(4, "none", "-")
            self.store = None
            self._refresh_items_list()
            return
        self.dp = DatapackPaths(Path(text))
        self._load_store()
        if detect:
            self._detect_namespaces()
        ns = self.ns_combo.currentText().strip()
        state, msg = self.dp.status(ns)
        self._set_dot(self.dp_dot, state, msg)
        self.dp_msg.setText(msg)
        if validate_namespace(ns) is None:
            give = self.dp.give_dir(ns)
            exists = give.is_dir()
            self._set_dir_row(3, "ok" if exists else "partial",
                              f"{give}  ({'exists' if exists else 'will be created'})")
            disp = self.dp.display_dir(ns)
            disp_exists = disp.is_dir()
            self._set_dir_row(4, "ok" if disp_exists else "partial",
                              f"{disp}  ({'exists' if disp_exists else 'created when enabled'})")
        else:
            self._set_dir_row(3, "invalid", "Invalid namespace")
            self._set_dir_row(4, "invalid", "Invalid namespace")
        self._refresh_items_list()

    def _detect_namespaces(self) -> None:
        if self.dp is None:
            return
        found = self.dp.detect_namespaces()
        current = self.ns_combo.currentText().strip()
        self.ns_combo.blockSignals(True)
        self.ns_combo.clear()
        self.ns_combo.addItems(found)
        # Keep what the user has unless it's the untouched default and a real namespace exists.
        if current and (current in found or current != DEFAULT_NAMESPACE or not found):
            self.ns_combo.setEditText(current)
        else:
            self.ns_combo.setEditText(found[0])
        self.ns_combo.blockSignals(False)

    def _function_settings(self) -> tuple[str, str, bool, bool, str, tuple[float, float, float]] | None:
        """Validate namespace/base item/datapack for modes A and B (one shared path).

        Returns (namespace, base_item, generate_give, generate_display, display_mode,
        display_scale) or None after showing an error.
        """
        namespace = self.ns_combo.currentText().strip()
        base_item = self.base_edit.text().strip()
        give = self.give_chk.isChecked()
        display = self.display_new_chk.isChecked()
        mode = self.display_opts_new.mode()
        scale = self.display_opts_new.scale() or DEFAULT_SCALE
        if display and self.display_opts_new.error():
            self._error(f"Display function: {self.display_opts_new.error()}")
            return None
        if give or display:
            err = validate_namespace(namespace)
            if err:
                self._error(f"Namespace: {err}")
                return None
            norm, err = normalize_base_item(base_item)
            if err or norm is None:
                self._error(f"Base item: {err}")
                return None
            base_item = norm
            if self.dp is None or self.dp.status(namespace)[0] == "invalid":
                self._error("Select a valid Datapack folder (or disable give and display functions).")
                return None
        return namespace, base_item, give, display, mode, scale

    # ------------------------------------------------------------ Mode A
    def _on_generate(self) -> None:
        self._refresh_rp()
        self._refresh_dp(detect=False)

        if self.rp is None or self.rp.status()[0] == "invalid":
            self._error("Select a valid Resource Pack folder first.")
            return

        names, bad = parse_names(self.names_edit.toPlainText())
        for raw, err in bad:
            self._log(Level.ERROR, f"Invalid name '{raw}': {err}")
        if not names:
            self._error("No valid item names to process.")
            return

        prepared = self._function_settings()
        if prepared is None:
            return
        namespace, base_item, give, display, mode, scale = prepared

        allow_missing = self.missing_chk.isChecked()
        missing = gen.find_missing_textures(self.rp, names)
        if missing and not allow_missing:
            shown = ", ".join(f"{m}.png" for m in missing[:10])
            if len(missing) > 10:
                shown += f", ... (+{len(missing) - 10} more)"
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Warning)
            box.setWindowTitle("Missing textures")
            box.setText(f"{len(missing)} texture(s) not found in textures/item/:\n{shown}")
            box.setInformativeText("Generate the JSON files for these items anyway, or skip them?")
            anyway = box.addButton("Generate anyway", QMessageBox.AcceptRole)
            skip = box.addButton("Skip those items", QMessageBox.DestructiveRole)
            cancel = box.addButton("Cancel", QMessageBox.RejectRole)
            box.setDefaultButton(skip)
            box.exec()
            clicked = box.clickedButton()
            if clicked is cancel or clicked is None:
                self._log(Level.INFO, "Generation cancelled.")
                return
            allow_missing = clicked is anyway

        overwrite = self._confirm_overwrite()
        options = gen.GenerationOptions(
            namespace=namespace, base_item=base_item, generate_give=give, generate_display=display,
            display_mode=mode, display_scale=scale, allow_missing_textures=allow_missing, overwrite=overwrite,
            text_format=self._text_format(), records=self._current_records(),
        )
        result = gen.generate_items(self.rp, self.dp, names, options)
        self._show_result(result)
        self._register_items(result.completed, display, mode, scale)
        self._refresh_rp()
        self._refresh_dp(detect=False)

    # ------------------------------------------------------------ Mode B
    def _on_scan(self) -> None:
        self._refresh_rp()
        if self.rp is None or self.rp.status()[0] == "invalid":
            self._error("Select a valid Resource Pack folder first.")
            return
        models, ignored = gen.list_existing_models(self.rp)
        self.models_list.clear()
        for name in models:
            has_def = self.rp.item_definition_path(name).is_file()
            item = QListWidgetItem(f"{name}   (item definition exists)" if has_def else name)
            item.setData(Qt.UserRole, name)
            self.models_list.addItem(item)
        for fname in ignored:
            self._log(Level.WARNING, f"Ignored model file with invalid name: {fname}")
        self._log(Level.INFO, f"Found {len(models)} model(s) in models/item/")

    def _on_generate_defs(self) -> None:
        if self.rp is None or self.rp.status()[0] == "invalid":
            self._error("Select a valid Resource Pack folder first.")
            return
        selected = [i.data(Qt.UserRole) for i in self.models_list.selectedItems()]
        if not selected:
            self._error("Select at least one model in the list (use 'Scan Existing Models').")
            return
        prepared = self._function_settings()
        if prepared is None:
            return
        namespace, base_item, give, display, mode, scale = prepared
        overwrite = self._confirm_overwrite()
        options = gen.GenerationOptions(
            namespace=namespace, base_item=base_item, generate_give=give, generate_display=display,
            display_mode=mode, display_scale=scale, overwrite=overwrite, text_format=self._text_format(), records=self._current_records(),
        )
        result = gen.generate_item_definitions(self.rp, selected, overwrite, self.dp, options)
        self._show_result(result)
        self._register_items(result.completed, display, mode, scale)
        self._refresh_dp(detect=False)
        self._on_scan_quiet()

    def _on_scan_quiet(self) -> None:
        """Refresh the list (to update the 'definition exists' marks) keeping the selection."""
        if self.rp is None:
            return
        selected = {i.data(Qt.UserRole) for i in self.models_list.selectedItems()}
        models, _ = gen.list_existing_models(self.rp)
        self.models_list.clear()
        for name in models:
            has_def = self.rp.item_definition_path(name).is_file()
            item = QListWidgetItem(f"{name}   (item definition exists)" if has_def else name)
            item.setData(Qt.UserRole, name)
            self.models_list.addItem(item)
            if name in selected:
                item.setSelected(True)

    def _track_lore_line(self, edit: QLineEdit) -> None:
        self.format_ref.track(
            edit, lambda e=edit: f"Lore line {self.lore_editor.index_of(e) + 1}")

    # ------------------------------------------- project store / item records
    def _text_format(self) -> str:
        return self.target_combo.currentData() or TEXT_SNBT

    def _namespace(self) -> str | None:
        ns = self.ns_combo.currentText().strip()
        return ns if validate_namespace(ns) is None else None

    def _default_base(self) -> str:
        norm, _err = normalize_base_item(self.base_edit.text())
        return norm or DEFAULT_BASE_ITEM

    def _load_store(self) -> None:
        if self.dp is None:
            self.store = None
            return
        path = self.dp.root / STORE_FILENAME
        if self.store is not None and self.store.path == path:
            return
        self.store = ProjectStore.load(path)
        for message in self.store.warnings:
            self._log(Level.WARNING, f"{STORE_FILENAME}: {message}")
        if self.store.read_error:
            self._log(Level.ERROR, self.store.read_error)
        elif self.store.loaded_from_file:
            idx = self.target_combo.findData(self.store.text_format)
            if idx >= 0:
                self.target_combo.blockSignals(True)
                self.target_combo.setCurrentIndex(idx)
                self.target_combo.blockSignals(False)

    def _persist_store(self) -> bool:
        if self.store is None:
            return True
        self.store.text_format = self._text_format()
        try:
            self.store.save()
            return True
        except StoreError as exc:
            self._log(Level.ERROR, str(exc))
            return False

    def _current_records(self) -> dict[str, ItemRecord]:
        ns = self._namespace()
        if self.dp is None or ns is None:
            return {}
        stored = self.store.items(ns) if self.store else {}
        return gen.collect_records(self.dp, ns, stored, self._default_base())

    def _register_items(self, names: list[str], display: bool = False,
                        mode: str = DEFAULT_DISPLAY_MODE,
                        scale: tuple[float, float, float] = DEFAULT_SCALE) -> None:
        """Remember generated items (and their display option) for the item editor."""
        ns = self._namespace()
        if self.store is None or ns is None or not names:
            return
        known = self._current_records()
        items = self.store.items(ns)
        changed = False
        for name in names:
            rec = items.get(name)
            if rec is None:
                rec = known.get(name) or ItemRecord(name, base_item=self._default_base())
                items[name] = rec
                changed = True
            if display and not rec.generate_display:
                rec.generate_display = True
                rec.display_mode, rec.display_scale = mode, scale
                changed = True
        if not changed:
            return
        self._persist_store()
        self._refresh_items_list()

    def _on_target_changed(self) -> None:
        fmt = self._text_format()
        self.format_ref.set_text_format(fmt)
        self._set_stack_limit(fmt)
        if self.store is not None and self.store.loaded_from_file and not self.store.read_error:
            self._persist_store()
        if self._current_item:
            self._update_item_preview()
        if self.dp is not None and self._current_records():
            self._log(Level.INFO, "Target version changed. Use 'Regenerate All Functions' "
                                  "(tab C) to update existing give functions.")

    # ------------------------------------------------------------ item editor
    def _refresh_items_list(self) -> None:
        records = self._current_records()
        previous = self._current_item
        self.items_list.blockSignals(True)
        self.items_list.clear()
        for name, rec in records.items():
            tags = [t for t, on in (("named", bool(rec.display_name)), ("lore", bool(rec.lore)),
                                    ("recipe", rec.recipe is not None),
                                    ("display", rec.generate_display)) if on]
            item = QListWidgetItem(name + (f"   [{', '.join(tags)}]" if tags else ""))
            item.setData(Qt.UserRole, name)
            self.items_list.addItem(item)
            if name == previous:
                self.items_list.setCurrentItem(item)
        self.items_list.blockSignals(False)
        if previous not in records:
            self._clear_editor()

    def _clear_editor(self) -> None:
        self._current_item = None
        self._item_recipe = None
        self.item_title.setText("Select an item from the list")
        self.item_form.setEnabled(False)
        self._update_footer()
        self.display_chk.blockSignals(True)
        self.display_chk.setChecked(False)
        self.display_chk.blockSignals(False)
        self.display_opts.setEnabled(False)
        self.display_opts.set_values(DEFAULT_DISPLAY_MODE, DEFAULT_SCALE)
        for edit in (self.display_edit, self.item_base_edit):
            edit.blockSignals(True)
            edit.clear()
            edit.blockSignals(False)
        self._load_properties(ItemRecord(""))
        self._update_item_preview()

    def _on_item_selected(self) -> None:
        selected = self.items_list.selectedItems()
        if not selected:
            return
        name = selected[0].data(Qt.UserRole)
        rec = self._current_records().get(name)
        if rec is None:
            return
        self._current_item = name
        self._item_recipe = Recipe.from_dict(rec.recipe.to_dict()) if rec.recipe else None
        self.item_title.setText(name)
        self.display_edit.setText(rec.display_name)
        self.item_base_edit.setText(rec.base_item)
        self._load_properties(rec)
        self.display_chk.blockSignals(True)
        self.display_chk.setChecked(rec.generate_display)
        self.display_chk.blockSignals(False)
        self.display_opts.setEnabled(rec.generate_display)
        self.display_opts.set_values(rec.display_mode, rec.display_scale)
        self.item_form.setEnabled(True)
        self._update_footer()
        self._update_item_preview()

    def _set_stack_limit(self, text_format: str) -> None:
        self.stack_spin.setMaximum(max_stack_limit(text_format))

    def _refresh_stack_default(self) -> None:
        """The 'Default' entry shows the base item's own stack size."""
        base, _err = normalize_base_item(self.item_base_edit.text())
        facts = item_facts(base) if base else None
        self.stack_spin.setSpecialValueText(
            f"Default ({facts.default_stack})" if facts is not None and facts.known else "Default")

    def _load_properties(self, rec: ItemRecord) -> None:
        """Show a record's lore/properties without triggering previews one by one."""
        widgets = (self.stack_spin, self.rarity_combo, self.glint_chk, self.unbreakable_chk,
                   self.hide_tooltip_chk, self.fire_chk, self.damage_spin, self.custom_data_edit,
                   self.ench_editor, self.attr_editor)
        for w in widgets:
            w.blockSignals(True)
        try:
            self.stack_spin.setValue(rec.max_stack_size or 0)
            idx = self.rarity_combo.findData(rec.rarity)
            self.rarity_combo.setCurrentIndex(idx if idx >= 0 else 0)
            self.glint_chk.setChecked(rec.glint)
            self.unbreakable_chk.setChecked(rec.unbreakable)
            self.hide_tooltip_chk.setChecked(rec.hide_tooltip)
            self.fire_chk.setChecked(rec.fire_resistant)
            self.damage_spin.setValue(rec.max_damage or 0)
            self.custom_data_edit.setText(rec.custom_data)
            self.ench_editor.set_enchantments(list(rec.enchantments))
            self.attr_editor.set_modifiers(list(rec.attributes))
        finally:
            for w in widgets:
                w.blockSignals(False)
        self.lore_editor.set_lines(rec.lore, notify=False)   # tracking signals must still fire
        self._refresh_stack_default()
        self.format_ref.refresh_status()

    def _working_record(self) -> tuple[ItemRecord | None, str | None]:
        """The item as currently shown in the editor (may be unsaved) and a base-item error."""
        name = self._current_item
        if not name:
            return None, None
        base_text = self.item_base_edit.text().strip()
        base, err = normalize_base_item(base_text)
        if err:
            err = f"Base item: {err}"
        display_on = self.display_chk.isChecked()
        scale = self.display_opts.scale()
        if display_on and scale is None and not err:
            err = f"Display function: {self.display_opts.error()}"
        existing = self._current_records().get(name)
        record = ItemRecord(
            name=name, base_item=base or base_text,
            display_name=self.display_edit.text().strip(),
            recipe=self._item_recipe,
            generate_display=display_on,
            display_mode=self.display_opts.mode(),
            display_scale=scale or DEFAULT_SCALE,
            extra_components=dict(existing.extra_components) if existing else {},
            lore=self.lore_editor.lines(),
            max_stack_size=self.stack_spin.value() or None,
            glint=self.glint_chk.isChecked(),
            rarity=self.rarity_combo.currentData() or "",
            unbreakable=self.unbreakable_chk.isChecked(),
            hide_tooltip=self.hide_tooltip_chk.isChecked(),
            enchantments=self.ench_editor.enchantments(),
            attributes=self.attr_editor.modifiers(),
            max_damage=self.damage_spin.value() or None,
            fire_resistant=self.fire_chk.isChecked(),
            custom_data=self.custom_data_edit.text().strip(),
        )
        if not err:
            plan = self._plan(record)
            if plan.errors:
                err = "Item: " + " ".join(plan.errors)
        return record, err

    def _plan(self, record: ItemRecord):
        return gen.analyze_item(record.name, record.base_item, record.display_name,
                                self._text_format(), record.extra_components, record.properties())

    def _update_item_preview(self) -> None:
        record, err = self._working_record()
        if record is None:
            self.tooltip.set_lines([[Segment("Select an item", color="dark_gray")]])
            self.cmd_preview.setPlainText("")
            self.recipe_lbl.setText("No recipe")
            self.item_notes.setVisible(False)
            return
        self._refresh_stack_default()
        self._show_item_notes(record, err)
        props = record.properties()
        self.tooltip.set_lines(build_tooltip(record.base_item, record.display_name, props),
                               item_traits(record.base_item, props))
        if err:
            self.cmd_preview.setPlainText(f"// {err}")
        else:
            try:
                props = record.properties()
                text = gen.build_give_command(
                    record.name, record.base_item, record.display_name,
                    self._text_format(), record.extra_components, props)
                ns = self._namespace()
                if ns:
                    text = f"// /function {function_id(ns, 'give', record.name)}\n" + text
                if record.generate_display:
                    shown = "\n\n"
                    if ns:
                        shown += f"// /function {function_id(ns, 'display', record.name)}\n"
                    text += shown + gen.build_display_command(
                        record.name, record.base_item, record.display_name,
                        self._text_format(), record.extra_components,
                        record.display_mode, record.display_scale, props)
                self.cmd_preview.setPlainText(text)
            except ValueError as exc:
                self.cmd_preview.setPlainText(f"// {exc}")
        recipe = self._item_recipe
        if recipe is None:
            text = "No recipe"
        else:
            text = f"{recipe.kind.capitalize()} recipe '{recipe.recipe_id}' -> {recipe.output} x{recipe.count}"
        stored = self._current_records().get(record.name)
        stored_recipe = stored.recipe.to_dict() if stored and stored.recipe else None
        if (recipe.to_dict() if recipe else None) != stored_recipe:
            text += "  (unsaved)"
        self.recipe_lbl.setText(text)

    def _show_item_notes(self, record: ItemRecord, err: str | None) -> None:
        """Errors (block saving), warnings (reported, e.g. unsupported components) and extras."""
        lines: list[str] = []
        base_ok = normalize_base_item(record.base_item)[1] is None
        if base_ok:
            plan = self._plan(record)
            lines += [f'<span style="color:#ff6b6b">{escape(m)}</span>' for m in plan.errors]
            lines += [f'<span style="color:#e0a030">{escape(m)}</span>' for m in plan.warnings]
            if record.extra_components:
                keys = ", ".join(record.extra_components)
                lines.append(f'<span style="color:#8d9299">Extra components kept from the project '
                             f'file: {escape(keys)}</span>')
        self.item_notes.setText("<br>".join(lines))
        self.item_notes.setVisible(bool(lines))

    def _edit_recipe(self) -> None:
        ns = self._namespace()
        if self.dp is None or ns is None:
            self._error("Select a valid Datapack folder and namespace first.")
            return
        record, err = self._working_record()
        if record is None:
            return
        if err:
            self._error(err)
            return
        records = self._current_records()
        records[record.name] = record          # so the preview uses unsaved edits
        dialog = RecipeDialog(record.name, records, ns, self._item_recipe, self)
        if dialog.exec() and dialog.recipe is not None:
            self._item_recipe = dialog.recipe
            self._save_item()

    def _save_item(self) -> None:
        ns = self._namespace()
        if self.dp is None or ns is None or self.dp.status(ns)[0] == "invalid":
            self._error("Select a valid Datapack folder and namespace first.")
            return
        record, err = self._working_record()
        if record is None:
            return
        if err:
            self._error(err)
            return
        records = self._current_records()
        records[record.name] = record
        if self._apply_records(records, [record.name], ns):
            self._refresh_items_list()
            self._update_item_preview()

    def _regenerate_all(self) -> None:
        ns = self._namespace()
        if self.dp is None or ns is None or self.dp.status(ns)[0] == "invalid":
            self._error("Select a valid Datapack folder and namespace first.")
            return
        records = self._current_records()
        if not records:
            self._log(Level.INFO, "No items to regenerate.")
            return
        if self._apply_records(records, list(records), ns):
            self._refresh_items_list()

    def _apply_records(self, records: dict[str, ItemRecord], names: list[str], ns: str) -> bool:
        """Plan, confirm replacing changed files, write, then persist item data."""
        assert self.dp is not None
        fmt = self._text_format()
        stored = self.store.items(ns) if self.store else {}
        was_display = {n for n in names if n in stored and stored[n].generate_display}
        files, errors = gen.plan_item_files(self.dp, ns, records, names, fmt, was_display)
        if errors:
            for message in errors:
                self._log(Level.ERROR, message)
            QMessageBox.warning(self, "Cannot generate", "\n".join(errors[:8]))
            return False
        replacing = [pf for pf in files if pf.exists and pf.changed]
        if replacing:
            def _line(pf: gen.PlannedFile) -> str:
                rel = pf.path.relative_to(self.dp.root).as_posix()
                return f"{rel}  (will be removed)" if pf.delete else rel
            shown = "\n".join(_line(pf) for pf in replacing[:10])
            if len(replacing) > 10:
                shown += f"\n... (+{len(replacing) - 10} more)"
            answer = QMessageBox.question(
                self, "Replace existing files?",
                f"{len(replacing)} existing file(s) will be regenerated or removed:\n\n{shown}",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes,
            )
            if answer != QMessageBox.Yes:
                self._log(Level.INFO, "Cancelled - nothing was changed.")
                return False
        result = gen.regenerate_items(self.dp, ns, records, names, fmt, overwrite=True,
                                      display_was_enabled=was_display)
        self._show_result(result)
        if result.summary.errors:
            return False
        if self.store is not None:
            for name in names:
                self.store.put(ns, records[name])
        return self._persist_store()

    # ------------------------------------------------------------ settings
    def _load_settings(self) -> None:
        self.rp_edit.setText(self.settings.value("resource_pack", "", str))
        self.dp_edit.setText(self.settings.value("datapack", "", str))
        self.ns_combo.setEditText(self.settings.value("namespace", DEFAULT_NAMESPACE, str))
        self.base_edit.setText(self.settings.value("base_item", "minecraft:stick", str))
        self.give_chk.setChecked(self.settings.value("give", True, bool))
        self.missing_chk.setChecked(self.settings.value("allow_missing", False, bool))
        self.display_new_chk.setChecked(self.settings.value("display_new", False, bool))
        try:
            saved_scale = tuple(float(x) for x in str(self.settings.value("display_scale_new", "1,1,1")).split(","))
            if len(saved_scale) != 3:
                raise ValueError
        except ValueError:
            saved_scale = DEFAULT_SCALE
        self.display_opts_new.set_values(self.settings.value("display_mode_new", DEFAULT_DISPLAY_MODE, str),
                                         saved_scale)  # type: ignore[arg-type]
        geometry = self.settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        idx = self.target_combo.findData(self.settings.value("text_format", TEXT_SNBT, str))
        self.target_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._refresh_rp()
        self._refresh_dp()

    def _save_settings(self) -> None:
        self.settings.setValue("resource_pack", self.rp_edit.text().strip())
        self.settings.setValue("datapack", self.dp_edit.text().strip())
        self.settings.setValue("namespace", self.ns_combo.currentText().strip())
        self.settings.setValue("base_item", self.base_edit.text().strip())
        self.settings.setValue("give", self.give_chk.isChecked())
        self.settings.setValue("allow_missing", self.missing_chk.isChecked())
        self.settings.setValue("display_new", self.display_new_chk.isChecked())
        self.settings.setValue("display_mode_new", self.display_opts_new.mode())
        new_scale = self.display_opts_new.scale()
        if new_scale is not None:
            self.settings.setValue("display_scale_new", ",".join(f"{x:g}" for x in new_scale))
        if not self.isFullScreen():
            self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("text_format", self._text_format())

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        self._save_settings()
        super().closeEvent(event)
