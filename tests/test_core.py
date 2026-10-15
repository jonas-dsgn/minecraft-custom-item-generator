"""Run with:  python -m unittest discover -s tests   (from the project root)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import generator as gen  # noqa: E402
from core.items import STORE_FILENAME, ItemRecord, ProjectStore, StoreError  # noqa: E402
from core.project_paths import DatapackPaths, ResourcePackPaths  # noqa: E402
from core.recipes import Recipe, build_recipe_json, normalize_ingredient, validate_recipe  # noqa: E402
from core.text_components import TEXT_JSON, TEXT_SNBT, build_component  # noqa: E402
from core.validation import (  # noqa: E402
    DISPLAY_MODES, check_display_settings, format_snbt_float, normalize_base_item, parse_names,
    parse_scale_value, validate_namespace,
)


def make_packs(tmp: Path):
    rp = tmp / "rp"
    for d in ("assets/minecraft/items", "assets/minecraft/models/item", "assets/minecraft/textures/item"):
        (rp / d).mkdir(parents=True)
    (rp / "pack.mcmeta").write_text("{}")
    dp = tmp / "dp"
    (dp / "data/customfood/function/foods").mkdir(parents=True)
    (dp / "pack.mcmeta").write_text("{}")
    return ResourcePackPaths(rp), DatapackPaths(dp)


class ValidationTests(unittest.TestCase):
    def test_parse_names(self):
        ok, bad = parse_names(" a_b \n\nA_b\n a_b,c-d\n../x\nC:\\y\n con \nfoo.png")
        self.assertEqual(ok, ["a_b", "c-d"])
        self.assertEqual({n for n, _ in bad}, {"A_b", "../x", "C:\\y", "con", "foo.png"})

    def test_namespace_and_base(self):
        self.assertIsNone(validate_namespace("customfood"))
        self.assertIsNotNone(validate_namespace("Bad/NS"))
        self.assertEqual(normalize_base_item("stick"), ("minecraft:stick", None))
        self.assertIsNotNone(normalize_base_item("minecraft:stick[x]")[1])


class GeneratorTests(unittest.TestCase):
    def test_mode_a_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as t:
            rp, dp = make_packs(Path(t))
            (rp.textures_dir / "mr_electrocks.png").write_bytes(b"png")
            opts = gen.GenerationOptions(namespace="customfood")
            res = gen.generate_items(rp, dp, ["mr_electrocks", "ruby_sword"], opts)
            self.assertEqual(res.summary.created, 3)
            self.assertEqual(res.summary.items_skipped, 1)
            self.assertEqual(res.summary.warnings, 1)
            self.assertEqual(
                json.loads(rp.item_definition_path("mr_electrocks").read_text()),
                {"model": {"type": "minecraft:model", "model": "minecraft:item/mr_electrocks"}},
            )
            self.assertEqual(
                json.loads(rp.model_path("mr_electrocks").read_text()),
                {"parent": "minecraft:item/generated",
                 "textures": {"layer0": "minecraft:item/mr_electrocks"}},
            )
            self.assertEqual(
                dp.give_function_path("customfood", "mr_electrocks").read_text(),
                'give @p minecraft:stick[item_model="minecraft:mr_electrocks"]\n',
            )
            self.assertFalse(rp.item_definition_path("ruby_sword").exists())

            # second run: nothing overwritten
            rp.item_definition_path("mr_electrocks").write_text("custom")
            res2 = gen.generate_items(rp, dp, ["mr_electrocks"], opts)
            self.assertEqual(res2.summary.created, 0)
            self.assertEqual(res2.summary.skipped, 3)
            self.assertEqual(rp.item_definition_path("mr_electrocks").read_text(), "custom")

    def test_missing_texture_allowed(self):
        with tempfile.TemporaryDirectory() as t:
            rp, dp = make_packs(Path(t))
            opts = gen.GenerationOptions(namespace="customfood", allow_missing_textures=True,
                                         generate_give=False)
            res = gen.generate_items(rp, None, ["ruby_sword"], opts)
            self.assertEqual(res.summary.created, 2)
            self.assertEqual(res.summary.warnings, 1)
            self.assertFalse(any(dp.give_dir("customfood").glob("*")) if dp.give_dir("customfood").exists() else False)

    def test_mode_b(self):
        with tempfile.TemporaryDirectory() as t:
            rp, _ = make_packs(Path(t))
            rp.model_path("sword").write_text('{"keep": true}')
            (rp.models_dir / "Bad Name.json").write_text("{}")
            models, ignored = gen.list_existing_models(rp)
            self.assertEqual(models, ["sword"])
            self.assertEqual(ignored, ["Bad Name.json"])
            res = gen.generate_item_definitions(rp, ["sword"])
            self.assertEqual(res.summary.created, 1)
            self.assertEqual(rp.model_path("sword").read_text(), '{"keep": true}')

    def test_overwrite_and_rollback(self):
        with tempfile.TemporaryDirectory() as t:
            rp, dp = make_packs(Path(t))
            rp.item_definition_path("a").write_text("old")
            res = gen.generate_items(rp, dp, ["a"], gen.GenerationOptions(
                namespace="customfood", allow_missing_textures=True, overwrite=True))
            self.assertEqual(res.summary.created, 3)
            self.assertIn("minecraft:model", rp.item_definition_path("a").read_text())

            # Force a failure on the 3rd file: a directory squats on the function path.
            dp.give_function_path("customfood", "b").mkdir(parents=True)
            res = gen.generate_items(rp, dp, ["b"], gen.GenerationOptions(
                namespace="customfood", allow_missing_textures=True, overwrite=True))
            self.assertEqual(res.summary.errors, 1)
            self.assertFalse(rp.item_definition_path("b").exists())
            self.assertFalse(rp.model_path("b").exists())


class ItemModelIdTests(unittest.TestCase):
    def test_item_model_is_definition_id_not_model_path(self):
        self.assertEqual(
            gen.give_function_content("gui_accept", "minecraft:stick"),
            'give @p minecraft:stick[item_model="minecraft:gui_accept"]\n',
        )
        # model / texture paths are unchanged
        self.assertIn('"minecraft:item/gui_accept"', gen.item_definition_content("gui_accept"))
        self.assertIn('"minecraft:item/gui_accept"', gen.item_model_content("gui_accept"))


class TextComponentTests(unittest.TestCase):
    def test_gold_name(self):
        self.assertEqual(
            gen.build_give_command("sword", "minecraft:stick", "&6Ancient Sword"),
            'give @p minecraft:stick[item_model="minecraft:sword",'
            'custom_name={text:"Ancient Sword",color:"gold",italic:false}]',
        )
        self.assertEqual(
            gen.build_give_command("sword", "minecraft:stick", "&6Ancient Sword", TEXT_JSON),
            'give @p minecraft:stick[item_model="minecraft:sword",'
            'custom_name=\'{"text":"Ancient Sword","color":"gold","italic":false}\']',
        )

    def test_no_name_and_blank(self):
        for text in ("", "   ", "&6", "\x01"):
            self.assertIsNone(build_component(text))
        self.assertNotIn("custom_name", gen.build_give_command("a", "minecraft:stick", ""))

    def test_formatting_rules(self):
        comp = build_component("&6Gold &lBold&r Plain &#FF8800Hex &&amp &zz")
        extra = comp["extra"]
        self.assertEqual(extra[0], {"text": "Gold ", "color": "gold"})
        self.assertEqual(extra[1], {"text": "Bold", "color": "gold", "bold": True})
        self.assertEqual(extra[2], {"text": " Plain "})
        self.assertEqual(extra[3], {"text": "Hex &amp &zz", "color": "#ff8800"})
        self.assertEqual(len(extra), 4)   # '&&' is a literal '&', '&z' is kept as text
        # a color code resets earlier formatting (legacy behaviour)
        c2 = build_component("&lA&cB")["extra"]
        self.assertTrue(c2[0]["bold"])
        self.assertNotIn("bold", c2[1])

    def test_escaping(self):
        name = 'He said "hi" \\ it\'s'
        snbt = gen.build_give_command("a", "minecraft:stick", name)
        self.assertIn('text:"He said \\"hi\\" \\\\ it\'s"', snbt)
        js = gen.build_give_command("a", "minecraft:stick", name, TEXT_JSON)
        self.assertIn("it\\'s", js)
        self.assertIn('\\\\"hi\\\\"', js)

    def test_extra_components_preserved(self):
        cmd = gen.build_give_command("a", "minecraft:stick", "&cX", TEXT_SNBT,
                                     {"max_stack_size": "1", "item_model": "x"})
        self.assertTrue(cmd.endswith(',max_stack_size=1]'))
        self.assertEqual(cmd.count("item_model"), 1)
        with self.assertRaises(ValueError):
            gen.build_give_command("a", "minecraft:stick", "", TEXT_SNBT, {"bad key": "1"})


class DisplayFunctionTests(unittest.TestCase):
    EXPECTED = ('summon minecraft:item_display ~ ~ ~ {item:{id:"minecraft:stick",count:1,'
                'components:{"minecraft:item_model":"minecraft:andesite_greek_pillar"}},'
                'item_display:"fixed",transformation:{left_rotation:[0f,0f,0f,1f],'
                'right_rotation:[0f,0f,0f,1f],translation:[0f,0f,0f],scale:[1.0f,1.0f,1.0f]}}')

    def test_command_and_paths(self):
        self.assertEqual(gen.build_display_command("andesite_greek_pillar", "minecraft:stick"),
                         self.EXPECTED)
        with tempfile.TemporaryDirectory() as t:
            _, dp = make_packs(Path(t))
            self.assertEqual(dp.display_function_path("customfood", "x").relative_to(dp.root).as_posix(),
                             "data/customfood/function/display/x.mcfunction")

    def test_name_and_extras_match_give(self):
        cmd = gen.build_display_command("a", "minecraft:stick", "&6Sword", TEXT_SNBT, {"max_stack_size": "1"})
        self.assertIn('"minecraft:custom_name":{text:"Sword",color:"gold",italic:false}', cmd)
        self.assertIn('"minecraft:max_stack_size":1', cmd)
        js = gen.build_display_command("a", "minecraft:stick", "&6Sword", TEXT_JSON)
        self.assertIn("\"minecraft:custom_name\":'{", js)

    def test_mode_b_existing_model_and_independence(self):
        with tempfile.TemporaryDirectory() as t:
            rp, dp = make_packs(Path(t))
            rp.item_definition_path("andesite_greek_pillar").write_text("{}")   # items/ only
            models, _ = gen.list_existing_models(rp)
            self.assertEqual(models, ["andesite_greek_pillar"])
            opts = gen.GenerationOptions(namespace="customfood", generate_display=False)
            gen.generate_item_definitions(rp, ["andesite_greek_pillar"], False, dp, opts)
            self.assertEqual(dp.give_function_path("customfood", "andesite_greek_pillar").read_text(),
                             'give @p minecraft:stick[item_model="minecraft:andesite_greek_pillar"]\n')
            self.assertFalse(dp.display_function_path("customfood", "andesite_greek_pillar").exists())
            self.assertEqual(rp.item_definition_path("andesite_greek_pillar").read_text(), "{}")
            opts = gen.GenerationOptions(namespace="customfood", generate_display=True)
            gen.generate_item_definitions(rp, ["andesite_greek_pillar"], False, dp, opts)
            self.assertEqual(dp.display_function_path("customfood", "andesite_greek_pillar").read_text(),
                             self.EXPECTED + "\n")

    def test_mode_a_display_and_toggle_removes_only_display(self):
        with tempfile.TemporaryDirectory() as t:
            rp, dp = make_packs(Path(t))
            (rp.textures_dir / "ruby.png").write_bytes(b"png")
            gen.generate_items(rp, dp, ["ruby"], gen.GenerationOptions(
                namespace="customfood", generate_display=True))
            disp = dp.display_function_path("customfood", "ruby")
            give = dp.give_function_path("customfood", "ruby")
            self.assertTrue(disp.is_file() and give.is_file())
            other = dp.display_dir("customfood") / "hand_made.mcfunction"
            other.write_text("say hi\n")

            rec = ItemRecord("ruby", generate_display=False)
            res = gen.regenerate_items(dp, "customfood", {"ruby": rec}, ["ruby"], TEXT_SNBT,
                                       display_was_enabled={"ruby"})
            self.assertEqual(res.summary.errors, 0)
            self.assertFalse(disp.exists())
            self.assertTrue(give.is_file() and other.is_file())

            # re-enable regenerates it; never-generated display files are not deleted
            rec.generate_display = True
            gen.regenerate_items(dp, "customfood", {"ruby": rec}, ["ruby"], TEXT_SNBT)
            self.assertTrue(disp.is_file())
            rec.generate_display = False
            gen.regenerate_items(dp, "customfood", {"ruby": rec}, ["ruby"], TEXT_SNBT)
            self.assertTrue(disp.is_file())

    def test_store_roundtrip_flag(self):
        r = ItemRecord("a", generate_display=True)
        self.assertTrue(ItemRecord.from_dict("a", r.to_dict()).generate_display)
        self.assertNotIn("generate_display", ItemRecord("a").to_dict())


class DisplayModeScaleTests(unittest.TestCase):
    def test_all_modes_emit_exact_nbt(self):
        self.assertEqual(len(DISPLAY_MODES), 8)
        for mode in DISPLAY_MODES:
            cmd = gen.build_display_command("a", "minecraft:stick", display_mode=mode)
            self.assertIn(f'item_display:"{mode}",', cmd)
            self.assertIn("scale:[1.0f,1.0f,1.0f]", cmd)
        with self.assertRaises(ValueError):
            gen.build_display_command("a", "minecraft:stick", display_mode="bogus")

    def test_uniform_and_non_uniform_scale(self):
        uni = gen.build_display_command("a", "minecraft:stick", scale=(2, 2, 2))
        self.assertIn("scale:[2.0f,2.0f,2.0f]", uni)
        non = gen.build_display_command("a", "minecraft:stick", scale=(0.5, 1.25, 3))
        self.assertIn("scale:[0.5f,1.25f,3.0f]", non)
        self.assertTrue(non.endswith("scale:[0.5f,1.25f,3.0f]}}"))

    def test_scale_validation(self):
        self.assertEqual(parse_scale_value("1,5"), (1.5, None))
        self.assertEqual(parse_scale_value(" 2 "), (2.0, None))
        for bad in ("", "abc", "1e5", "nan", "inf", "0", "-1", "1.0f", "5000", "1.2.3"):
            self.assertIsNotNone(parse_scale_value(bad)[1], bad)
        self.assertEqual(format_snbt_float(0.1 + 0.2), "0.3f")
        self.assertEqual(format_snbt_float(100), "100.0f")
        for bad in ((1, 1), (1, 1, float("nan")), (1, 1, float("inf")), (0, 1, 1), (1, True, 1)):
            self.assertIsNotNone(check_display_settings("fixed", bad))
            with self.assertRaises(ValueError):
                gen.build_display_command("a", "minecraft:stick", scale=bad)

    def test_persisted_and_damaged_settings(self):
        r = ItemRecord("a", generate_display=True, display_mode="gui", display_scale=(1.0, 2.0, 3.0))
        back = ItemRecord.from_dict("a", json.loads(json.dumps(r.to_dict())))
        self.assertEqual((back.display_mode, back.display_scale), ("gui", (1.0, 2.0, 3.0)))
        d = ItemRecord("a").to_dict()
        self.assertNotIn("display_mode", d)
        self.assertNotIn("display_scale", d)
        bad = ItemRecord.from_dict("a", {"display_mode": "nope", "display_scale": [1, "x", 3]})
        self.assertEqual((bad.display_mode, bad.display_scale), ("fixed", (1.0, 1.0, 1.0)))
        bad = ItemRecord.from_dict("a", {"display_scale": [0, 1, 1]})
        self.assertEqual(bad.display_scale, (1.0, 1.0, 1.0))

    def test_regenerate_on_change_and_give_independent(self):
        with tempfile.TemporaryDirectory() as t:
            _, dp = make_packs(Path(t))
            rec = ItemRecord("ruby", display_name="&6Ruby", generate_display=True)
            gen.regenerate_items(dp, "customfood", {"ruby": rec}, ["ruby"], TEXT_SNBT)
            give = dp.give_function_path("customfood", "ruby")
            disp = dp.display_function_path("customfood", "ruby")
            give_before = give.read_text()
            self.assertIn('item_display:"fixed"', disp.read_text())
            rec.display_mode, rec.display_scale = "head", (2.0, 2.0, 2.0)
            res = gen.regenerate_items(dp, "customfood", {"ruby": rec}, ["ruby"], TEXT_SNBT)
            self.assertIn('item_display:"head"', disp.read_text())
            self.assertIn("scale:[2.0f,2.0f,2.0f]", disp.read_text())
            self.assertEqual(give.read_text(), give_before)      # give untouched by display settings
            self.assertIn("[SKIPPED] give/ruby.mcfunction is already up to date",
                          [str(e) for e in res.entries])
            # same item id / name as the give command
            self.assertIn('"minecraft:item_model":"minecraft:ruby"', disp.read_text())
            self.assertIn('"minecraft:custom_name":{text:"Ruby",color:"gold",italic:false}',
                          disp.read_text())

    def test_creation_uses_options_mode_and_scale(self):
        with tempfile.TemporaryDirectory() as t:
            rp, dp = make_packs(Path(t))
            rp.item_definition_path("pillar").write_text("{}")
            gen.generate_item_definitions(rp, ["pillar"], False, dp, gen.GenerationOptions(
                namespace="customfood", generate_display=True, display_mode="gui",
                display_scale=(1.0, 2.0, 1.0)))
            text = dp.display_function_path("customfood", "pillar").read_text()
            self.assertIn('item_display:"gui"', text)
            self.assertIn("scale:[1.0f,2.0f,1.0f]", text)


def records_for(*items):
    return {r.name: r for r in items}


class RecipeTests(unittest.TestCase):
    def setUp(self):
        self.ruby = ItemRecord("ruby", display_name="&cRuby")
        self.sword = ItemRecord("ruby_sword", display_name="&6Ancient Sword")
        self.recs = records_for(self.ruby, self.sword)

    def test_shaped_trim_and_keys(self):
        r = Recipe(kind="shaped", recipe_id="ruby_sword", output="custom:ruby_sword", count=2,
                   slots=["", "minecraft:diamond", "", "", "minecraft:diamond", "",
                          "", "minecraft:stick", ""])
        data = build_recipe_json(r, self.recs)
        self.assertEqual(data["type"], "minecraft:crafting_shaped")
        self.assertEqual(data["pattern"], ["A", "A", "B"])
        self.assertEqual(data["key"], {"A": "minecraft:diamond", "B": "minecraft:stick"})
        self.assertEqual(data["result"], {
            "id": "minecraft:stick", "count": 2,
            "components": {
                "minecraft:item_model": "minecraft:ruby_sword",
                "minecraft:custom_name": {"text": "Ancient Sword", "color": "gold", "italic": False},
            }})

    def test_shaped_keeps_gaps(self):
        r = Recipe(recipe_id="x", output="minecraft:diamond",
                   slots=["#minecraft:planks", "", "#minecraft:planks", "", "", "", "", "", ""])
        data = build_recipe_json(r, self.recs)
        self.assertEqual(data["pattern"], ["A A"])
        self.assertEqual(data["key"], {"A": "#minecraft:planks"})
        self.assertEqual(data["result"], {"id": "minecraft:diamond", "count": 1})

    def test_shapeless(self):
        r = Recipe(kind="shapeless", recipe_id="x", output="custom:ruby_sword",
                   slots=["minecraft:diamond", "", "", "minecraft:diamond", "", "", "minecraft:stick", "", ""])
        data = build_recipe_json(r, self.recs)
        self.assertEqual(data["type"], "minecraft:crafting_shapeless")
        self.assertEqual(data["ingredients"], ["minecraft:diamond", "minecraft:diamond", "minecraft:stick"])

    def test_custom_ingredient_warns_and_maps_to_base(self):
        r = Recipe(recipe_id="x", output="custom:ruby_sword",
                   slots=["custom:ruby"] + [""] * 8)
        check = validate_recipe(r, self.recs)
        self.assertTrue(check.ok)
        self.assertEqual(len(check.warnings), 1)
        self.assertEqual(build_recipe_json(r, self.recs)["key"], {"A": "minecraft:stick"})

    def test_validation_errors(self):
        bad = [
            Recipe(recipe_id="x", output="minecraft:stone"),                       # no ingredients
            Recipe(recipe_id="", output="minecraft:stone", slots=["minecraft:dirt"] + [""] * 8),
            Recipe(recipe_id="Bad Id", output="minecraft:stone", slots=["minecraft:dirt"] + [""] * 8),
            Recipe(recipe_id="x", output="", slots=["minecraft:dirt"] + [""] * 8),
            Recipe(recipe_id="x", output="custom:nope", slots=["minecraft:dirt"] + [""] * 8),
            Recipe(recipe_id="x", output="minecraft:stone", count=0, slots=["minecraft:dirt"] + [""] * 8),
            Recipe(recipe_id="x", output="minecraft:stone", slots=["not valid!"] + [""] * 8),
            Recipe(recipe_id="x", output="minecraft:stone", slots=["custom:nope"] + [""] * 8),
        ]
        for r in bad:
            self.assertFalse(validate_recipe(r, self.recs).ok, r)
            with self.assertRaises(ValueError):
                build_recipe_json(r, self.recs)

    def test_normalize(self):
        self.assertEqual(normalize_ingredient(" Diamond "), "minecraft:diamond")
        self.assertEqual(normalize_ingredient("#planks"), "#minecraft:planks")
        self.assertEqual(normalize_ingredient(""), "")


class StoreAndRegenerationTests(unittest.TestCase):
    def test_store_roundtrip_and_corrupt_protection(self):
        with tempfile.TemporaryDirectory() as t:
            path = Path(t) / STORE_FILENAME
            store = ProjectStore(path)
            rec = ItemRecord("a", display_name="&6A", extra_components={"max_stack_size": "1"},
                             recipe=Recipe(recipe_id="a", output="custom:a",
                                           slots=["minecraft:stick"] + [""] * 8))
            store.put("customfood", rec)
            store.text_format = TEXT_JSON
            store.save()
            again = ProjectStore.load(path)
            self.assertEqual(again.text_format, TEXT_JSON)
            got = again.items("customfood")["a"]
            self.assertEqual(got.to_dict(), rec.to_dict())

            path.write_text("{not json")
            bad = ProjectStore.load(path)
            self.assertIsNotNone(bad.read_error)
            with self.assertRaises(StoreError):
                bad.save()
            self.assertEqual(path.read_text(), "{not json")   # untouched

    def test_old_broken_function_is_repaired_and_base_recovered(self):
        with tempfile.TemporaryDirectory() as t:
            rp, dp = make_packs(Path(t))
            old = dp.give_function_path("customfood", "gui_accept")
            old.parent.mkdir(parents=True)
            old.write_text('give @p minecraft:paper[item_model="minecraft:item/gui_accept"]\n')
            records = gen.collect_records(dp, "customfood", {}, "minecraft:stick")
            self.assertEqual(records["gui_accept"].base_item, "minecraft:paper")
            res = gen.regenerate_items(dp, "customfood", records, ["gui_accept"], TEXT_SNBT)
            self.assertEqual(res.summary.errors, 0)
            self.assertEqual(old.read_text(),
                             'give @p minecraft:paper[item_model="minecraft:gui_accept"]\n')
            # second run: already up to date
            res = gen.regenerate_items(dp, "customfood", records, ["gui_accept"], TEXT_SNBT)
            self.assertEqual(res.summary.created, 0)
            self.assertEqual(res.summary.skipped, 1)

    def test_rename_regenerates_function_and_recipes(self):
        with tempfile.TemporaryDirectory() as t:
            rp, dp = make_packs(Path(t))
            unrelated = dp.root / "data/customfood/recipe/other.json"
            unrelated.parent.mkdir(parents=True)
            unrelated.write_text("{}")
            sword = ItemRecord("ruby_sword", display_name="&6Old",
                               recipe=Recipe(recipe_id="ruby_sword", output="custom:ruby_sword",
                                             slots=["minecraft:diamond"] + [""] * 8))
            gem = ItemRecord("gem", recipe=Recipe(recipe_id="gem_to_sword", kind="shapeless",
                                                   output="custom:ruby_sword",
                                                   slots=["minecraft:ruby"] + [""] * 8))
            recs = records_for(sword, gem)
            gen.regenerate_items(dp, "customfood", recs, ["ruby_sword", "gem"], TEXT_SNBT)
            recipe_path = dp.recipe_file("customfood", "ruby_sword")
            other_path = dp.recipe_file("customfood", "gem_to_sword")
            self.assertIn('"text": "Old"', recipe_path.read_text())

            sword.display_name = "&bNew Name"
            res = gen.regenerate_items(dp, "customfood", recs, ["ruby_sword"], TEXT_SNBT)
            self.assertEqual(res.summary.errors, 0)
            for p in (recipe_path, other_path):     # recipe owned AND recipe producing the item
                self.assertIn('"text": "New Name"', p.read_text())
                self.assertIn('"color": "aqua"', p.read_text())
            self.assertIn('text:"New Name"', dp.give_function_path("customfood", "ruby_sword").read_text())
            self.assertEqual(unrelated.read_text(), "{}")

    def test_invalid_recipe_blocks_everything(self):
        with tempfile.TemporaryDirectory() as t:
            rp, dp = make_packs(Path(t))
            bad = ItemRecord("a", recipe=Recipe(recipe_id="a", output="custom:a"))   # no ingredients
            res = gen.regenerate_items(dp, "customfood", records_for(bad), ["a"], TEXT_SNBT)
            self.assertGreater(res.summary.errors, 0)
            self.assertFalse(dp.give_function_path("customfood", "a").exists())

    def test_rollback_on_failure(self):
        with tempfile.TemporaryDirectory() as t:
            rp, dp = make_packs(Path(t))
            rec = ItemRecord("a", recipe=Recipe(recipe_id="a", output="custom:a",
                                                slots=["minecraft:stick"] + [""] * 8))
            dp.recipe_file("customfood", "a").mkdir(parents=True)      # recipe path blocked
            res = gen.regenerate_items(dp, "customfood", records_for(rec), ["a"], TEXT_SNBT)
            self.assertGreater(res.summary.errors, 0)
            self.assertFalse(dp.give_function_path("customfood", "a").exists())


if __name__ == "__main__":
    unittest.main()
