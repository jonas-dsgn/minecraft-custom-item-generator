"""GUI checks. Needs PySide6; run headless with:  QT_QPA_PLATFORM=offscreen python -m unittest tests.test_gui"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, QSettings, Qt
    from PySide6.QtGui import QColor, QFocusEvent, QWheelEvent
    from PySide6.QtWidgets import QApplication, QDialog, QLineEdit, QMessageBox, QScrollArea
except ImportError:  # pragma: no cover
    QApplication = None

from core.attributes import AttributeModifier as Attr  # noqa: E402
from ui.template_dialog import PackTemplateDialog  # noqa: E402
from core.text_components import parse_legacy as parse_legacy_text  # noqa: E402
from core.validation import DISPLAY_MODES  # noqa: E402

if QApplication is not None:
    from ui import main_window as mw  # noqa: E402
    from ui.recipe_dialog import RecipeDialog  # noqa: E402
    from ui.widgets import DisplayOptionsWidget  # noqa: E402


@unittest.skipIf(QApplication is None, "PySide6 not installed")
class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.tmp = tempfile.TemporaryDirectory()
        QSettings.setPath(QSettings.NativeFormat, QSettings.UserScope, cls.tmp.name)
        QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, cls.tmp.name)

    @staticmethod
    def wheel(widget, delta=-120):
        """Deliver a wheel event like Qt does for real input: starting at the widget under the
        cursor and moving up through its parents until one accepts it. (sendEvent alone does
        not propagate; real spontaneous events do.) Returns the widget that accepted it."""
        w = widget
        pos = QPointF(5, 5)
        glob = widget.mapToGlobal(pos.toPoint())
        while w is not None:
            local = QPointF(w.mapFromGlobal(glob))
            ev = QWheelEvent(local, QPointF(glob), QPoint(0, 0), QPoint(0, delta),
                             Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
            ev.setAccepted(True)
            QCoreApplication.sendEvent(w, ev)
            if ev.isAccepted():
                return w
            w = w.parentWidget()
        return None

    def make_window(self):
        root = Path(tempfile.mkdtemp(dir=self.tmp.name))
        rp = root / "rp"
        for d in ("assets/minecraft/items", "assets/minecraft/models/item", "assets/minecraft/textures/item"):
            (rp / d).mkdir(parents=True)
        (rp / "pack.mcmeta").write_text("{}")
        dp = root / "dp"
        (dp / "data/customitems/function").mkdir(parents=True)
        (dp / "pack.mcmeta").write_text("{}")
        (rp / "assets/minecraft/items/andesite_greek_pillar.json").write_text("{}")
        (rp / "assets/minecraft/textures/item/ruby.png").write_bytes(b"png")
        QSettings("MinecraftItemGenerator", "ItemGenerator").clear()   # tests must not share state
        w = mw.MainWindow()
        w.rp_edit.setText(str(rp)); w.dp_edit.setText(str(dp))
        w.ns_combo.setEditText("customitems")
        w._refresh_rp(); w._refresh_dp(detect=False)
        # never block on modal dialogs
        QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
        QMessageBox.warning = staticmethod(lambda *a, **k: None)
        return w, rp, dp

    # ------------------------------------------------------------ layout
    def test_scroll_resize_fullscreen(self):
        w, _, _ = self.make_window()
        w.show(); self.app.processEvents()
        bar = w.scroll.verticalScrollBar()

        w.resize(900, 420); self.app.processEvents()          # small: must scroll
        self.assertGreater(bar.maximum(), 0)
        self.assertTrue(bar.isVisible())
        self.assertTrue(w.action_btn.isVisible())             # footer pinned, outside the scroll
        self.assertFalse(w.scroll.isAncestorOf(w.action_btn))

        # every control reachable by scrolling: scroll to the end, log + settings in view
        bar.setValue(bar.maximum()); self.app.processEvents()
        for widget in (w.log_view, w.display_new_chk, w.give_chk):
            top = widget.mapTo(w.scroll.viewport(), QPoint(0, 0)).y()
            self.assertLess(top, w.scroll.viewport().height(), widget)
        bar.setValue(0)

        # mouse wheel over the page (a label) scrolls it
        before = bar.value()
        handled_by = self.wheel(w.rp_msg); self.app.processEvents()
        self.assertIs(handled_by, w.scroll.viewport())
        self.assertGreater(bar.value(), before)

        # a combo that is not focused ignores the wheel (so the page scrolls instead)
        combo = w.target_combo
        idx = combo.currentIndex()
        before = bar.value()
        self.assertIs(self.wheel(combo), w.scroll.viewport())
        self.assertEqual(combo.currentIndex(), idx)
        self.assertGreaterEqual(bar.value(), before)

        # large (1080p): no scrolling needed, content fills the width, extra height goes to tabs/log
        w.resize(1920, 1080); self.app.processEvents()
        self.assertEqual(bar.maximum(), 0)
        self.assertGreaterEqual(w.tabs.width(), 1800)
        self.assertGreater(w.log_view.height(), 70)
        # F11 handler: fullscreen on/off and maximize/restore keep the layout valid
        w._toggle_fullscreen(); self.app.processEvents()
        self.assertTrue(w.isFullScreen())
        self.assertTrue(w.action_btn.isVisible())
        w._toggle_fullscreen(); self.app.processEvents()
        self.assertFalse(w.isFullScreen())
        w.showMaximized(); self.app.processEvents()
        w.showNormal(); w.resize(1000, 700); self.app.processEvents()
        w.resize(700, 480); self.app.processEvents()
        self.assertGreater(bar.maximum(), 0)
        w.resize(1000, 700); self.app.processEvents()
        self.assertGreater(w.scroll.viewport().width(), 900)    # width follows the window
        # one scroll area for the page only (the other is none: recipe dialog is separate)
        self.assertEqual(len(w.findChildren(QScrollArea)), 1)
        w.close()

    def test_item_editor_not_squeezed_when_small(self):
        w, _, dp = self.make_window()
        (dp / "data/customitems/function/give").mkdir(parents=True)
        (dp / "data/customitems/function/give/ruby.mcfunction").write_text(
            'give @p minecraft:stick[item_model="minecraft:ruby"]\n')
        w.show(); w._refresh_dp(detect=False)
        w.tabs.setCurrentIndex(2); w.items_list.setCurrentRow(0)
        w.display_chk.setChecked(True)
        w.resize(900, 450); self.app.processEvents()
        for widget in (w.display_opts, w.cmd_preview, w.display_edit, w.item_base_edit):
            self.assertGreaterEqual(widget.height(), widget.minimumSizeHint().height(), widget)
        self.assertGreaterEqual(w.display_opts.height(), w.display_opts.sizeHint().height())
        self.assertGreater(w.scroll.verticalScrollBar().maximum(), 0)
        w.close()

    def test_recipe_dialog_fits_small_screen(self):
        w, _, _ = self.make_window()
        dlg = RecipeDialog("a", {}, "customitems", None, w)
        dlg.show(); dlg.resize(500, 340); self.app.processEvents()
        self.assertTrue(dlg.save_button.isVisible())
        scroll = dlg.findChild(QScrollArea)
        self.assertGreater(scroll.verticalScrollBar().maximum() + scroll.horizontalScrollBar().maximum(), 0)
        self.assertFalse(scroll.isAncestorOf(dlg.save_button))
        dlg.close(); w.close()

    # ---------------------------------------------------- display widget
    def test_widget_modes_link_validation(self):
        wd = DisplayOptionsWidget()
        self.assertEqual([wd.mode_combo.itemData(i) for i in range(wd.mode_combo.count())], list(DISPLAY_MODES))
        self.assertEqual(wd.mode(), "fixed")
        self.assertEqual(wd.scale(), (1.0, 1.0, 1.0))
        wd.edits[0].setText("2.5")                      # linked: all follow X
        self.assertEqual(wd.scale(), (2.5, 2.5, 2.5))
        wd.link_chk.setChecked(False)
        wd.edits[1].setText("1")
        self.assertEqual(wd.scale(), (2.5, 1.0, 2.5))
        wd.edits[2].setText("abc")
        self.assertIsNone(wd.scale())
        self.assertIn("Scale Z", wd.error())
        self.assertIn("border", wd.edits[2].styleSheet())
        wd.link_chk.setChecked(True)                    # re-link: X wins, error gone
        self.assertEqual(wd.scale(), (2.5, 2.5, 2.5))
        self.assertIsNone(wd.error())
        wd.set_values("gui", (1.0, 2.0, 3.0))
        self.assertFalse(wd.link_chk.isChecked())
        self.assertEqual((wd.mode(), wd.scale()), ("gui", (1.0, 2.0, 3.0)))

    # --------------------------------------------------- end-to-end paths
    def test_existing_model_with_display_all_modes_and_scales(self):
        w, rp, dp = self.make_window()
        w.tabs.setCurrentIndex(1); w._on_scan()
        names = [w.models_list.item(i).data(Qt.UserRole) for i in range(w.models_list.count())]
        self.assertIn("andesite_greek_pillar", names)
        for i in range(w.models_list.count()):
            if w.models_list.item(i).data(Qt.UserRole) == "andesite_greek_pillar":
                w.models_list.item(i).setSelected(True)
        w.display_new_chk.setChecked(True)
        w.display_opts_new.mode_combo.setCurrentIndex(DISPLAY_MODES.index("thirdperson_lefthand"))
        w.display_opts_new.link_chk.setChecked(False)
        for edit, text in zip(w.display_opts_new.edits, ("1", "2", "0.5")):
            edit.setText(text)
        w._run_footer_action()
        fn = dp / "data/customitems/function"
        self.assertEqual((fn / "give/andesite_greek_pillar.mcfunction").read_text(),
                         'give @p minecraft:stick[item_model="minecraft:andesite_greek_pillar"]\n')
        text = (fn / "display/andesite_greek_pillar.mcfunction").read_text()
        self.assertIn('item_display:"thirdperson_lefthand"', text)
        self.assertIn("scale:[1.0f,2.0f,0.5f]", text)

        # tab C: item shows saved settings; change them and save -> only display file changes
        w.tabs.setCurrentIndex(2); w._refresh_items_list()
        for i in range(w.items_list.count()):
            if w.items_list.item(i).data(Qt.UserRole) == "andesite_greek_pillar":
                w.items_list.setCurrentRow(i)
        self.assertTrue(w.display_chk.isChecked())
        self.assertTrue(w.display_opts.isEnabled())
        self.assertEqual(w.display_opts.mode(), "thirdperson_lefthand")
        self.assertEqual(w.display_opts.scale(), (1.0, 2.0, 0.5))
        self.assertTrue(w.action_btn.isEnabled())
        give_before = (fn / "give/andesite_greek_pillar.mcfunction").read_bytes()
        seen = []
        for mode in DISPLAY_MODES:
            w.display_opts.mode_combo.setCurrentIndex(DISPLAY_MODES.index(mode))
            w.display_opts.link_chk.setChecked(True)
            w.display_opts.edits[0].setText("3")
            self.assertIn(f'item_display:"{mode}"', w.cmd_preview.toPlainText())
            w._run_footer_action()
            seen.append(mode)
            txt = (fn / "display/andesite_greek_pillar.mcfunction").read_text()
            self.assertIn(f'item_display:"{mode}"', txt)
            self.assertIn("scale:[3.0f,3.0f,3.0f]", txt)
            w.display_opts.link_chk.setChecked(False)
        self.assertEqual(seen, list(DISPLAY_MODES))
        self.assertEqual((fn / "give/andesite_greek_pillar.mcfunction").read_bytes(), give_before)

        # invalid scale blocks saving and leaves the file alone
        w.display_opts.link_chk.setChecked(False)
        w.display_opts.edits[1].setText("oops")
        self.assertIn("Scale Y", w.cmd_preview.toPlainText())
        before = (fn / "display/andesite_greek_pillar.mcfunction").read_text()
        w._run_footer_action()
        self.assertEqual((fn / "display/andesite_greek_pillar.mcfunction").read_text(), before)

        # untick: only the display file is removed
        w.display_opts.edits[1].setText("1")
        w.display_chk.setChecked(False)
        w._run_footer_action()
        self.assertFalse((fn / "display/andesite_greek_pillar.mcfunction").exists())
        self.assertTrue((fn / "give/andesite_greek_pillar.mcfunction").exists())
        w.close()

    def test_texture_path_defaults(self):
        w, rp, dp = self.make_window()
        w.names_edit.setPlainText("ruby")
        w.display_new_chk.setChecked(True)          # defaults: fixed, 1.0
        w._run_footer_action()
        fn = dp / "data/customitems/function"
        text = (fn / "display/ruby.mcfunction").read_text()
        self.assertIn('item_display:"fixed"', text)
        self.assertIn("scale:[1.0f,1.0f,1.0f]", text)
        self.assertTrue((fn / "give/ruby.mcfunction").exists())
        w.close()

    # ------------------------------------------- lore, properties, code reference
    def item_window(self, base="minecraft:ender_pearl", store=None):
        """A window with one item ('ruby') selected in tab C."""
        w, rp, dp = self.make_window()
        give = dp / "data/customitems/function/give"
        give.mkdir(parents=True)
        (give / "ruby.mcfunction").write_text(
            f'give @p {base}[item_model="minecraft:ruby"]\n')
        if store is not None:
            (dp / "item_generator_items.json").write_text(json.dumps(store))
            w.store = None                      # as if the project file was there from the start
        w.show(); w._refresh_dp(detect=False)
        w.tabs.setCurrentIndex(2); w.items_list.setCurrentRow(0)
        self.app.processEvents()
        return w, rp, dp

    @staticmethod
    def focus_in(edit):
        """Deliver a focus-in like the window system would (works without an active window)."""
        QCoreApplication.sendEvent(edit, QFocusEvent(QEvent.FocusIn, Qt.OtherFocusReason))

    @staticmethod
    def give_text(dp):
        return (dp / "data/customitems/function/give/ruby.mcfunction").read_text(encoding="utf-8")

    def test_name_editor_is_reused_not_duplicated(self):
        w, _, _ = self.item_window()
        name_edits = [e for e in w.findChildren(QLineEdit) if "Ancient Sword" in e.placeholderText()]
        self.assertEqual(name_edits, [w.display_edit])
        self.assertIs(w.format_ref.target(), w.display_edit)
        self.assertEqual(len(w.findChildren(type(w.format_ref))), 1)       # one shared reference
        self.assertEqual(len(w.findChildren(QScrollArea)), 1)
        w.close()

    def test_reference_inserts_at_caret_without_replacing(self):
        w, _, _ = self.item_window()
        ref, edit = w.format_ref, w.display_edit
        self.assertEqual(ref.tile("6").focusPolicy(), Qt.NoFocus)          # click keeps the caret
        edit.setText("Hello World"); self.focus_in(edit)
        edit.setCursorPosition(5)
        ref.tile("6").click()
        self.assertEqual(edit.text(), "Hello&6 World")                      # nothing replaced
        self.assertEqual(edit.cursorPosition(), 7)                          # caret behind the code
        edit.undo()                                                         # undo still works
        self.assertEqual(edit.text(), "Hello World")
        edit.redo()
        self.assertEqual(edit.text(), "Hello&6 World")
        ref.tile("l").click()
        self.assertEqual(edit.text(), "Hello&6&l World")                    # codes stay in order

        # selection with the caret at its end: same characters stay selected, code goes after
        edit.setText("abcdef"); edit.setSelection(1, 3)                     # "bcd", caret at 4
        ref.tile("l").click()
        self.assertEqual(edit.text(), "abcd&lef")
        self.assertEqual((edit.selectionStart(), edit.selectedText()), (1, "bcd"))

        # selection with the caret at its start: code goes before, selection moves with its text
        edit.setText("abcdef"); edit.setSelection(4, -3)                    # "bcd", caret at 1
        ref.tile("o").click()
        self.assertEqual(edit.text(), "a&obcdef")
        self.assertEqual((edit.selectionStart(), edit.selectedText(), edit.cursorPosition()),
                         (3, "bcd", 3))
        ref.tile("l").click()                                               # repeated clicks keep order
        self.assertEqual(edit.text(), "a&o&lbcdef")
        self.assertEqual(edit.selectedText(), "bcd")

        # emoji before the caret: positions are UTF-16 in Qt, the code is still placed correctly
        edit.setText("\U0001F525ab"); edit.setCursorPosition(len("\U0001F525".encode("utf-16-le")) // 2)
        ref.tile("c").click()
        self.assertEqual(edit.text(), "\U0001F525&cab")
        w.close()

    def test_hex_and_literal_tiles(self):
        w, _, _ = self.item_window()
        ref, edit = w.format_ref, w.display_edit
        edit.setText("ab"); self.focus_in(edit); edit.setCursorPosition(1)
        ref._pick_color = lambda: QColor("#33CCFF")
        ref.hex_tile.click()
        self.assertEqual(edit.text(), "a&#33ccffb")
        ref._pick_color = lambda: QColor()                                  # dialog cancelled
        ref.hex_tile.click()
        self.assertEqual(edit.text(), "a&#33ccffb")
        edit.setText(""); ref.literal_tile.click()
        self.assertEqual(edit.text(), "&&")
        self.assertEqual([c.text for c in parse_legacy_text(edit.text())], ["&"])
        w.close()

    def test_reference_is_shared_with_lore_lines(self):
        w, _, _ = self.item_window()
        ref, lore = w.format_ref, w.lore_editor
        lore.set_lines(["one", "two", "three"])
        w.display_edit.setText("Name")
        self.focus_in(lore.line_edit(1))
        self.assertIs(ref.target(), lore.line_edit(1))
        self.assertIn("Lore line 2", ref.status.text())
        lore.line_edit(1).setCursorPosition(3)
        ref.tile("a").click()
        self.assertEqual(lore.lines(), ["one", "two&a", "three"])
        self.assertEqual(w.display_edit.text(), "Name")                     # name untouched

        lore.move_line(1, -1)                                               # target follows its line
        self.assertEqual(lore.lines(), ["two&a", "one", "three"])
        self.assertIn("Lore line 1", ref.status.text())
        ref.tile("n").click()
        self.assertEqual(lore.lines()[0], "two&a&n")

        # the targeted line is removed: the target is never the dead field. Focus moves to the
        # neighbouring line (which then becomes the target) or, without one, the name is used.
        self.assertIs(ref.target(), lore.line_edit(0))
        removed = lore.line_edit(0)
        lore.remove_line(0)
        self.assertIsNot(ref.target(), removed)
        self.assertIn(ref.target(), (w.display_edit, lore.line_edit(0)))
        ref.tile("c").click()
        everything = [w.display_edit.text()] + lore.lines()
        self.assertEqual(sum(t.count("&c") for t in everything), 1)         # landed exactly once

        lore.set_lines(["solo"]); self.focus_in(lore.line_edit(0))
        self.assertIs(ref.target(), lore.line_edit(0))
        lore.remove_line(0)                                                 # no neighbour left
        self.assertIs(ref.target(), w.display_edit)
        # replacing all lines (selecting another item) also retargets
        lore.set_lines(["a", "b"]); self.focus_in(lore.line_edit(1))
        lore.set_lines([])
        self.assertIs(ref.target(), w.display_edit)
        w.close()

    def test_lore_loaded_from_a_saved_item_is_a_code_target(self):
        store = {"version": 2, "namespaces": {"customitems": {"items": {"ruby": {
            "base_item": "minecraft:ender_pearl", "lore": ["first", "second"]}}}}}
        w, _, _ = self.item_window(store=store)
        self.assertEqual(w.lore_editor.lines(), ["first", "second"])
        self.focus_in(w.lore_editor.line_edit(1))                           # rows made by loading
        self.assertIs(w.format_ref.target(), w.lore_editor.line_edit(1))
        w.lore_editor.line_edit(1).setCursorPosition(0)
        w.format_ref.tile("c").click()
        self.assertEqual(w.lore_editor.lines(), ["first", "&csecond"])
        self.assertIn('{text:"second",color:"red",italic:false}',
                      w.cmd_preview.toPlainText())                         # preview followed the edit
        # switching to another item (here: clearing) leaves no dead target behind
        w._clear_editor()
        self.assertEqual(w.lore_editor.lines(), [])
        self.assertIs(w.format_ref.target(), w.display_edit)
        w.close()

    def test_real_mouse_click_keeps_focus_caret_and_selection(self):
        from PySide6.QtTest import QTest
        w, _, _ = self.item_window()
        w.resize(1000, 1300); self.app.processEvents()
        w.scroll.ensureWidgetVisible(w.display_edit); self.app.processEvents()
        w.lore_editor.set_lines(["abcdef"])
        edit = w.lore_editor.line_edit(0)
        edit.setFocus(); self.app.processEvents()
        edit.setSelection(1, 3)                                             # "bcd"
        tile = w.format_ref.tile("6")
        w.scroll.ensureWidgetVisible(tile); self.app.processEvents()
        QTest.mouseClick(tile, Qt.LeftButton)
        self.app.processEvents()
        self.assertEqual(edit.text(), "abcd&6ef")
        self.assertEqual(edit.selectedText(), "bcd")                        # selection survived
        self.assertIs(w.format_ref.target(), edit)
        # a click on a code also works from the keyboard-free state: no focus stolen by the tile
        self.assertFalse(tile.hasFocus())
        w.close()

    def test_reference_with_no_target_does_nothing(self):
        w, _, _ = self.item_window()
        w.format_ref.set_target(None)
        w.display_edit.setText("x")
        self.assertFalse(w.format_ref.insert("&6"))
        self.assertEqual(w.display_edit.text(), "x")
        self.assertIn("Click a name or lore field", w.format_ref.status.text())
        w.close()

    def test_lore_editor_add_remove_reorder(self):
        w, _, _ = self.item_window()
        lore = w.lore_editor
        self.assertEqual(lore.lines(), [])
        seen = []
        lore.changed.connect(lambda: seen.append(1))
        for text in ("a", "b", "c"):
            lore.add_line(text)
        self.assertEqual(lore.lines(), ["a", "b", "c"])
        lore.add_line("x", index=1)                                         # insert in the middle
        self.assertEqual(lore.lines(), ["a", "x", "b", "c"])
        lore.move_line(3, -1); lore.move_line(0, 1)
        self.assertEqual(lore.lines(), ["x", "a", "c", "b"])
        lore.move_line(0, -1); lore.move_line(3, 1)                         # at the edges: no-op
        self.assertEqual(lore.lines(), ["x", "a", "c", "b"])
        lore.remove_line(1)
        self.assertEqual(lore.lines(), ["x", "c", "b"])
        self.assertFalse(lore._rows[0].up.isEnabled())
        self.assertFalse(lore._rows[-1].down.isEnabled())
        lore.line_edit(0).setText("&6edited")
        self.assertEqual(lore.lines()[0], "&6edited")
        self.assertGreater(len(seen), 5)                                    # every change notifies
        lore._rows[1].remove.click()                                        # real buttons work too
        lore._rows[0].down.click()
        self.assertEqual(lore.lines(), ["b", "&6edited"])
        lore.set_lines([]); self.assertEqual(lore.line_count(), 0)
        w.close()

    def test_lore_preview_and_blank_lines(self):
        w, _, _ = self.item_window()
        w.lore_editor.set_lines(["&cRed", "", "  &lBold"])
        html = w.lore_editor.preview.text()
        self.assertIn("#FF5555", html)                                      # red
        self.assertIn("font-weight:bold", html)
        self.assertIn("&nbsp;", html)                                       # blank line is kept
        w.lore_editor.set_lines(["plain"])
        self.assertIn("#AA00AA", w.lore_editor.preview.text())              # default lore color
        w.close()

    def test_properties_roundtrip_through_files_and_a_new_window(self):
        w, rp, dp = self.item_window()
        w.display_edit.setText("&6Ruby")
        w.lore_editor.set_lines(['&7Forged "in" fire', "", "&cHot \\ it's"])
        w.stack_spin.setValue(8); w.glint_chk.setChecked(True)
        w.rarity_combo.setCurrentIndex(w.rarity_combo.findData("epic"))
        w.unbreakable_chk.setChecked(True); w.hide_tooltip_chk.setChecked(True)
        self.assertIn("lore=[", w.cmd_preview.toPlainText())
        w._run_footer_action()
        text = self.give_text(dp)
        for part in ("lore=[", "max_stack_size=8", "enchantment_glint_override=true",
                     'rarity="epic"', "unbreakable={}", "tooltip_display={hide_tooltip:true}"):
            self.assertIn(part, text)
        self.assertEqual(text.count("\n"), 1)
        stored = json.loads((dp / "item_generator_items.json").read_text(encoding="utf-8"))
        item = stored["namespaces"]["customitems"]["items"]["ruby"]
        self.assertEqual(item["lore"], ['&7Forged "in" fire', "", "&cHot \\ it's"])
        self.assertEqual((item["max_stack_size"], item["glint"], item["rarity"]), (8, True, "epic"))
        self.assertIn("lore", w.items_list.item(0).text())
        w.close()

        # a brand new window reads everything back from the project file
        w2 = mw.MainWindow()
        w2.rp_edit.setText(str(rp)); w2.dp_edit.setText(str(dp))
        w2.ns_combo.setEditText("customitems"); w2._refresh_rp(); w2._refresh_dp(detect=False)
        w2.show(); w2.tabs.setCurrentIndex(2); w2.items_list.setCurrentRow(0)
        self.assertEqual(w2.lore_editor.lines(), ['&7Forged "in" fire', "", "&cHot \\ it's"])
        self.assertEqual((w2.stack_spin.value(), w2.glint_chk.isChecked(), w2.rarity_combo.currentData(),
                          w2.unbreakable_chk.isChecked(), w2.hide_tooltip_chk.isChecked()),
                         (8, True, "epic", True, True))
        self.assertEqual(w2.display_edit.text(), "&6Ruby")
        # saving again without changes keeps the file byte-identical
        before = self.give_text(dp)
        w2._run_footer_action()
        self.assertEqual(self.give_text(dp), before)
        w2.close()

    def test_stack_size_validation_blocks_saving(self):
        w, _, dp = self.item_window(base="minecraft:diamond_sword")
        before = self.give_text(dp)
        w.stack_spin.setValue(5)
        self.assertTrue(w.cmd_preview.toPlainText().startswith("// Item:"))
        self.assertIn("damageable", w.item_notes.text())
        self.assertTrue(w.item_notes.isVisible())
        w._run_footer_action()
        self.assertEqual(self.give_text(dp), before)                        # nothing written
        w.stack_spin.setValue(1)
        self.assertNotIn("damageable", w.item_notes.text())
        w._run_footer_action()
        self.assertIn("max_stack_size=1", self.give_text(dp))
        # changing the base item re-validates, and 'Default' shows the item's own size
        w.stack_spin.setValue(0)
        w.item_base_edit.setText("minecraft:ender_pearl")
        self.assertEqual(w.stack_spin.specialValueText(), "Default (16)")
        w.stack_spin.setValue(40)
        self.assertFalse(w.item_notes.isVisible() and "damageable" in w.item_notes.text())
        w.close()

    def test_target_version_changes_syntax(self):
        w, _, dp = self.item_window()
        w.lore_editor.set_lines(["&7Hi"]); w.hide_tooltip_chk.setChecked(True)
        new = w.cmd_preview.toPlainText()
        self.assertIn('lore=[{text:"Hi",color:"gray",italic:false}]', new)
        self.assertIn("tooltip_display={hide_tooltip:true}", new)
        self.assertIn("text:&quot;Text&quot;", w.format_ref.tile("6").toolTip())
        w.target_combo.setCurrentIndex(w.target_combo.findData("json"))
        old = w.cmd_preview.toPlainText()
        self.assertIn("lore=['{\"text\":\"Hi\",\"color\":\"gray\",\"italic\":false}']", old)
        self.assertIn("hide_tooltip={}", old)
        self.assertNotIn("tooltip_display", old)
        self.assertIn("&quot;text&quot;", w.format_ref.tile("6").toolTip())
        w._run_footer_action()
        self.assertIn("hide_tooltip={}", self.give_text(dp))
        w.close()

    def test_unsupported_extra_components_are_reported_not_discarded(self):
        store = {"version": 1, "namespaces": {"customitems": {"items": {"ruby": {
            "base_item": "minecraft:ender_pearl", "display_name": "",
            "extra_components": {"fire_resistant": "{}", "custom_model_data": "{floats:[1f]}"}}}}}}
        w, _, dp = self.item_window(store=store)
        notes = w.item_notes.text()
        self.assertIn("fire_resistant", notes)                              # visible in the editor
        self.assertIn("left out", notes)
        self.assertIn("custom_model_data", notes)                           # extras are listed
        w._run_footer_action()
        log = w.log_view.toPlainText()
        self.assertIn("[WARNING]", log)
        self.assertIn("fire_resistant", log)                                # and in the log
        text = self.give_text(dp)
        self.assertNotIn("fire_resistant", text)
        self.assertIn("custom_model_data={floats:[1f]}", text)              # others kept
        stored = json.loads((dp / "item_generator_items.json").read_text(encoding="utf-8"))
        kept = stored["namespaces"]["customitems"]["items"]["ruby"]["extra_components"]
        self.assertIn("fire_resistant", kept)                               # not lost from the project
        w.close()

    def test_unusable_stored_values_are_logged_on_load(self):
        store = {"version": 2, "namespaces": {"customitems": {"items": {"ruby": {
            "max_stack_size": 500, "lore": "nope"}}}}}
        w, _, _ = self.item_window(store=store)
        log = w.log_view.toPlainText()
        self.assertIn("max_stack_size", log)
        self.assertIn("lore", log)
        w.close()

    def test_obfuscated_sample_animates_without_resizing(self):
        w, _, _ = self.item_window()
        ref = w.format_ref
        self.assertTrue(ref._timer.isActive())                              # visible: running
        tile = ref.tile("k"); width = tile.width()
        seen = set()
        for _ in range(8):
            ref._scramble(); seen.add(tile.text())
        self.assertGreater(len(seen), 1)
        self.app.processEvents()
        self.assertEqual(tile.width(), width)
        w.hide(); self.assertFalse(ref._timer.isActive())
        w.close()

    def test_editor_tab_fits_lore_and_notes_without_squeezing(self):
        w, _, _ = self.item_window()
        w.lore_editor.set_lines([f"&7line {i}" for i in range(12)])
        w.resize(900, 600); self.app.processEvents(); self.app.processEvents()
        self.assertGreaterEqual(w.tabs.height(), w.items_box.minimumSizeHint().height())
        for edit in (w.display_edit, w.lore_editor.line_edit(0), w.lore_editor.line_edit(11)):
            self.assertGreaterEqual(edit.height(), edit.minimumSizeHint().height())
        self.assertGreater(w.scroll.verticalScrollBar().maximum(), 0)       # the page scrolls
        self.assertEqual(len(w.findChildren(QScrollArea)), 1)
        w.close()

    # ------------------------------- tooltip preview, attribute and enchantment editors
    def test_tooltip_preview_follows_every_edit(self):
        w, _, _ = self.item_window(base="minecraft:diamond_sword")
        tip = w.tooltip
        self.assertEqual(tip.plain_lines(), ["Diamond Sword"])               # no custom name yet
        w.display_edit.setText("&6Ruby")
        self.assertEqual(tip.plain_lines(), ["Ruby"])
        self.assertIn("#FFAA00", tip.body.text())                           # gold
        w.lore_editor.set_lines(["&7Forged"])
        self.assertEqual(tip.plain_lines(), ["Ruby", "Forged"])
        w.ench_editor.add_enchantment("minecraft:sharpness", 5)
        self.assertEqual(tip.plain_lines()[1], "Sharpness V")
        w.attr_editor.add_modifier(Attr("minecraft:attack_damage", 7, "add_value", "mainhand"))
        self.assertEqual(tip.plain_lines()[-3:], ["", "When in Main Hand:", "+7 Attack Damage"])
        self.assertIn("#5555FF", tip.body.text())                           # positive = blue
        w.unbreakable_chk.setChecked(True)
        self.assertEqual(tip.plain_lines()[-1], "Unbreakable")
        w.glint_chk.setChecked(True); w.damage_spin.setValue(300)
        self.assertIn("glint", tip.caption.text())
        self.assertIn("durability 300", tip.caption.text())
        w.hide_tooltip_chk.setChecked(True)                                 # hidden in game
        self.assertEqual(tip.plain_lines(), [])
        self.assertIn("hidden", tip.body.text())
        w.hide_tooltip_chk.setChecked(False)
        w.items_list.clearSelection(); w._clear_editor()
        self.assertEqual(tip.plain_lines(), ["Select an item"])
        w.close()

    def test_attribute_editor_rows(self):
        w, _, _ = self.item_window()
        ed = w.attr_editor
        self.assertEqual(ed.modifiers(), [])
        ed.add_btn.click()                                                  # sensible default row
        self.assertEqual(ed.modifiers(), [Attr("minecraft:attack_damage", 1.0, "add_value", "mainhand")])
        ed.set_modifiers([Attr("minecraft:armor", 3, "add_value", "head"),
                          Attr("mod:thing", -0.25, "add_multiplied_total", "any")])
        self.assertEqual([m.type for m in ed.modifiers()], ["minecraft:armor", "mod:thing"])
        self.assertEqual(ed.modifiers()[1], Attr("mod:thing", -0.25, "add_multiplied_total", "any"))
        attr, op, amount, slot = ed._rows[0].parts
        attr.setCurrentText("luck"); amount.setValue(2.5)                   # bare ids get a namespace
        op.setCurrentIndex(op.findData("add_multiplied_base")); slot.setCurrentIndex(slot.findData("feet"))
        self.assertEqual(ed.modifiers()[0], Attr("minecraft:luck", 2.5, "add_multiplied_base", "feet"))
        ed._rows[0].findChildren(type(ed.add_btn))[0].click()               # remove button of row 1
        self.assertEqual([m.type for m in ed.modifiers()], ["mod:thing"])
        self.assertEqual(ed.count_lbl.text(), "1 entry")
        ed.set_modifiers([])
        self.assertEqual(ed.count_lbl.text(), "No attribute modifiers")
        w.close()

    def test_enchantment_editor_rows(self):
        w, _, _ = self.item_window()
        ed = w.ench_editor
        ed.add_btn.click(); ed.add_btn.click()
        names = [e for e, _l in ed.enchantments()]
        self.assertEqual(len(set(names)), 2)                                # picks unused ones
        ed.set_enchantments([("minecraft:sharpness", 5), ("pack:custom", 300)])
        self.assertEqual(ed.enchantments(), [("minecraft:sharpness", 5), ("pack:custom", 255)])
        ed.remove_row(0)
        self.assertEqual([e for e, _l in ed.enchantments()], ["pack:custom"])
        w.close()

    def test_new_properties_roundtrip_through_files_and_a_new_window(self):
        w, rp, dp = self.item_window(base="minecraft:stick")
        w.display_edit.setText("&6Ruby")
        w.ench_editor.set_enchantments([("minecraft:sharpness", 5), ("minecraft:mending", 1)])
        w.attr_editor.set_modifiers([Attr("minecraft:attack_damage", 7, "add_value", "mainhand"),
                                     Attr("minecraft:movement_speed", 0.1, "add_multiplied_base", "feet")])
        w.stack_spin.setValue(1); w.damage_spin.setValue(750); w.fire_chk.setChecked(True)
        w.custom_data_edit.setText('{tier:3,owner:"ruby"}')
        self.assertEqual(w.item_notes.text().count("ff6b6b"), 0)            # no errors
        w._run_footer_action()
        text = self.give_text(dp)
        for part in ('enchantments={"minecraft:sharpness":5,"minecraft:mending":1}',
                     "attribute_modifiers=[{type:", "max_damage=750", "max_stack_size=1",
                     'damage_resistant={types:"#minecraft:is_fire"}',
                     'custom_data={tier:3,owner:"ruby"}'):
            self.assertIn(part, text)
        parse_ok = text.rstrip("\n")
        self.assertEqual(parse_ok.count("\n"), 0)
        stored = json.loads((dp / "item_generator_items.json").read_text(encoding="utf-8"))
        self.assertEqual(stored["version"], 3)
        w.close()
        w2 = mw.MainWindow()
        w2.rp_edit.setText(str(rp)); w2.dp_edit.setText(str(dp))
        w2.ns_combo.setEditText("customitems"); w2._refresh_rp(); w2._refresh_dp(detect=False)
        w2.show(); w2.tabs.setCurrentIndex(2); w2.items_list.setCurrentRow(0)
        self.assertEqual(w2.ench_editor.enchantments(),
                         [("minecraft:sharpness", 5), ("minecraft:mending", 1)])
        self.assertEqual([m.type for m in w2.attr_editor.modifiers()],
                         ["minecraft:attack_damage", "minecraft:movement_speed"])
        self.assertEqual((w2.damage_spin.value(), w2.fire_chk.isChecked(),
                          w2.custom_data_edit.text()), (750, True, '{tier:3,owner:"ruby"}'))
        self.assertEqual(w2.tooltip.plain_lines()[1], "Sharpness V")         # tooltip right after load
        before = self.give_text(dp)
        w2._run_footer_action()
        self.assertEqual(self.give_text(dp), before)                        # stable on re-save
        w2.close()

    def test_validation_messages_in_the_editor_block_saving(self):
        w, _, dp = self.item_window(base="minecraft:stick")
        before = self.give_text(dp)
        w.damage_spin.setValue(100)                                         # stick stacks to 64
        self.assertIn("stack size to 1", w.item_notes.text())
        self.assertTrue(w.cmd_preview.toPlainText().startswith("// Item:"))
        w._run_footer_action()
        self.assertEqual(self.give_text(dp), before)
        w.stack_spin.setValue(1)
        self.assertNotIn("stack size to 1", w.item_notes.text())

        w.attr_editor.add_modifier(Attr("minecraft:generic.attack_damage", 1))
        self.assertIn("pre-1.21.2", w.item_notes.text())
        self.assertIn("minecraft:attack_damage", w.item_notes.text())
        w.attr_editor.set_modifiers([Attr("minecraft:attack_damage", 1)])
        self.assertNotIn("pre-1.21.2", w.item_notes.text())

        w.ench_editor.set_enchantments([("minecraft:mending", 1), ("minecraft:mending", 2)])
        self.assertIn("listed twice", w.item_notes.text())
        w.ench_editor.set_enchantments([("minecraft:mending", 1)])
        self.assertNotIn("listed twice", w.item_notes.text())

        w.custom_data_edit.setText("{broken")
        self.assertIn("Custom data", w.item_notes.text())
        self.assertTrue(w.cmd_preview.toPlainText().startswith("// Item:"))
        w.custom_data_edit.setText("{ok:1b}")
        self.assertIn("recipe", w.item_notes.text())                        # lossy-number warning, not blocking
        self.assertFalse(w.cmd_preview.toPlainText().startswith("// Item:"))
        w.close()

    def test_version_switch_changes_attribute_and_enchantment_syntax(self):
        w, _, _ = self.item_window()
        w.ench_editor.set_enchantments([("minecraft:mending", 1)])
        w.attr_editor.set_modifiers([Attr("minecraft:luck", 1, "add_value", "head")])
        new = w.cmd_preview.toPlainText()
        self.assertIn('enchantments={"minecraft:mending":1}', new)
        self.assertIn("attribute_modifiers=[{type:", new)
        w.target_combo.setCurrentIndex(w.target_combo.findData("json"))
        old = w.cmd_preview.toPlainText()
        self.assertIn('enchantments={levels:{"minecraft:mending":1}}', old)
        self.assertIn("attribute_modifiers={modifiers:[{type:", old)
        w.close()

    def test_editor_tab_still_fits_with_attributes_and_enchantments(self):
        w, _, _ = self.item_window()
        w.attr_editor.set_modifiers([Attr("minecraft:armor", i + 1) for i in range(6)])
        w.ench_editor.set_enchantments([(f"minecraft:{e}", 1) for e in ("mending", "unbreaking",
                                                                         "fortune", "efficiency")])
        w.resize(900, 600); self.app.processEvents(); self.app.processEvents()
        self.assertGreaterEqual(w.tabs.height(), w.items_box.minimumSizeHint().height())
        for row in w.attr_editor._rows + w.ench_editor._rows:
            for part in row.parts:
                self.assertGreaterEqual(part.height(), part.minimumSizeHint().height())
        self.assertEqual(len(w.findChildren(QScrollArea)), 1)
        w.close()

    # ----------------------------------------------------------- new pack template
    def template_dir(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name)

    def test_template_dialog_validates_live(self):
        where = self.template_dir()
        d = PackTemplateDialog(str(where), "customitems")
        d.show(); self.app.processEvents()
        self.assertEqual(d.error_lbl.text(), "")
        self.assertTrue(d.create_btn.isEnabled())
        preview = d.preview.toPlainText()
        self.assertIn("My Items - Resource Pack/", preview)
        self.assertIn("data/customitems/function/give/", preview)
        self.assertIn('"min_format": [107, 1]', preview)                    # the data pack formats
        self.assertIn('"min_format": [88, 0]', preview)                     # the resource pack formats
        self.assertNotIn("pack_format", preview.replace("min_format", "").replace("max_format", ""))

        d.name_edit.setText("bad/name")
        self.assertFalse(d.create_btn.isEnabled())
        self.assertIn("must not contain", d.error_lbl.text())
        self.assertEqual(d.preview.toPlainText(), "")
        d.name_edit.setText("Good Name")
        self.assertTrue(d.create_btn.isEnabled())

        d.ns_edit.setText("Bad Namespace")
        self.assertFalse(d.create_btn.isEnabled())
        d.dp_chk.setChecked(False)                                          # no datapack: ns is unused
        self.assertTrue(d.create_btn.isEnabled())
        self.assertFalse(d.ns_edit.isEnabled())
        self.assertNotIn("Data Pack", d.preview.toPlainText())
        d.rp_chk.setChecked(False)
        self.assertFalse(d.create_btn.isEnabled())                          # nothing selected
        self.assertIn("at least one", d.error_lbl.text())
        d.rp_chk.setChecked(True); d.dp_chk.setChecked(True); d.ns_edit.setText("ok")

        for text in ("", ".", "relative/dir", str(where / "missing")):      # never the working dir
            d.dir_edit.setText(text)
            self.assertFalse(d.create_btn.isEnabled(), text)
        d.dir_edit.setText(str(where))
        self.assertTrue(d.create_btn.isEnabled())
        d.close()

    def test_template_dialog_versions_and_custom_formats(self):
        d = PackTemplateDialog(str(self.template_dir()), "ns")
        d.show(); self.app.processEvents()
        self.assertFalse(d.custom_box.isVisible())
        d.preset_combo.setCurrentIndex(d.preset_combo.findData("26.3"))
        self.assertIn('"min_format": [121, 0]', d.preview.toPlainText())
        self.assertIn('"min_format": [97, 1]', d.preview.toPlainText())
        d.preset_combo.setCurrentIndex(d.preset_combo.findData("custom"))
        self.assertTrue(d.custom_box.isVisible())
        d.dp_min_major.setValue(130); d.dp_min_minor.setValue(2); d.dp_max_major.setValue(130)
        d.rp_min_major.setValue(100); d.rp_min_minor.setValue(0); d.rp_max_major.setValue(101)
        self.assertTrue(d.create_btn.isEnabled())
        self.assertIn('"min_format": [130, 2]', d.preview.toPlainText())
        self.assertIn('"max_format": 101', d.preview.toPlainText())
        d.dp_min_major.setValue(50)                                         # a pre-1.21.9 format
        self.assertFalse(d.create_btn.isEnabled())
        self.assertIn("Data pack", d.error_lbl.text())
        d.dp_min_major.setValue(130); d.dp_max_major.setValue(120)           # min above max
        self.assertFalse(d.create_btn.isEnabled())
        d.close()

    def test_template_dialog_creates_and_blocks_overwrite(self):
        where = self.template_dir()
        d = PackTemplateDialog(str(where), "customitems")
        d.name_edit.setText("Test Pack")
        d._create()
        self.assertIsNotNone(d.created)
        self.assertTrue((where / "Test Pack - Resource Pack" / "pack.mcmeta").is_file())
        self.assertTrue((where / "Test Pack - Data Pack/data/customitems/function/give").is_dir())
        self.assertEqual(d.result(), QDialog.Accepted)
        # the same name again is refused (button disabled, and a direct call fails cleanly)
        d2 = PackTemplateDialog(str(where), "customitems")
        d2.name_edit.setText("Test Pack")
        self.assertFalse(d2.create_btn.isEnabled())
        self.assertIn("already exists", d2.error_lbl.text())
        d2._create()
        self.assertIsNone(d2.created)
        self.assertEqual(len(list(where.iterdir())), 2)                     # nothing extra written

    def fake_exec(self, name, where, **changes):
        """Stand-in for the modal dialog: fill it in, press Create (or Cancel)."""
        def run(dialog):
            dialog.name_edit.setText(name)
            dialog.dir_edit.setText(str(where))
            for attr, value in changes.items():
                getattr(dialog, attr).setChecked(value) if isinstance(value, bool) \
                    else getattr(dialog, attr).setText(value)
            dialog._create()
            return QDialog.Accepted if dialog.created is not None else QDialog.Rejected
        return run

    def test_new_template_button_creates_and_loads_the_packs(self):
        w, _, _ = self.make_window()
        w.show()
        where = self.template_dir()
        self.assertEqual(w.rp_edit.text() != str(where), True)
        PackTemplateDialog.exec = self.fake_exec("Fresh Start", where, ns_edit="shinyitems")
        self.addCleanup(lambda: delattr(PackTemplateDialog, "exec"))
        w.template_btn.click()
        rp = where / "Fresh Start - Resource Pack"
        dp = where / "Fresh Start - Data Pack"
        self.assertTrue(rp.is_dir() and dp.is_dir())
        # the packs are now loaded: fields, namespace and validation all green, no manual steps
        self.assertEqual((w.rp_edit.text(), w.dp_edit.text()), (str(rp), str(dp)))
        self.assertEqual(w.ns_combo.currentText(), "shinyitems")
        self.assertEqual(w.rp_msg.text(), "Valid resource pack structure.")
        self.assertEqual(w.dp_msg.text(), "Valid datapack structure.")
        for i in range(3):
            self.assertIn("(exists)", w.dir_rows[i][2].text())
        self.assertIn("(exists)", w.dir_rows[3][2].text())                  # datapack give/
        self.assertIn("template created", w.log_view.toPlainText())
        self.assertEqual(w.settings.value("template_dir", "", str), str(where))   # remembered
        # and the tool can immediately write items into the new datapack
        w.tabs.setCurrentIndex(2)
        self.assertEqual(w.items_list.count(), 0)                           # no items yet
        w.close()

    def test_new_template_without_loading_leaves_the_paths_alone(self):
        w, rp, dp = self.make_window()
        where = self.template_dir()
        before = (w.rp_edit.text(), w.dp_edit.text(), w.ns_combo.currentText())
        PackTemplateDialog.exec = self.fake_exec("Detached", where, load_chk=False)
        self.addCleanup(lambda: delattr(PackTemplateDialog, "exec"))
        w.template_btn.click()
        self.assertTrue((where / "Detached - Data Pack" / "pack.mcmeta").is_file())
        self.assertEqual((w.rp_edit.text(), w.dp_edit.text(), w.ns_combo.currentText()), before)
        self.assertIn("template created", w.log_view.toPlainText())
        w.close()

    def test_new_template_only_the_datapack(self):
        w, _, _ = self.make_window()
        where = self.template_dir()
        w.rp_edit.setText(""); w._refresh_rp()
        PackTemplateDialog.exec = self.fake_exec("Only Data", where, rp_chk=False)
        self.addCleanup(lambda: delattr(PackTemplateDialog, "exec"))
        w.template_btn.click()
        self.assertFalse((where / "Only Data - Resource Pack").exists())
        self.assertEqual(w.rp_edit.text(), "")                              # untouched
        self.assertEqual(w.dp_edit.text(), str(where / "Only Data - Data Pack"))
        w.close()

    def test_cancelled_dialog_changes_nothing(self):
        w, _, _ = self.make_window()
        where = self.template_dir()
        before = (w.rp_edit.text(), w.dp_edit.text())
        PackTemplateDialog.exec = lambda dialog: QDialog.Rejected
        self.addCleanup(lambda: delattr(PackTemplateDialog, "exec"))
        w.template_btn.click()
        self.assertEqual((w.rp_edit.text(), w.dp_edit.text()), before)
        self.assertEqual(list(where.iterdir()), [])
        self.assertNotIn("template created", w.log_view.toPlainText())
        w.close()

    def test_dialog_starts_from_the_current_namespace_and_last_folder(self):
        w, _, _ = self.make_window()
        w.ns_combo.setEditText("my_ns")
        where = self.template_dir()
        w.settings.setValue("template_dir", str(where))
        seen = {}

        def peek(dialog):
            seen["ns"], seen["dir"] = dialog.ns_edit.text(), dialog.dir_edit.text()
            return QDialog.Rejected

        PackTemplateDialog.exec = peek
        self.addCleanup(lambda: delattr(PackTemplateDialog, "exec"))
        w.template_btn.click()
        self.assertEqual(seen, {"ns": "my_ns", "dir": str(where)})
        w.close()


if __name__ == "__main__":
    unittest.main()
