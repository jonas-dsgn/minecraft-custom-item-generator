"""Small reusable widgets: a wheel-safe combo box and the item_display options editor."""
from __future__ import annotations

import random
from typing import Callable

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFontMetrics
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)
from shiboken6 import isValid

from core.attributes import (
    KNOWN_ATTRIBUTES, KNOWN_ENCHANTMENTS, MAX_ATTRIBUTES, MAX_ENCHANT_LEVEL, OPERATION_LABELS,
    OPERATIONS, SLOT_LABELS, SLOTS, AttributeModifier, normalize_id,
)
from core.components import MAX_LORE_LINES
from core.format_codes import (
    COLOR_REFERENCE, FORMAT_REFERENCE, HEX_PREFIX, LITERAL_AMPERSAND, CodeInfo,
    code_snippet, contrast_text_color, hex_code, plan_insert,
)
from core.text_components import (
    LORE_DEFAULT_COLOR, TEXT_SNBT, parse_legacy, segments_to_html,
)
from core.validation import DEFAULT_DISPLAY_MODE, DEFAULT_SCALE, DISPLAY_MODES, parse_scale_value

MODE_HINTS = {
    "fixed": "fixed - as placed in an item frame (default)",
    "ground": "ground - as a dropped item",
    "head": "head - as worn on a head",
    "gui": "gui - as in an inventory slot",
    "firstperson_righthand": "firstperson_righthand - first person, right hand",
    "firstperson_lefthand": "firstperson_lefthand - first person, left hand",
    "thirdperson_righthand": "thirdperson_righthand - third person, right hand",
    "thirdperson_lefthand": "thirdperson_lefthand - third person, left hand",
}
_BAD_EDIT = "QLineEdit { border: 1px solid #e05555; }"


class PageLayout(QVBoxLayout):
    """Vertical layout for the scrolled page that does not use height-for-width.

    With wrapped hint labels the scroll area would size the page from the *preferred* heights of
    every section, forcing a scrollbar even when the minimum heights fit. Without height-for-width
    the page only scrolls when its minimum height really exceeds the window.
    """

    def hasHeightForWidth(self) -> bool:  # noqa: N802 (Qt naming)
        return False


class NoWheelComboBox(QComboBox):
    """Ignores the mouse wheel until focused, so wheel-scrolling the page never changes it."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)

    def wheelEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()     # let the surrounding scroll area handle it


class NoWheelSpinBox(QSpinBox):
    """Ignores the mouse wheel until focused (same reason as NoWheelComboBox)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)

    def wheelEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class DisplayOptionsWidget(QWidget):
    """item_display mode + X/Y/Z scale, with an optional link for uniform scaling."""

    changed = Signal()

    def __init__(self, parent: QWidget | None = None, compact: bool = False,
                 show_hint: bool = True) -> None:
        super().__init__(parent)
        self._busy = False
        self.compact = compact       # one row: mode, X, Y, Z, link
        grid = QGridLayout() if not compact else QHBoxLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        self.setLayout(grid)

        self.mode_combo = NoWheelComboBox()
        for mode in DISPLAY_MODES:
            self.mode_combo.addItem(MODE_HINTS[mode], mode)
        self.mode_combo.setToolTip("item_display mode: how the item is positioned/oriented. "
                                   "It does NOT change the size - use Scale for that.")
        mode_label, scale_label = QLabel("Display mode"), QLabel("Scale")
        self.edits: list[QLineEdit] = []
        axis_labels: list[QLabel] = []
        for i, axis in enumerate("XYZ"):
            edit = QLineEdit(f"{DEFAULT_SCALE[i]:.1f}")
            edit.setMinimumWidth(60)
            edit.setToolTip(f"Scale {axis}. 1.0 keeps the model's original size.")
            edit.textChanged.connect(lambda _t, idx=i: self._on_edit(idx))
            self.edits.append(edit)
            axis_labels.append(QLabel(axis))
        self.link_chk = QCheckBox("Link axes")
        self.link_chk.setChecked(True)
        self.link_chk.setToolTip("Uniform scaling: one value controls X, Y and Z.")
        self.link_chk.toggled.connect(self._on_link)

        self.hint = QLabel("Mode = display context only. Scale = size (1.0 = original).")
        self.hint.setObjectName("hint")
        self.hint.setVisible(show_hint)
        self.setToolTip("Display mode = how the item is positioned/oriented (not its size).\n"
                        "Scale = the size; 1.0 keeps the model's original size.")

        if compact:
            grid.addWidget(mode_label)
            grid.addWidget(self.mode_combo, 3)
            grid.addWidget(scale_label)
            for lab, edit in zip(axis_labels, self.edits):
                grid.addWidget(lab)
                grid.addWidget(edit, 1)
            grid.addWidget(self.link_chk)
        else:
            grid.addWidget(mode_label, 0, 0)
            grid.addWidget(self.mode_combo, 0, 1, 1, 6)
            grid.addWidget(scale_label, 1, 0)
            for i, (lab, edit) in enumerate(zip(axis_labels, self.edits)):
                grid.addWidget(lab, 1, 1 + i * 2)
                grid.addWidget(edit, 1, 2 + i * 2)
            grid.addWidget(self.link_chk, 1, 7)
            grid.setColumnStretch(2, 1)
            grid.setColumnStretch(4, 1)
            grid.setColumnStretch(6, 1)
            grid.addWidget(self.hint, 2, 0, 1, 8)

        self.mode_combo.currentIndexChanged.connect(lambda _i: self.changed.emit())

    # ---------------------------------------------------------------- state
    def mode(self) -> str:
        return self.mode_combo.currentData() or DEFAULT_DISPLAY_MODE

    def error(self) -> str | None:
        """First problem with the scale fields, or None."""
        for axis, edit in zip("XYZ", self.edits):
            value, err = parse_scale_value(edit.text())
            if err:
                return f"Scale {axis} {err}."
        return None

    def scale(self) -> tuple[float, float, float] | None:
        """The parsed scale, or None if any field is invalid."""
        values = [parse_scale_value(e.text())[0] for e in self.edits]
        if any(v is None for v in values):
            return None
        return (values[0], values[1], values[2])  # type: ignore[return-value]

    def set_values(self, mode: str, scale: tuple[float, float, float]) -> None:
        self._busy = True
        try:
            idx = self.mode_combo.findData(mode)
            self.mode_combo.blockSignals(True)
            self.mode_combo.setCurrentIndex(idx if idx >= 0 else 0)
            self.mode_combo.blockSignals(False)
            for edit, value in zip(self.edits, scale):
                edit.setText(f"{value:g}" if float(value) != int(value) else f"{float(value):.1f}")
            self.link_chk.blockSignals(True)
            self.link_chk.setChecked(scale[0] == scale[1] == scale[2])
            self.link_chk.blockSignals(False)
        finally:
            self._busy = False
        self._mark_invalid()
        self.changed.emit()

    # --------------------------------------------------------------- events
    def _on_edit(self, index: int) -> None:
        if self._busy:
            return
        if self.link_chk.isChecked():
            self._busy = True
            try:
                for j, other in enumerate(self.edits):
                    if j != index:
                        other.setText(self.edits[index].text())
            finally:
                self._busy = False
        self._mark_invalid()
        self.changed.emit()

    def _on_link(self, linked: bool) -> None:
        if linked:   # make the axes uniform, using X as the source
            self._busy = True
            try:
                for other in self.edits[1:]:
                    other.setText(self.edits[0].text())
            finally:
                self._busy = False
            self._mark_invalid()
        self.changed.emit()

    def _mark_invalid(self) -> None:
        for edit in self.edits:
            bad = parse_scale_value(edit.text())[1] is not None
            edit.setStyleSheet(_BAD_EDIT if bad else "")


# ------------------------------------------------------------- formatting codes

def selection_state(edit: QLineEdit) -> tuple[int, int]:
    """(caret, anchor) of a line edit; anchor == caret when nothing is selected."""
    caret = edit.cursorPosition()
    if edit.hasSelectedText():
        start, end = edit.selectionStart(), edit.selectionEnd()
        return caret, (end if caret == start else start)
    return caret, caret


def restore_selection(edit: QLineEdit, caret: int, anchor: int) -> None:
    if anchor == caret:
        edit.deselect()
        edit.setCursorPosition(caret)
    else:
        edit.setSelection(anchor, caret - anchor)       # negative length: caret at the start


def insert_code(edit: QLineEdit, code: str) -> None:
    """Insert `code` at the caret of a QLineEdit. Nothing is replaced and the selection stays.

    QLineEdit.insert() would overwrite a selection, so the selection is lifted first and put
    back afterwards (see core.format_codes.plan_insert for the rules). It goes through the
    editor's own insert(), so Ctrl+Z still works.
    """
    caret, anchor = selection_state(edit)
    new_caret, new_anchor = plan_insert(caret, anchor, len(code))
    edit.deselect()
    edit.setCursorPosition(caret)
    edit.insert(code)
    restore_selection(edit, new_caret, new_anchor)
    edit.setFocus(Qt.OtherFocusReason)


_TILE_STYLE = ("QPushButton { background:%(bg)s; color:%(fg)s; border:1px solid #666; "
               "border-radius:3px; padding:3px 6px; text-align:left; %(extra)s } "
               "QPushButton:hover { border:1px solid #ffffff; }")
_OBFUSCATION_GLYPHS = "0123456789#%@&$?"


def _label(text: str) -> str:
    """Button text with literal ampersands (Qt would treat a single & as a mnemonic marker)."""
    return text.replace("&", "&&")


class FormatReferenceWidget(QWidget):
    """Clickable reference of every formatting code, shared by the name and lore editors.

    Colors are drawn as real color tiles, formats as samples in their own style. A click
    inserts the code into whichever tracked field was focused last (see track()). The tiles
    never take keyboard focus, so the field keeps its caret and selection while you click.
    """

    codeInserted = Signal(str)

    COLUMNS = 4

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._text_format = TEXT_SNBT
        self._fields: list[tuple[QLineEdit, Callable[[], str]]] = []
        self._target: QLineEdit | None = None
        # Qt gives focus to the first click-focus ancestor on a mouse press (even over a NoFocus
        # tile) and QLineEdit deselects when it loses focus that way. The state at that moment
        # is kept here and put back before inserting.
        self._saved: tuple[QLineEdit, int, int] | None = None
        self._tiles: list[tuple[QPushButton, CodeInfo]] = []
        self._obfuscated: tuple[QPushButton, str] | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(110)
        self._timer.timeout.connect(self._scramble)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(3)
        head = QHBoxLayout()
        title = QLabel("Formatting codes - click to insert at the cursor")
        title.setObjectName("hint")
        self.status = QLabel("")
        self.status.setObjectName("hint")
        self.status.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        head.addWidget(title, 1)
        head.addWidget(self.status)
        root.addLayout(head)

        grid = QGridLayout()
        grid.setSpacing(3)
        for c in range(self.COLUMNS):
            grid.setColumnStretch(c, 1)
        entries: list[CodeInfo | None] = list(COLOR_REFERENCE) + list(FORMAT_REFERENCE)
        for index, info in enumerate(entries):
            grid.addWidget(self._code_tile(info), index // self.COLUMNS, index % self.COLUMNS)
        extra_row = len(entries) // self.COLUMNS + (1 if len(entries) % self.COLUMNS else 0)
        self.hex_tile = self._plain_tile("&#RRGGBB  Pick...",
                                         "Choose any color; inserts &#rrggbb (hex color).")
        self.hex_tile.clicked.connect(self._on_hex)
        self.literal_tile = self._plain_tile("&&  Literal &",
                                             "Inserts && which is written as a single & character.")
        self.literal_tile.clicked.connect(lambda: self.insert(LITERAL_AMPERSAND))
        grid.addWidget(self.hex_tile, extra_row, 0, 1, 2)
        grid.addWidget(self.literal_tile, extra_row, 2, 1, 2)
        root.addLayout(grid)
        self._refresh_tooltips()
        self._refresh_status()

    # ---------------------------------------------------------------- tiles
    def _plain_tile(self, text: str, tip: str) -> QPushButton:
        btn = QPushButton(_label(text))
        btn.setFocusPolicy(Qt.NoFocus)
        btn.setMinimumHeight(26)
        btn.setToolTip(tip)
        btn.setStyleSheet("QPushButton { padding:3px 6px; text-align:left; }")
        return btn

    def _code_tile(self, info: CodeInfo) -> QPushButton:
        btn = QPushButton(_label(f"{info.text}  {info.label}"))
        btn.setFocusPolicy(Qt.NoFocus)           # keep the caret/selection in the text field
        btn.setCursor(Qt.PointingHandCursor)
        btn.setMinimumHeight(26)
        if info.kind == "color":
            btn.setStyleSheet(_TILE_STYLE % {
                "bg": info.hex, "fg": contrast_text_color(info.hex or "#000000"), "extra": ""})
        else:
            extra = {
                "l": "font-weight:bold;", "o": "font-style:italic;",
                "n": "text-decoration:underline;", "m": "text-decoration:line-through;",
            }.get(info.code, "")
            btn.setStyleSheet(_TILE_STYLE % {"bg": "#e8e8e8", "fg": "#111111", "extra": extra})
            if info.code in ("n", "m"):          # QSS text-decoration is not honoured everywhere
                font = btn.font()
                font.setUnderline(info.code == "n")
                font.setStrikeOut(info.code == "m")
                btn.setFont(font)
            if info.code == "k":
                width = QFontMetrics(btn.font()).horizontalAdvance("&k  " + "0" * len(info.label))
                btn.setMinimumWidth(width + 24)   # scrambling text must not resize the tile
                self._obfuscated = (btn, info.label)
        btn.clicked.connect(lambda _c=False, text=info.text: self.insert(text))
        self._tiles.append((btn, info))
        return btn

    def tile(self, code: str) -> QPushButton:
        for btn, info in self._tiles:
            if info.code == code:
                return btn
        raise KeyError(code)

    # ------------------------------------------------------- version syntax
    def set_text_format(self, text_format: str) -> None:
        """Target version: tooltips show the component syntax this version needs."""
        self._text_format = text_format
        self._refresh_tooltips()

    def _refresh_tooltips(self) -> None:
        for btn, info in self._tiles:
            sample = f"<span style=\"color:{info.hex}\">Sample</span> - " if info.hex else ""
            btn.setToolTip(
                f"<b>{info.text}</b> {info.label}<br>{sample}"
                f"<code>{_escape(code_snippet(info.code, self._text_format))}</code>")

    # -------------------------------------------------------------- targets
    def track(self, edit: QLineEdit, label: str | Callable[[], str]) -> None:
        """Make `edit` an insertion target; it becomes the target whenever it gets focus."""
        getter = label if callable(label) else (lambda text=label: text)
        self._fields.append((edit, getter))
        edit.installEventFilter(self)

    def forget(self, edit: QLineEdit, fallback: QLineEdit | None = None) -> None:
        """A tracked field is going away: stop tracking it. If it was the target, insertions go
        to `fallback` instead of into a deleted widget."""
        self._fields = [(e, g) for e, g in self._fields if e is not edit]
        if self._target is edit:
            self._target = fallback
        self._refresh_status()

    def set_target(self, edit: QLineEdit | None) -> None:
        self._target = edit
        self._refresh_status()

    def target(self) -> QLineEdit | None:
        if self._target is not None and not isValid(self._target):
            self._target = None
        return self._target

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt naming)
        if isinstance(obj, QLineEdit):
            if event.type() == QEvent.FocusIn:
                self._target = obj
                if self._saved is not None and self._saved[0] is obj:
                    self._saved = None
                self._refresh_status()
            elif event.type() == QEvent.FocusOut:
                self._saved = (obj, *selection_state(obj))   # filters run before the deselect
        return False

    def _label_of(self, edit: QLineEdit) -> str:
        self._fields = [(e, g) for e, g in self._fields if isValid(e)]
        for e, getter in self._fields:
            if e is edit:
                return getter()
        return ""

    def _refresh_status(self) -> None:
        target = self.target()
        self.status.setText(f"Inserting into: {self._label_of(target)}" if target is not None
                            else "Click a name or lore field first")

    def refresh_status(self) -> None:
        self._refresh_status()

    # ------------------------------------------------------------ inserting
    def insert(self, code: str) -> bool:
        target = self.target()
        if target is None or not target.isEnabled():
            self._refresh_status()
            return False
        if self._saved is not None and self._saved[0] is target:
            _edit, caret, anchor = self._saved
            self._saved = None
            if not target.hasFocus():
                restore_selection(target, caret, anchor)
        insert_code(target, code)
        self.codeInserted.emit(code)
        return True

    def _pick_color(self) -> QColor:
        return QColorDialog.getColor(QColor("#ffaa00"), self, "Choose a color")

    def _on_hex(self) -> None:
        color = self._pick_color()
        if color.isValid():
            self.insert(hex_code(color.name()))

    # ---------------------------------------------------------- obfuscation
    def _scramble(self) -> None:
        if self._obfuscated is not None:
            btn, label = self._obfuscated
            btn.setText(_label("&k  " + "".join(random.choice(_OBFUSCATION_GLYPHS) for _ in label)))

    def showEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        super().showEvent(event)
        if self._obfuscated is not None:
            self._timer.start()

    def hideEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        super().hideEvent(event)
        self._timer.stop()


def _escape(text: str) -> str:
    from html import escape
    return escape(text)


# ------------------------------------------------------------------ lore editor

_ROW_BUTTON = "QPushButton { padding: 2px 0; }"


class _LoreRow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(3)
        self.number = QLabel("1")
        self.number.setFixedWidth(24)
        self.number.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.number.setObjectName("hint")
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("Lore line (empty = blank line), e.g. &7Forged in fire")
        self.up = self._button("\u25b2", "Move line up")
        self.down = self._button("\u25bc", "Move line down")
        self.remove = self._button("\u2715", "Remove line")
        for w in (self.number,):
            row.addWidget(w)
        row.addWidget(self.edit, 1)
        for b in (self.up, self.down, self.remove):
            row.addWidget(b)

    @staticmethod
    def _button(text: str, tip: str) -> QPushButton:
        b = QPushButton(text)
        b.setToolTip(tip)
        b.setFixedWidth(28)
        b.setStyleSheet(_ROW_BUTTON)
        return b


class LoreEditor(QWidget):
    """Multi-line lore editor: add, remove and reorder lines; one &-code line per row."""

    changed = Signal()
    lineCreated = Signal(QLineEdit)       # so the shared code reference can track the field
    lineRemoved = Signal(QLineEdit)       # ... and stop tracking it (before the row is deleted)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: list[_LoreRow] = []
        self._busy = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(3)

        head = QHBoxLayout()
        self.count_lbl = QLabel("")
        self.count_lbl.setObjectName("hint")
        self.add_btn = QPushButton("Add Line")
        self.add_btn.setToolTip("Add a lore line at the end (Enter inside a line adds one below it).")
        self.add_btn.clicked.connect(lambda: self.add_line(focus=True))
        head.addWidget(self.count_lbl, 1)
        head.addWidget(self.add_btn)
        outer.addLayout(head)

        self._rows_box = QVBoxLayout()
        self._rows_box.setSpacing(2)
        outer.addLayout(self._rows_box)

        self.preview = QLabel()
        self.preview.setTextFormat(Qt.RichText)
        self.preview.setStyleSheet("QLabel { background:#100010; border:2px solid #2a0a5e; "
                                   "border-radius:3px; padding:4px 6px; }")
        outer.addWidget(self.preview)
        self._renumber()

    # ----------------------------------------------------------------- data
    def lines(self) -> list[str]:
        return [row.edit.text() for row in self._rows]

    def line_count(self) -> int:
        return len(self._rows)

    def line_edit(self, index: int) -> QLineEdit:
        return self._rows[index].edit

    def index_of(self, edit: QLineEdit) -> int:
        for i, row in enumerate(self._rows):
            if row.edit is edit:
                return i
        return -1

    def set_lines(self, lines: list[str], notify: bool = True) -> None:
        """Replace all lines. `notify=False` skips the `changed` signal (the caller refreshes
        its preview itself); lineCreated/lineRemoved are always sent so tracking stays right."""
        self._busy = True
        try:
            for row in self._rows:
                self.lineRemoved.emit(row.edit)
                self._rows_box.removeWidget(row)
                row.setParent(None)
                row.deleteLater()
            self._rows.clear()
            for text in lines[:MAX_LORE_LINES]:
                self._insert_row(len(self._rows), text)
        finally:
            self._busy = False
        self._renumber()
        if notify:
            self.changed.emit()

    # ------------------------------------------------------------- editing
    def add_line(self, text: str = "", index: int | None = None, focus: bool = False) -> QLineEdit | None:
        if len(self._rows) >= MAX_LORE_LINES:
            return None
        at = len(self._rows) if index is None else max(0, min(index, len(self._rows)))
        row = self._insert_row(at, text)
        self._renumber()
        if focus:
            row.edit.setFocus(Qt.OtherFocusReason)
        self.changed.emit()
        return row.edit

    def remove_line(self, index: int) -> None:
        if not 0 <= index < len(self._rows):
            return
        row = self._rows.pop(index)
        self.lineRemoved.emit(row.edit)
        self._rows_box.removeWidget(row)
        row.setParent(None)
        row.deleteLater()
        self._renumber()
        if self._rows:
            self._rows[min(index, len(self._rows) - 1)].edit.setFocus(Qt.OtherFocusReason)
        self.changed.emit()

    def move_line(self, index: int, delta: int) -> None:
        new = index + delta
        if not (0 <= index < len(self._rows) and 0 <= new < len(self._rows)):
            return
        row = self._rows.pop(index)
        self._rows.insert(new, row)
        self._rows_box.removeWidget(row)
        self._rows_box.insertWidget(new, row)
        caret = row.edit.cursorPosition()
        self._renumber()
        row.edit.setFocus(Qt.OtherFocusReason)       # follow the moved line, keep the caret
        row.edit.setCursorPosition(caret)
        self.changed.emit()

    def _insert_row(self, at: int, text: str) -> _LoreRow:
        row = _LoreRow()
        row.edit.setText(text)
        self._rows.insert(at, row)
        self._rows_box.insertWidget(at, row)
        row.edit.textChanged.connect(self._on_text)
        row.edit.returnPressed.connect(lambda r=row: self.add_line(index=self._rows.index(r) + 1, focus=True))
        row.up.clicked.connect(lambda _c=False, r=row: self.move_line(self._rows.index(r), -1))
        row.down.clicked.connect(lambda _c=False, r=row: self.move_line(self._rows.index(r), 1))
        row.remove.clicked.connect(lambda _c=False, r=row: self.remove_line(self._rows.index(r)))
        self.lineCreated.emit(row.edit)
        return row

    def _on_text(self) -> None:
        if self._busy:
            return
        self._update_preview()
        self.changed.emit()

    def _renumber(self) -> None:
        last = len(self._rows) - 1
        for i, row in enumerate(self._rows):
            row.number.setText(str(i + 1))
            row.up.setEnabled(i > 0)
            row.down.setEnabled(i < last)
        n = len(self._rows)
        self.count_lbl.setText("No lore lines" if n == 0 else f"{n} lore line{'s' if n != 1 else ''}")
        self.add_btn.setEnabled(n < MAX_LORE_LINES)
        self._update_preview()

    def _update_preview(self) -> None:
        if not self._rows:
            self.preview.setText('<span style="color:#8d9299">(no lore)</span>')
            return
        html = []
        for line in self.lines():
            segments = parse_legacy(line, strip=False)
            html.append(segments_to_html(segments, LORE_DEFAULT_COLOR) if segments else "&nbsp;")
        self.preview.setText("<br>".join(html))


# ---------------------------------------------------------------- game-style tooltip

class TooltipPreview(QWidget):
    """The item as the in-game tooltip shows it (dark purple box, colored lines)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._plain: list[str] = []
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(3)
        self.body = QLabel()
        self.body.setTextFormat(Qt.RichText)
        self.body.setWordWrap(True)
        self.body.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.body.setMinimumWidth(200)
        self.body.setStyleSheet(
            "QLabel { background:#100010; border:2px solid #28007f; border-top-color:#5000ff; "
            "border-left-color:#5000ff; border-radius:2px; padding:5px 8px; "
            "font-family:'Consolas','DejaVu Sans Mono',monospace; font-size:13px; }")
        self.caption = QLabel()
        self.caption.setObjectName("hint")
        self.caption.setWordWrap(True)
        root.addWidget(self.body)
        root.addWidget(self.caption)

    def set_lines(self, lines, traits: list[str] | None = None) -> None:
        """`lines` from core.tooltip.build_tooltip (None = hidden tooltip)."""
        if lines is None:
            self._plain = []
            self.body.setText('<span style="color:#8d9299">(tooltip hidden in game)</span>')
        else:
            self._plain = ["".join(seg.text for seg in line) for line in lines]
            self.body.setText("<br>".join(
                segments_to_html(line) if line else "&nbsp;" for line in lines))
        self.caption.setText(("Also: " + ", ".join(traits)) if traits else "")
        self.caption.setVisible(bool(traits))

    def plain_lines(self) -> list[str]:
        return list(self._plain)


# ------------------------------------------------- attribute / enchantment row editors

class NoWheelDoubleSpinBox(QDoubleSpinBox):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)

    def wheelEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class _RowEditor(QWidget):
    """Header (count + Add button) and a list of removable rows. Subclasses build the rows."""

    changed = Signal()

    def __init__(self, add_text: str, max_rows: int, empty_text: str,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: list[QWidget] = []
        self._max = max_rows
        self._empty = empty_text
        self._busy = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(3)
        head = QHBoxLayout()
        self.count_lbl = QLabel("")
        self.count_lbl.setObjectName("hint")
        self.add_btn = QPushButton(add_text)
        self.add_btn.clicked.connect(lambda: self._add_default())
        head.addWidget(self.count_lbl, 1)
        head.addWidget(self.add_btn)
        outer.addLayout(head)
        self._rows_box = QVBoxLayout()
        self._rows_box.setSpacing(2)
        outer.addLayout(self._rows_box)
        self._refresh()

    # subclasses
    def _add_default(self) -> None:
        raise NotImplementedError

    def row_count(self) -> int:
        return len(self._rows)

    def _attach(self, row: QWidget, remove_btn: QPushButton) -> None:
        self._rows.append(row)
        self._rows_box.addWidget(row)
        remove_btn.clicked.connect(lambda _c=False, r=row: self.remove_row(self._rows.index(r)))
        self._refresh()
        if not self._busy:
            self.changed.emit()

    def remove_row(self, index: int) -> None:
        if not 0 <= index < len(self._rows):
            return
        row = self._rows.pop(index)
        self._rows_box.removeWidget(row)
        row.setParent(None)
        row.deleteLater()
        self._refresh()
        self.changed.emit()

    def _clear(self) -> None:
        for row in self._rows:
            self._rows_box.removeWidget(row)
            row.setParent(None)
            row.deleteLater()
        self._rows.clear()

    def _notify(self) -> None:
        if not self._busy:
            self.changed.emit()

    def _refresh(self) -> None:
        n = len(self._rows)
        self.count_lbl.setText(self._empty if n == 0 else f"{n} entr{'y' if n == 1 else 'ies'}")
        self.add_btn.setEnabled(n < self._max)

    @staticmethod
    def _remove_button() -> QPushButton:
        b = QPushButton("\u2715")
        b.setToolTip("Remove")
        b.setFixedWidth(28)
        b.setStyleSheet(_ROW_BUTTON)
        return b


def _name_combo(options: tuple[str, ...], placeholder: str) -> NoWheelComboBox:
    combo = NoWheelComboBox()
    combo.setEditable(True)
    combo.setInsertPolicy(QComboBox.NoInsert)
    combo.addItems(list(options))
    combo.lineEdit().setPlaceholderText(placeholder)
    return combo


def _shown_id(item_id: str) -> str:
    """'minecraft:sharpness' is shown as 'sharpness'; other namespaces stay complete."""
    return item_id[len("minecraft:"):] if item_id.startswith("minecraft:") else item_id


class AttributeEditor(_RowEditor):
    """Rows of attribute modifiers: attribute, operation, amount, slot."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Add Modifier", MAX_ATTRIBUTES, "No attribute modifiers", parent)

    def _add_default(self) -> None:
        self.add_modifier(AttributeModifier("minecraft:attack_damage", 1.0, "add_value", "mainhand"))

    def add_modifier(self, m: AttributeModifier) -> None:
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)
        attr = _name_combo(KNOWN_ATTRIBUTES, "attribute, e.g. attack_damage")
        attr.setCurrentText(_shown_id(m.type))
        attr.setToolTip("Attribute id. Pick one or type any id (modded ones need a namespace).")
        op = NoWheelComboBox()
        for key in OPERATIONS:
            op.addItem(OPERATION_LABELS[key], key)
        op.setCurrentIndex(max(0, op.findData(m.operation)))
        op.setToolTip("Add: +n. Multiply base: +n% of the base value. "
                      "Multiply total: x(1+n) after all other modifiers (n = 0.1 is 10%).")
        amount = NoWheelDoubleSpinBox()
        amount.setDecimals(3)
        amount.setRange(-1_000_000.0, 1_000_000.0)
        amount.setSingleStep(0.5)
        amount.setValue(m.amount)
        amount.setMinimumWidth(80)
        slot = NoWheelComboBox()
        for key in SLOTS:
            slot.addItem(SLOT_LABELS[key], key)
        slot.setCurrentIndex(max(0, slot.findData(m.slot)))
        remove = self._remove_button()
        lay.addWidget(attr, 3)
        lay.addWidget(op, 2)
        lay.addWidget(amount, 1)
        lay.addWidget(slot, 2)
        lay.addWidget(remove)
        row.parts = (attr, op, amount, slot)               # type: ignore[attr-defined]
        attr.editTextChanged.connect(self._notify)
        op.currentIndexChanged.connect(self._notify)
        amount.valueChanged.connect(self._notify)
        slot.currentIndexChanged.connect(self._notify)
        self._attach(row, remove)

    def modifiers(self) -> list[AttributeModifier]:
        out = []
        for row in self._rows:
            attr, op, amount, slot = row.parts             # type: ignore[attr-defined]
            out.append(AttributeModifier(normalize_id(attr.currentText()), amount.value(),
                                         op.currentData(), slot.currentData()))
        return out

    def set_modifiers(self, mods: list[AttributeModifier]) -> None:
        self._busy = True
        try:
            self._clear()
            for m in mods:
                self.add_modifier(m)
        finally:
            self._busy = False
        self._refresh()
        self.changed.emit()


class EnchantmentEditor(_RowEditor):
    """Rows of enchantments: id and level."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Add Enchantment", 64, "No enchantments", parent)

    def _add_default(self) -> None:
        used = {_shown_id(e) for e, _l in self.enchantments()}
        free = next((e for e in KNOWN_ENCHANTMENTS if e not in used), "sharpness")
        self.add_enchantment(f"minecraft:{free}", 1)

    def add_enchantment(self, ench: str, level: int) -> None:
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)
        combo = _name_combo(KNOWN_ENCHANTMENTS, "enchantment, e.g. sharpness")
        combo.setCurrentText(_shown_id(ench))
        combo.setToolTip("Enchantment id. Pick one or type any id (datapack enchantments need a "
                         "namespace).")
        spin = NoWheelSpinBox()
        spin.setRange(1, MAX_ENCHANT_LEVEL)
        spin.setValue(max(1, min(MAX_ENCHANT_LEVEL, level)))
        spin.setPrefix("Level ")
        remove = self._remove_button()
        lay.addWidget(combo, 3)
        lay.addWidget(spin, 1)
        lay.addWidget(remove)
        row.parts = (combo, spin)                          # type: ignore[attr-defined]
        combo.editTextChanged.connect(self._notify)
        spin.valueChanged.connect(self._notify)
        self._attach(row, remove)

    def enchantments(self) -> list[tuple[str, int]]:
        return [(normalize_id(c.currentText()), s.value())
                for c, s in (row.parts for row in self._rows)]   # type: ignore[attr-defined]

    def set_enchantments(self, pairs: list[tuple[str, int]]) -> None:
        self._busy = True
        try:
            self._clear()
            for ench, level in pairs:
                self.add_enchantment(ench, level)
        finally:
            self._busy = False
        self._refresh()
        self.changed.emit()
