"""New pack template: planning, validation, creation, rollback (core only, no Qt).

Run with:  python -m unittest discover -s tests   (from the project root).
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import generator as gen  # noqa: E402
from core import templates as tpl  # noqa: E402
from core.items import ItemRecord  # noqa: E402
from core.project_paths import DatapackPaths, ResourcePackPaths  # noqa: E402
from core.templates import (  # noqa: E402
    PRESETS, FormatRange, TemplateError, TemplateOptions, check_formats, check_options,
    create_templates, mcmeta_text, plan_templates, validate_pack_name,
)
from core.text_components import TEXT_SNBT  # noqa: E402


class TemplateTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.parent = Path(self._tmp.name)

    def opts(self, **kw):
        kw.setdefault("name", "My Items")
        kw.setdefault("namespace", "customitems")
        return TemplateOptions(parent=self.parent, **kw)


class CreationTests(TemplateTestCase):
    def test_creates_both_packs_that_the_tool_accepts(self):
        result = create_templates(self.opts())
        self.assertEqual(result.resource_root, self.parent / "My Items - Resource Pack")
        self.assertEqual(result.data_root, self.parent / "My Items - Data Pack")
        # the tool's own validators call them fully valid, with no manual steps
        self.assertEqual(ResourcePackPaths(result.resource_root).status(),
                         ("ok", "Valid resource pack structure."))
        self.assertEqual(DatapackPaths(result.data_root).status("customitems"),
                         ("ok", "Valid datapack structure."))
        for _label, _path, exists in ResourcePackPaths(result.resource_root).dir_checks():
            self.assertTrue(exists)
        self.assertTrue(DatapackPaths(result.data_root).give_dir("customitems").is_dir())
        self.assertEqual(DatapackPaths(result.data_root).detect_namespaces(), ["customitems"])

    def test_exact_contents_and_no_items_yet(self):
        result = create_templates(self.opts())
        found = sorted(p.relative_to(self.parent).as_posix()
                       for p in self.parent.rglob("*"))
        self.assertEqual(found, sorted([
            "My Items - Resource Pack",
            "My Items - Resource Pack/pack.mcmeta",
            "My Items - Resource Pack/assets",
            "My Items - Resource Pack/assets/minecraft",
            "My Items - Resource Pack/assets/minecraft/items",
            "My Items - Resource Pack/assets/minecraft/models",
            "My Items - Resource Pack/assets/minecraft/models/item",
            "My Items - Resource Pack/assets/minecraft/textures",
            "My Items - Resource Pack/assets/minecraft/textures/item",
            "My Items - Data Pack",
            "My Items - Data Pack/pack.mcmeta",
            "My Items - Data Pack/data",
            "My Items - Data Pack/data/customitems",
            "My Items - Data Pack/data/customitems/function",
            "My Items - Data Pack/data/customitems/function/give",
        ]))
        self.assertEqual((result.directories, result.files), (13, 2))
        self.assertEqual(list(result.resource_root.rglob("*.json")), [])

    def test_mcmeta_follows_the_1_21_9_plus_format(self):
        result = create_templates(self.opts(description="Ünï \"quoted\" \\ pack"))
        for root, lo, hi in ((result.data_root, [107, 1], 121), (result.resource_root, [88, 0], 97)):
            raw = (root / "pack.mcmeta").read_bytes()
            self.assertNotIn(b"\r", raw)                                  # LF only
            self.assertTrue(raw.endswith(b"}\n"))
            pack = json.loads(raw.decode("utf-8"))["pack"]
            self.assertEqual(set(pack), {"description", "min_format", "max_format"})
            self.assertNotIn("pack_format", pack)                         # must be absent
            self.assertNotIn("supported_formats", pack)
            self.assertEqual((pack["min_format"], pack["max_format"]), (lo, hi))
            self.assertEqual(pack["description"], "Ünï \"quoted\" \\ pack")

    def test_description_defaults_to_the_name_and_control_characters_go(self):
        result = create_templates(self.opts())
        pack = json.loads((result.data_root / "pack.mcmeta").read_text(encoding="utf-8"))["pack"]
        self.assertEqual(pack["description"], "My Items")
        text = mcmeta_text("a\nb\tc\x00d", PRESETS[0].data_pack)
        self.assertEqual(json.loads(text)["pack"]["description"], "abcd")

    def test_presets_hold_the_checked_release_numbers(self):
        by_key = {p.key: p for p in PRESETS}
        self.assertEqual(by_key["26.2"].data_pack, FormatRange((107, 1), 107))
        self.assertEqual(by_key["26.2"].resource_pack, FormatRange((88, 0), 88))
        self.assertEqual(by_key["26.3"].data_pack, FormatRange((121, 0), 121))
        self.assertEqual(by_key["26.3"].resource_pack, FormatRange((97, 1), 97))
        self.assertEqual(by_key["26.2+"].data_pack, FormatRange((107, 1), 121))
        self.assertEqual(by_key["26.2+"].resource_pack, FormatRange((88, 0), 97))
        for preset in PRESETS:
            self.assertEqual(check_formats(preset.data_pack, preset.resource_pack), [])

    def test_only_one_pack(self):
        r = create_templates(self.opts(create_data_pack=False))
        self.assertIsNotNone(r.resource_root)
        self.assertIsNone(r.data_root)
        self.assertFalse((self.parent / "My Items - Data Pack").exists())
        r = create_templates(self.opts(name="Second", create_resource_pack=False, namespace="x"))
        self.assertIsNone(r.resource_root)
        self.assertFalse((self.parent / "Second - Resource Pack").exists())

    def test_unicode_and_spaces_in_names(self):
        r = create_templates(self.opts(name="Äpfel & Birnen 🍎"))
        self.assertTrue((r.data_root / "pack.mcmeta").is_file())
        self.assertEqual(r.data_root.name, "Äpfel & Birnen 🍎 - Data Pack")

    def test_plan_writes_nothing_and_shows_the_tree(self):
        plan = plan_templates(self.opts())
        self.assertEqual(list(self.parent.iterdir()), [])
        tree = plan.tree_text()
        for line in ("My Items - Resource Pack/", "    assets/minecraft/items/",
                     "    assets/minecraft/models/item/", "    assets/minecraft/textures/item/",
                     "My Items - Data Pack/", "    data/customitems/function/give/",
                     "    pack.mcmeta"):
            self.assertIn(line, tree.splitlines())

    def test_the_tool_works_in_a_fresh_template(self):
        r = create_templates(self.opts())
        dp = DatapackPaths(r.data_root)
        rec = ItemRecord("ruby", base_item="minecraft:stick", display_name="&6Ruby")
        result = gen.regenerate_items(dp, "customitems", {"ruby": rec}, ["ruby"], TEXT_SNBT)
        self.assertEqual(result.summary.errors, 0)
        self.assertTrue(dp.give_function_path("customitems", "ruby").is_file())
        self.assertEqual(dp.status("customitems"), ("ok", "Valid datapack structure."))


class ValidationTests(TemplateTestCase):
    def test_pack_names(self):
        for good in ("My Items", "a", "Pack 1.2", "Äpfel", "x" * tpl.MAX_NAME_LENGTH, "my-pack_v2"):
            self.assertIsNone(validate_pack_name(good), good)
        bad = ["", "   ", " lead", "trail ", "dot.", "x" * (tpl.MAX_NAME_LENGTH + 1),
               "con", "CON", "nul", "com1", "lpt9", "con.txt"]
        bad += [f"a{c}b" for c in '<>:"/\\|?*'] + ["a\nb", "a\tb", "a\x00b"]
        for name in bad:
            self.assertIsNotNone(validate_pack_name(name), repr(name))

    def test_check_options_rules(self):
        self.assertEqual(check_options(self.opts()), [])
        self.assertTrue(check_options(self.opts(create_resource_pack=False, create_data_pack=False)))
        self.assertTrue(check_options(self.opts(name="bad/name")))
        self.assertTrue(check_options(self.opts(namespace="Upper")))
        self.assertTrue(check_options(self.opts(namespace="")))
        self.assertTrue(check_options(self.opts(namespace="a/b")))
        self.assertTrue(check_options(self.opts(description="x" * (tpl.MAX_DESCRIPTION_LENGTH + 1))))
        # an invalid namespace does not matter when no datapack is created
        self.assertEqual(check_options(self.opts(namespace="Upper", create_data_pack=False)), [])
        # location problems
        self.assertTrue(check_options(TemplateOptions(parent=self.parent / "missing", name="x")))
        (self.parent / "afile").write_text("x")
        self.assertTrue(check_options(TemplateOptions(parent=self.parent / "afile", name="x")))
        for relative in ("", ".", "relative/folder", "..", "somewhere"):          # never the working dir
            errors = check_options(TemplateOptions(parent=Path(relative), name="x"))
            self.assertTrue(errors, relative)
        self.assertEqual(list(Path.cwd().glob("x - *")), [])

    def test_format_rules(self):
        ok = FormatRange((107, 1), 121)
        self.assertEqual(check_formats(ok, FormatRange((88, 0), 97)), [])
        self.assertEqual(check_formats(FormatRange((82, 0), 82), FormatRange((65, 0), 65)), [])
        self.assertTrue(check_formats(FormatRange((81, 0), 90), ok)[0].startswith("Data pack"))
        self.assertTrue(check_formats(ok, FormatRange((64, 0), 90))[0].startswith("Resource pack"))
        self.assertEqual(check_formats(FormatRange((121, 1), 121), ok), [])      # 121 = any minor
        self.assertTrue(check_formats(FormatRange((122, 0), 121), ok)[0].startswith("Data pack"))  # min > max
        self.assertEqual(check_formats(FormatRange((121, 1), (121, 1)), ok), [])
        self.assertTrue(check_formats(FormatRange((121, 2), (121, 1)), ok))
        self.assertTrue(check_formats(FormatRange((-1, 0), 90), ok))
        # a bad format of a pack that is not created is not reported
        bad = FormatRange((10, 0), 20)
        self.assertEqual(check_options(self.opts(data_pack_formats=bad, create_data_pack=False)), [])
        self.assertTrue(check_options(self.opts(data_pack_formats=bad)))

    def test_planning_with_errors_raises(self):
        with self.assertRaises(ValueError):
            plan_templates(self.opts(name="bad/name"))
        with self.assertRaises(ValueError):
            create_templates(self.opts(namespace="Upper"))
        self.assertEqual(list(self.parent.iterdir()), [])


class SafetyTests(TemplateTestCase):
    def test_never_overwrites_even_an_empty_folder(self):
        (self.parent / "My Items - Data Pack").mkdir()
        errors = check_options(self.opts())
        self.assertEqual(len(errors), 1)
        self.assertIn("already exists", errors[0])
        with self.assertRaises(ValueError):
            create_templates(self.opts())
        self.assertFalse((self.parent / "My Items - Resource Pack").exists())   # nothing partial
        # a collision only matters for the pack that would be created
        self.assertEqual(check_options(self.opts(create_data_pack=False)), [])

    def test_existing_content_is_untouched(self):
        root = self.parent / "My Items - Resource Pack"
        root.mkdir()
        (root / "pack.mcmeta").write_text("precious")
        with self.assertRaises(ValueError):
            create_templates(self.opts())
        self.assertEqual((root / "pack.mcmeta").read_text(), "precious")

    def test_failure_halfway_removes_everything_created(self):
        real_open = open
        calls = []

        def flaky(path, *a, **kw):
            calls.append(path)
            if len(calls) == 2:                                   # the second pack.mcmeta
                raise PermissionError("disk full (simulated)")
            return real_open(path, *a, **kw)

        with mock.patch("core.templates.open", flaky, create=True):
            with self.assertRaises(TemplateError) as ctx:
                create_templates(self.opts())
        self.assertIn("simulated", str(ctx.exception))
        self.assertEqual(list(self.parent.iterdir()), [])         # both packs rolled back

    def test_rollback_spares_folders_it_did_not_create(self):
        # the data pack folder appears between the check and the write (a race)
        victim = self.parent / "My Items - Data Pack"
        victim.mkdir()
        (victim / "keep.txt").write_text("mine")
        with mock.patch("core.templates.check_options", return_value=[]):
            with self.assertRaises(TemplateError):
                create_templates(self.opts())
        self.assertEqual((victim / "keep.txt").read_text(), "mine")
        self.assertFalse((self.parent / "My Items - Resource Pack").exists())   # its own work undone

    def test_unwritable_location_is_a_clean_error(self):
        with mock.patch("pathlib.Path.mkdir", side_effect=PermissionError("read-only (simulated)")):
            with self.assertRaises(TemplateError):
                create_templates(self.opts())
        self.assertEqual(list(self.parent.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
