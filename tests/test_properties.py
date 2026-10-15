"""Lore, stack size, glint and other item components (core only, no Qt).

Run with:  python -m unittest discover -s tests   (from the project root).

Generated commands are checked by parsing them back with a small independent SNBT reader,
so escaping and structure are verified by round-trip, not by comparing strings.
"""
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import generator as gen  # noqa: E402
from core.attributes import (  # noqa: E402
    MAX_ATTRIBUTES, AttributeModifier, attribute_label, check_attributes, enchantment_label,
    format_double,
)
from core.components import MAX_LORE_LINES, ItemProperties  # noqa: E402
from core.snbt import SnbtError, check_compound, parse_compound  # noqa: E402
from core.tooltip import build_tooltip, effective_rarity, format_number, item_traits  # noqa: E402
from core.format_codes import (  # noqa: E402
    COLOR_REFERENCE, FORMAT_REFERENCE, code_snippet, contrast_text_color, hex_code, plan_insert,
)
from core.item_rules import item_facts, validate_stack_size  # noqa: E402
from core.items import STORE_FILENAME, ItemRecord, ProjectStore  # noqa: E402
from core.project_paths import DatapackPaths  # noqa: E402
from core.recipes import Recipe, build_recipe_json  # noqa: E402
from core.text_components import (  # noqa: E402
    TEXT_JSON, TEXT_SNBT, build_component, build_lore_line, find_unknown_codes, parse_legacy,
)


# ------------------------------------------------------------ tiny SNBT reader
class _Snbt:
    """Just enough SNBT to read what this tool writes: compounds, lists, quoted strings,
    booleans and numbers. Raises ValueError on anything malformed."""

    def __init__(self, text: str) -> None:
        self.t, self.i = text, 0

    def parse(self):
        value = self.value()
        if self.i != len(self.t):
            raise ValueError(f"trailing text at {self.i}: {self.t[self.i:self.i + 20]!r}")
        return value

    def value(self):
        c = self.t[self.i]
        if c == "{":
            return self.compound()
        if c == "[":
            return self.list_()
        if c in "\"'":
            return self.string()
        m = re.compile(r"[A-Za-z0-9_.+-]+").match(self.t, self.i)
        if not m:
            raise ValueError(f"unexpected {c!r} at {self.i}")
        self.i = m.end()
        word = m.group()
        if word in ("true", "false"):
            return word == "true"
        return word            # numbers/identifiers are compared as text (e.g. "16", "1.0f")

    def string(self) -> str:
        quote = self.t[self.i]
        self.i += 1
        out = []
        while True:
            c = self.t[self.i]
            if c == "\\":
                out.append(self.t[self.i + 1])
                self.i += 2
            elif c == quote:
                self.i += 1
                return "".join(out)
            else:
                out.append(c)
                self.i += 1

    def key(self) -> str:
        if self.t[self.i] in "\"'":
            return self.string()
        m = re.compile(r"[A-Za-z0-9_.+-]+").match(self.t, self.i)
        self.i = m.end()
        return m.group()

    def compound(self) -> dict:
        self.i += 1
        out = {}
        while self.t[self.i] != "}":
            k = self.key()
            if self.t[self.i] != ":":
                raise ValueError(f"expected ':' at {self.i}")
            self.i += 1
            out[k] = self.value()
            if self.t[self.i] == ",":
                self.i += 1
        self.i += 1
        return out

    def list_(self) -> list:
        self.i += 1
        out = []
        while self.t[self.i] != "]":
            out.append(self.value())
            if self.t[self.i] == ",":
                self.i += 1
        self.i += 1
        return out


def parse_give(command: str):
    """'give @p <id>[k=v,...]' -> (id, {k: parsed value})."""
    m = re.fullmatch(r"give @p (\S+?)\[(.*)\]", command, re.S)
    assert m, command
    reader = _Snbt(m.group(2))
    comps = {}
    while reader.i < len(reader.t):
        k = re.compile(r"[a-z0-9_.:/-]+").match(reader.t, reader.i)
        reader.i = k.end()
        assert reader.t[reader.i] == "=", command
        reader.i += 1
        comps[k.group()] = reader.value()
        if reader.i < len(reader.t):
            assert reader.t[reader.i] == ",", command
            reader.i += 1
    return m.group(1), comps


def lore_of(comps, text_format):
    """Lore components as dicts, whichever way the target version writes them."""
    lines = comps["lore"]
    if text_format == TEXT_JSON:
        return [json.loads(line) for line in lines]        # each line is a JSON string
    return lines


NASTY = [
    'He said "hi"',
    "back\\slash and it's",
    "ünïcödé \u2605 \U0001F525 emoji",
    "",
    "   leading and trailing   ",
    "&6Gold &lbold&r plain &#33ccff hex &&amp",
    "$not a macro # not a comment",
    "'",
    '"',
    "\\",
]


class LoreSyntaxTests(unittest.TestCase):
    def check_lore(self, text_format):
        props = ItemProperties(lore=tuple(NASTY))
        cmd = gen.build_give_command("ruby", "minecraft:stick", "&6Ruby", text_format, None, props)
        self.assertEqual(cmd.count("\n"), 0)              # one command, one line
        item, comps = parse_give(cmd)
        self.assertEqual(item, "minecraft:stick")
        got = lore_of(comps, text_format)
        expected = [build_lore_line(line) for line in NASTY]
        self.assertEqual(len(got), len(NASTY))
        for line, g, e in zip(NASTY, got, expected):
            if text_format == TEXT_JSON:
                self.assertEqual(g, e, line)             # real JSON, parsed back equal
            else:
                self.assertEqual(flatten(g), flatten(e), line)

    def test_lore_roundtrip_snbt(self):
        self.check_lore(TEXT_SNBT)

    def test_lore_roundtrip_json_strings(self):
        self.check_lore(TEXT_JSON)

    def test_lore_text_survives_exactly(self):
        # what the player reads equals what was typed (minus codes), spaces included
        for fmt in (TEXT_SNBT, TEXT_JSON):
            cmd = gen.build_give_command("a", "minecraft:stick", "", fmt, None,
                                         ItemProperties(lore=('  say "x" \\ it\'s  ',)))
            _item, comps = parse_give(cmd)
            comp = lore_of(comps, fmt)[0]
            self.assertEqual(flatten_text(comp), '  say "x" \\ it\'s  ')

    def test_blank_and_formatted_lines(self):
        self.assertEqual(build_lore_line(""), {"text": "", "italic": False})
        self.assertEqual(build_lore_line("&6"), {"text": "", "italic": False})   # code only
        self.assertEqual(build_lore_line("&7Hi"), {"text": "Hi", "color": "gray", "italic": False})
        self.assertEqual(build_lore_line("&oSlanted"), {"text": "Slanted", "italic": True})
        multi = build_lore_line("&cA&lB")
        self.assertEqual(multi["extra"][1], {"text": "B", "color": "red", "bold": True})
        self.assertFalse(multi["italic"])

    def test_spaces_are_kept_in_lore_but_not_in_names(self):
        self.assertEqual(parse_legacy("  x  ", strip=False)[0].text, "  x  ")
        self.assertEqual(parse_legacy("  x  ")[0].text, "x")

    def test_unknown_codes_are_found(self):
        self.assertEqual(find_unknown_codes("&6ok &zbad &#12 &&lit &lbold &"), ["&z", "&#"])
        self.assertEqual(find_unknown_codes("&#33ccff fine &r &k"), [])

    def test_lore_limit(self):
        props = ItemProperties(lore=("x",) * (MAX_LORE_LINES + 1))
        plan = gen.analyze_item("a", "minecraft:stick", "", TEXT_SNBT, None, props)
        self.assertTrue(any("256" in e for e in plan.errors))
        with self.assertRaises(ValueError):
            gen.build_give_command("a", "minecraft:stick", "", TEXT_SNBT, None, props)
        ok = ItemProperties(lore=("x",) * MAX_LORE_LINES)
        self.assertFalse(gen.analyze_item("a", "minecraft:stick", "", TEXT_SNBT, None, ok).errors)


def flatten(comp):
    """Normalise a parsed component for comparison (SNBT reader returns text for numbers)."""
    return json.loads(json.dumps(comp))


def flatten_text(comp) -> str:
    out = comp.get("text", "")
    for part in comp.get("extra", []):
        out += flatten_text(part)
    return out


class ComponentTests(unittest.TestCase):
    PROPS = ItemProperties(
        lore=("&7Line",), max_stack_size=16, glint=True, rarity="epic", unbreakable=True,
        hide_tooltip=True)

    def test_all_components_snbt(self):
        _i, c = parse_give(gen.build_give_command(
            "ruby", "minecraft:ender_pearl", "&6Ruby", TEXT_SNBT, None, self.PROPS))
        self.assertEqual(c["item_model"], "minecraft:ruby")
        self.assertEqual(c["max_stack_size"], "16")
        self.assertIs(c["enchantment_glint_override"], True)
        self.assertEqual(c["rarity"], "epic")
        self.assertEqual(c["unbreakable"], {})
        self.assertEqual(c["tooltip_display"], {"hide_tooltip": True})
        self.assertNotIn("hide_tooltip", c)

    def test_hide_tooltip_syntax_follows_version(self):
        _i, old = parse_give(gen.build_give_command(
            "r", "minecraft:stick", "", TEXT_JSON, None, ItemProperties(hide_tooltip=True)))
        self.assertEqual(old["hide_tooltip"], {})
        self.assertNotIn("tooltip_display", old)

    def test_defaults_write_nothing_new(self):
        cmd = gen.build_give_command("a", "minecraft:stick", "", TEXT_SNBT, None, ItemProperties())
        self.assertEqual(cmd, 'give @p minecraft:stick[item_model="minecraft:a"]')

    def test_display_function_has_same_components(self):
        text = gen.build_display_command("ruby", "minecraft:ender_pearl", "&6Ruby", TEXT_SNBT,
                                         None, "fixed", (1, 1, 1), self.PROPS)
        m = re.search(r"components:(\{.*\})\},item_display:", text)
        comps = _Snbt(m.group(1)).parse()
        for key in ("item_model", "custom_name", "lore", "max_stack_size",
                    "enchantment_glint_override", "rarity", "unbreakable", "tooltip_display"):
            self.assertIn(f"minecraft:{key}", comps)
        self.assertIn("scale:[1.0f,1.0f,1.0f]", text)

    def test_component_order_is_stable(self):
        _i, c = parse_give(gen.build_give_command(
            "r", "minecraft:ender_pearl", "x", TEXT_SNBT, None, self.PROPS))
        self.assertEqual(list(c), ["item_model", "custom_name", "lore", "max_stack_size",
                                   "enchantment_glint_override", "rarity", "unbreakable",
                                   "tooltip_display"])

    def test_bad_rarity_is_an_error(self):
        plan = gen.analyze_item("a", "minecraft:stick", "", TEXT_SNBT, None,
                                ItemProperties(rarity="mythic"))
        self.assertTrue(plan.errors)


class StackSizeTests(unittest.TestCase):
    def test_range_and_type(self):
        for bad in (0, 100, -1, 1000, True, "5", 2.5):
            errors, _ = validate_stack_size("minecraft:stick", bad)
            self.assertTrue(errors, bad)
        for good in (1, 2, 16, 64, 99):
            self.assertEqual(validate_stack_size("minecraft:stick", good), ([], []))
        self.assertEqual(validate_stack_size("minecraft:stick", None), ([], []))

    def test_damageable_items_cannot_stack(self):
        for item in ("minecraft:diamond_sword", "minecraft:iron_chestplate", "minecraft:bow",
                     "minecraft:shears", "minecraft:elytra", "minecraft:wooden_pickaxe"):
            self.assertTrue(item_facts(item).damageable, item)
            errors, _ = validate_stack_size(item, 2)
            self.assertTrue(errors, item)
            self.assertEqual(validate_stack_size(item, 1), ([], []))    # 1 is fine

    def test_unknown_items_are_reported_not_guessed(self):
        _e, warnings = validate_stack_size("othermod:gizmo", 8)
        self.assertEqual(len(warnings), 1)
        self.assertEqual(validate_stack_size("othermod:gizmo", 1), ([], []))
        self.assertEqual(validate_stack_size("minecraft:stick", 8), ([], []))

    def test_default_sizes(self):
        self.assertEqual(item_facts("minecraft:stick").default_stack, 64)
        self.assertEqual(item_facts("minecraft:ender_pearl").default_stack, 16)
        self.assertEqual(item_facts("minecraft:oak_sign").default_stack, 16)
        self.assertEqual(item_facts("minecraft:water_bucket").default_stack, 1)
        self.assertEqual(item_facts("minecraft:bucket").default_stack, 16)

    def test_blocks_command_generation(self):
        with self.assertRaises(ValueError):
            gen.build_give_command("a", "minecraft:diamond_sword", "", TEXT_SNBT, None,
                                   ItemProperties(max_stack_size=8))


class ExtraComponentTests(unittest.TestCase):
    def test_unsupported_for_target_are_reported_and_left_out(self):
        extras = {"hide_tooltip": "{}", "fire_resistant": "{}", "custom_model_data": "{}"}
        plan = gen.analyze_item("a", "minecraft:stick", "", TEXT_SNBT, extras, None)
        self.assertEqual(len(plan.warnings), 2)
        self.assertTrue(any("hide_tooltip" in w for w in plan.warnings))
        self.assertTrue(any("fire_resistant" in w for w in plan.warnings))
        keys = [k for k, _v in plan.entries]
        self.assertIn("custom_model_data", keys)             # unknown ones pass through
        self.assertNotIn("hide_tooltip", keys)
        # the same extra IS valid on 1.21.4
        old = gen.analyze_item("a", "minecraft:stick", "", TEXT_JSON, {"hide_tooltip": "{}"}, None)
        self.assertEqual(old.warnings, [])
        self.assertIn("hide_tooltip", [k for k, _v in old.entries])

    def test_extra_is_overridden_by_editor_value_with_warning(self):
        plan = gen.analyze_item("a", "minecraft:stick", "", TEXT_SNBT, {"max_stack_size": "1"},
                                ItemProperties(max_stack_size=5))
        self.assertEqual([v for k, v in plan.entries if k == "max_stack_size"], ["5"])
        self.assertTrue(any("max_stack_size" in w for w in plan.warnings))

    def test_extra_used_verbatim_when_editor_value_unset(self):
        plan = gen.analyze_item("a", "minecraft:stick", "", TEXT_SNBT, {"max_stack_size": "1"}, None)
        self.assertEqual(plan.warnings, [])
        self.assertEqual(plan.entries[-1], ("max_stack_size", "1"))

    def test_generated_components_in_extras_are_reported(self):
        plan = gen.analyze_item("a", "minecraft:stick", "", TEXT_SNBT, {"item_model": "x"}, None)
        self.assertEqual(len(plan.warnings), 1)

    def test_invalid_extra_key_is_an_error(self):
        plan = gen.analyze_item("a", "minecraft:stick", "", TEXT_SNBT, {"bad key": "1"}, None)
        self.assertTrue(plan.errors)


class StoreTests(unittest.TestCase):
    def test_roundtrip_all_properties(self):
        with tempfile.TemporaryDirectory() as t:
            path = Path(t) / STORE_FILENAME
            store = ProjectStore(path)
            rec = ItemRecord("ruby", base_item="minecraft:ender_pearl", display_name="&6Ruby",
                             lore=["&7a", "", "  b \"q\""], max_stack_size=8, glint=True,
                             rarity="rare", unbreakable=True, hide_tooltip=True)
            store.put("ns", rec)
            store.save()
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["version"], 2)
            stored = data["namespaces"]["ns"]["items"]["ruby"]
            self.assertEqual(stored["lore"], ["&7a", "", "  b \"q\""])
            self.assertEqual(stored["max_stack_size"], 8)
            again = ProjectStore.load(path).items("ns")["ruby"]
            self.assertEqual(again.to_dict(), rec.to_dict())
            self.assertEqual(again.properties(), rec.properties())

    def test_defaults_are_not_written_and_old_format_stays_v1(self):
        with tempfile.TemporaryDirectory() as t:
            path = Path(t) / STORE_FILENAME
            store = ProjectStore(path)
            store.put("ns", ItemRecord("a", display_name="&6A"))
            store.save()
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["version"], 1)         # still readable by older builds
            self.assertEqual(set(data["namespaces"]["ns"]["items"]["a"]), {"base_item", "display_name"})

    def test_old_file_loads_without_new_fields(self):
        with tempfile.TemporaryDirectory() as t:
            path = Path(t) / STORE_FILENAME
            path.write_text(json.dumps({"version": 1, "namespaces": {"ns": {"items": {
                "a": {"base_item": "minecraft:stick", "display_name": "&6A"}}}}}))
            store = ProjectStore.load(path)
            self.assertEqual(store.warnings, [])
            rec = store.items("ns")["a"]
            self.assertEqual((rec.lore, rec.max_stack_size, rec.glint), ([], None, False))

    def test_newer_version_is_refused_not_overwritten(self):
        with tempfile.TemporaryDirectory() as t:
            path = Path(t) / STORE_FILENAME
            path.write_text(json.dumps({"version": 99, "namespaces": {}}))
            store = ProjectStore.load(path)
            self.assertIsNotNone(store.read_error)

    def test_unusable_stored_values_are_reported(self):
        with tempfile.TemporaryDirectory() as t:
            path = Path(t) / STORE_FILENAME
            path.write_text(json.dumps({"version": 2, "namespaces": {"ns": {"items": {"a": {
                "lore": "not a list", "max_stack_size": 500, "rarity": "mythic", "glint": True}}}}}))
            store = ProjectStore.load(path)
            self.assertEqual(len(store.warnings), 3)
            rec = store.items("ns")["a"]
            self.assertEqual((rec.lore, rec.max_stack_size, rec.rarity, rec.glint), ([], None, "", True))


def make_dp(tmp: Path) -> DatapackPaths:
    dp = tmp / "dp"
    (dp / "data/ns/function/give").mkdir(parents=True)
    (dp / "pack.mcmeta").write_text("{}")
    return DatapackPaths(dp)


class GenerationTests(unittest.TestCase):
    def records(self):
        ruby = ItemRecord("ruby", base_item="minecraft:ender_pearl", display_name="&6Ruby",
                          lore=["&7Forged \"in\" fire", "", "&cHot"], max_stack_size=8, glint=True,
                          hide_tooltip=True, generate_display=True,
                          extra_components={"fire_resistant": "{}"},
                          recipe=Recipe(recipe_id="ruby", output="custom:ruby", count=2,
                                        slots=["minecraft:diamond"] + [""] * 8, kind="shapeless"))
        return {"ruby": ruby}

    def test_regenerate_writes_everything_and_reports_unsupported(self):
        with tempfile.TemporaryDirectory() as t:
            dp = make_dp(Path(t))
            result = gen.regenerate_items(dp, "ns", self.records(), ["ruby"], TEXT_SNBT)
            self.assertEqual(result.summary.errors, 0)
            self.assertEqual(result.summary.warnings, 1)
            self.assertIn("fire_resistant", str(result.entries))
            give = dp.give_function_path("ns", "ruby").read_text(encoding="utf-8")
            _i, comps = parse_give(give.rstrip("\n"))
            self.assertEqual(len(comps["lore"]), 3)
            self.assertEqual(comps["max_stack_size"], "8")
            self.assertNotIn("fire_resistant", give)
            disp = dp.display_function_path("ns", "ruby").read_text(encoding="utf-8")
            self.assertIn('"minecraft:lore"', disp)
            self.assertEqual(give.count("\n"), 1)
            recipe = json.loads(dp.recipe_file("ns", "ruby").read_text(encoding="utf-8"))
            res = recipe["result"]["components"]
            self.assertEqual(res["minecraft:max_stack_size"], 8)
            self.assertEqual(res["minecraft:lore"][0], build_lore_line("&7Forged \"in\" fire"))
            self.assertEqual(res["minecraft:tooltip_display"], {"hide_tooltip": True})
            self.assertEqual(res["minecraft:item_model"], "minecraft:ruby")
            self.assertEqual(res["minecraft:custom_name"], build_component("&6Ruby"))

    def test_recipe_result_follows_target_version(self):
        recs = self.records()
        old = build_recipe_json(recs["ruby"].recipe, recs, TEXT_JSON)["result"]["components"]
        self.assertEqual(old["minecraft:hide_tooltip"], {})
        self.assertNotIn("minecraft:tooltip_display", old)

    def test_invalid_item_blocks_all_writes(self):
        with tempfile.TemporaryDirectory() as t:
            dp = make_dp(Path(t))
            recs = {"sword": ItemRecord("sword", base_item="minecraft:diamond_sword",
                                        max_stack_size=4)}
            result = gen.regenerate_items(dp, "ns", recs, ["sword"], TEXT_SNBT)
            self.assertEqual(result.summary.errors, 1)
            self.assertFalse(dp.give_function_path("ns", "sword").exists())

    def test_recipe_for_invalid_custom_result_is_an_error_not_a_crash(self):
        with tempfile.TemporaryDirectory() as t:
            dp = make_dp(Path(t))
            recs = self.records()
            recs["ruby"].base_item = "minecraft:diamond_sword"     # 8 is illegal on a sword
            result = gen.regenerate_items(dp, "ns", recs, ["ruby"], TEXT_SNBT)
            self.assertGreaterEqual(result.summary.errors, 1)
            self.assertFalse(dp.give_function_path("ns", "ruby").exists())

    def test_item_warnings_helper(self):
        warnings = gen.item_warnings(self.records(), ["ruby", "missing"], TEXT_SNBT)
        self.assertEqual(len(warnings), 1)
        # fire_resistant was removed in 1.21.2, so it is unsupported on both targets
        self.assertEqual(len(gen.item_warnings(self.records(), ["ruby"], TEXT_JSON)), 1)


class FormatCodeTests(unittest.TestCase):
    def test_reference_is_complete(self):
        codes = [c.code for c in COLOR_REFERENCE] + [c.code for c in FORMAT_REFERENCE]
        self.assertEqual("".join(codes), "0123456789abcdefklmnor")
        by = {c.code: c for c in COLOR_REFERENCE}
        self.assertEqual((by["7"].label, by["7"].hex), ("Gray", "#AAAAAA"))
        self.assertEqual((by["f"].label, by["f"].hex), ("White", "#FFFFFF"))
        labels = {c.code: c.label for c in FORMAT_REFERENCE}
        self.assertEqual(labels, {"k": "Obfuscated", "l": "Bold", "m": "Strikethrough",
                                  "n": "Underline", "o": "Italic", "r": "Reset"})

    def test_contrast_and_hex(self):
        self.assertEqual(contrast_text_color("#000000"), "#FFFFFF")
        self.assertEqual(contrast_text_color("#FFFFFF"), "#000000")
        self.assertEqual(hex_code("#FF8800"), "&#ff8800")

    def test_snippet_follows_version(self):
        self.assertEqual(code_snippet("6", TEXT_SNBT), '{text:"Text",color:"gold",italic:false}')
        self.assertEqual(code_snippet("6", TEXT_JSON),
                         "'{\"text\":\"Text\",\"color\":\"gold\",\"italic\":false}'")
        self.assertIn("bold:true", code_snippet("l", TEXT_SNBT))

    def test_every_code_parses_to_the_documented_style(self):
        names = ["black", "dark_blue", "dark_green", "dark_aqua", "dark_red", "dark_purple",
                 "gold", "gray", "dark_gray", "blue", "green", "aqua", "red", "light_purple",
                 "yellow", "white"]
        for code, name in zip("0123456789abcdef", names):
            self.assertEqual(parse_legacy(f"&{code}x")[0].color, name, code)
        flags = {"k": "obfuscated", "l": "bold", "m": "strikethrough", "n": "underlined",
                 "o": "italic"}
        for code, flag in flags.items():
            self.assertTrue(getattr(parse_legacy(f"&{code}x")[0], flag), code)
        self.assertEqual(parse_legacy("&l&rx")[0].bold, False)          # reset

    def test_plan_insert(self):
        # no selection: caret moves behind the code
        self.assertEqual(plan_insert(3, 3, 2), (5, 5))
        # caret at the end of a selection [1, 4]: selection unchanged
        self.assertEqual(plan_insert(4, 1, 2), (4, 1))
        # caret at the start of a selection [1, 4]: selection moves with its text
        self.assertEqual(plan_insert(1, 4, 2), (3, 6))


A = AttributeModifier


class AttributeEnchantmentTests(unittest.TestCase):
    ATTRS = (A("minecraft:attack_damage", 7, "add_value", "mainhand"),
             A("minecraft:movement_speed", 0.1, "add_multiplied_base", "feet"),
             A("example:custom_attr", -2.5, "add_multiplied_total", "any"))
    ENCH = (("minecraft:sharpness", 5), ("minecraft:mending", 1))

    def command(self, fmt, **kw):
        props = ItemProperties(attributes=self.ATTRS, enchantments=self.ENCH, **kw)
        return parse_give(gen.build_give_command("ruby", "minecraft:stick", "", fmt, None, props))[1]

    def check_entries(self, entries):
        self.assertEqual(len(entries), 3)
        ids = [e["id"] for e in entries]
        self.assertEqual(len(set(ids)), 3)                               # unique per modifier
        for e in entries:
            self.assertRegex(e["id"], r"^minecraft:[a-z0-9_./-]+$")
        first = entries[0]
        self.assertEqual((first["type"], first["amount"], first["operation"], first["slot"]),
                         ("minecraft:attack_damage", "7.0d", "add_value", "mainhand"))
        self.assertEqual(entries[1]["amount"], "0.1d")
        self.assertEqual(entries[2]["amount"], "-2.5d")
        self.assertEqual(entries[2]["type"], "example:custom_attr")

    def test_syntax_1_21_5_plus(self):
        c = self.command(TEXT_SNBT)
        self.check_entries(c["attribute_modifiers"])                      # a plain list
        self.assertEqual(c["enchantments"], {"minecraft:sharpness": "5", "minecraft:mending": "1"})

    def test_syntax_1_21_4(self):
        c = self.command(TEXT_JSON)
        self.check_entries(c["attribute_modifiers"]["modifiers"])         # wrapped in a record
        self.assertEqual(c["enchantments"]["levels"],
                         {"minecraft:sharpness": "5", "minecraft:mending": "1"})

    def test_recipe_json_follows_version(self):
        rec = ItemRecord("ruby", base_item="minecraft:stick", attributes=list(self.ATTRS),
                         enchantments=list(self.ENCH), fire_resistant=True, max_damage=10,
                         max_stack_size=1,
                         recipe=Recipe(recipe_id="ruby", output="custom:ruby", count=1,
                                       slots=["minecraft:diamond"] + [""] * 8, kind="shapeless"))
        recs = {"ruby": rec}
        new = build_recipe_json(rec.recipe, recs, TEXT_SNBT)["result"]["components"]
        old = build_recipe_json(rec.recipe, recs, TEXT_JSON)["result"]["components"]
        self.assertEqual(new["minecraft:enchantments"], {"minecraft:sharpness": 5, "minecraft:mending": 1})
        self.assertEqual(old["minecraft:enchantments"], {"levels": new["minecraft:enchantments"]})
        self.assertEqual(new["minecraft:attribute_modifiers"][0]["amount"], 7.0)
        self.assertEqual(old["minecraft:attribute_modifiers"], {"modifiers": new["minecraft:attribute_modifiers"]})
        self.assertEqual(new["minecraft:max_damage"], 10)
        self.assertEqual(new["minecraft:damage_resistant"], {"types": "#minecraft:is_fire"})
        # the command and the recipe carry the same modifier ids
        c = parse_give(gen.build_give_command("ruby", "minecraft:stick", "", TEXT_SNBT, None,
                                              rec.properties()))[1]
        self.assertEqual([e["id"] for e in c["attribute_modifiers"]],
                         [e["id"] for e in new["minecraft:attribute_modifiers"]])

    def test_display_function_has_them_too(self):
        text = gen.build_display_command("ruby", "minecraft:stick", "", TEXT_SNBT, None, "fixed",
                                         (1, 1, 1), ItemProperties(attributes=self.ATTRS,
                                                                   enchantments=self.ENCH))
        comps = _Snbt(re.search(r"components:(\{.*\})\},item_display:", text).group(1)).parse()
        self.assertEqual(len(comps["minecraft:attribute_modifiers"]), 3)
        self.assertIn("minecraft:enchantments", comps)

    def test_attribute_validation(self):
        legacy = check_attributes([A("minecraft:generic.attack_damage", 1)])[0]
        self.assertEqual(len(legacy), 1)
        self.assertIn("minecraft:attack_damage", legacy[0])               # suggests the new name
        self.assertTrue(check_attributes([A("minecraft:player.block_interaction_range", 1)])[0])
        self.assertTrue(check_attributes([A("Attack Damage", 1)])[0])      # not an id
        self.assertTrue(check_attributes([A("minecraft:armor", 1, "multiply")])[0])
        self.assertTrue(check_attributes([A("minecraft:armor", 1, "add_value", "thumb")])[0])
        self.assertTrue(check_attributes([A("minecraft:armor", float("nan"))])[0])
        self.assertTrue(check_attributes([A("minecraft:armor", float("inf"))])[0])
        self.assertTrue(check_attributes([A("minecraft:armor", 1)] * (MAX_ATTRIBUTES + 1))[0])
        self.assertEqual(check_attributes([A("minecraft:armor", 1)] * MAX_ATTRIBUTES), ([], []))
        _e, w = check_attributes([A("minecraft:armor", 0)])
        self.assertEqual(len(w), 1)                                       # 0 is useless
        _e, w = check_attributes([A("minecraft:follow_range", 1), A("mod:thing", 1)])
        self.assertEqual(len(w), 2)                                       # unverified, not blocked
        with self.assertRaises(ValueError):
            gen.build_give_command("a", "minecraft:stick", "", TEXT_SNBT, None,
                                   ItemProperties(attributes=(A("minecraft:generic.luck", 1),)))

    def test_enchantment_validation(self):
        from core.attributes import check_enchantments
        self.assertEqual(check_enchantments([("minecraft:sharpness", 255)]), ([], []))
        for bad in (0, 256, -1, True, 2.5, "3"):
            self.assertTrue(check_enchantments([("minecraft:sharpness", bad)])[0], bad)
        self.assertTrue(check_enchantments([("Sharpness", 1)])[0])
        dup = check_enchantments([("minecraft:sharpness", 1), ("minecraft:sharpness", 2)])[0]
        self.assertEqual(len(dup), 1)
        self.assertEqual(len(check_enchantments([("minecraft:new_thing", 1)])[1]), 1)
        self.assertEqual(len(check_enchantments([("pack:custom", 1)])[1]), 1)

    def test_labels_and_number_formats(self):
        self.assertEqual(attribute_label("minecraft:attack_damage"), "Attack Damage")
        self.assertEqual(attribute_label("minecraft:movement_speed"), "Speed")
        self.assertEqual(enchantment_label("minecraft:luck_of_the_sea"), "Luck of the Sea")
        self.assertEqual(enchantment_label("minecraft:vanishing_curse"), "Curse of Vanishing")
        self.assertEqual(format_double(7), "7.0d")
        self.assertEqual(format_double(0.1), "0.1d")
        self.assertEqual(format_double(-1e-7), "0.0d")                    # no exponent notation
        self.assertEqual(format_double(123456.5), "123456.5d")
        self.assertEqual([format_number(x) for x in (7, 0.25, 1.456, 10.0, 0.004)],
                         ["7", "0.25", "1.46", "10", "0"])


class DocumentedFormatTests(unittest.TestCase):
    """Our 1.21.5+ output has the structure the official component reference documents
    (minecraft.wiki 'Data component format', checked against 26.2 / 26.3 on 2026-10-13)."""

    def test_structures_match_the_documented_examples(self):
        props = ItemProperties(
            lore=("&6A shiny Diamond!",), enchantments=(("minecraft:sharpness", 3), ("minecraft:knockback", 2)),
            attributes=(A("minecraft:scale", 4, "add_multiplied_base", "hand"),),
            max_damage=4, max_stack_size=1, fire_resistant=True, unbreakable=True)
        _i, c = parse_give(gen.build_give_command("grow", "minecraft:stick", "&dMagic Wand",
                                                  TEXT_SNBT, None, props))
        # custom_name={text:"Magic Wand",color:"light_purple",italic:false}
        self.assertEqual(c["custom_name"], {"text": "Magic Wand", "color": "light_purple", "italic": False})
        # lore=[{text:"A shiny Diamond!",italic:false,color:"gold"}]
        self.assertEqual(c["lore"], [{"text": "A shiny Diamond!", "color": "gold", "italic": False}])
        # enchantments={sharpness:3,knockback:2}: a plain map, no 'levels' wrapper
        self.assertEqual(set(c["enchantments"]), {"minecraft:sharpness", "minecraft:knockback"})
        self.assertNotIn("levels", c["enchantments"])
        # attribute_modifiers=[{type:...,slot:...,id:...,amount:...,operation:...}]: a plain list
        (entry,) = c["attribute_modifiers"]
        self.assertEqual(set(entry), {"type", "slot", "id", "amount", "operation"})
        self.assertEqual((entry["type"], entry["slot"], entry["operation"]),
                         ("minecraft:scale", "hand", "add_multiplied_base"))
        self.assertEqual(c["damage_resistant"], {"types": "#minecraft:is_fire"})
        self.assertEqual(c["max_damage"], "4")
        self.assertEqual(c["unbreakable"], {})

    def test_saddle_slot_needs_1_21_5(self):
        mods = [A("minecraft:armor", 1, "add_value", "saddle")]
        self.assertEqual(check_attributes(mods, TEXT_SNBT), ([], []))
        errors, _w = check_attributes(mods, TEXT_JSON)
        self.assertEqual(len(errors), 1)
        self.assertIn("1.21.5", errors[0])
        with self.assertRaises(ValueError):
            gen.build_give_command("a", "minecraft:stick", "", TEXT_JSON, None,
                                   ItemProperties(attributes=tuple(mods)))
        gen.build_give_command("a", "minecraft:stick", "", TEXT_SNBT, None,
                               ItemProperties(attributes=tuple(mods)))
        lines = build_tooltip("minecraft:stick", "", ItemProperties(attributes=tuple(mods)))
        self.assertIn("When on Saddle:", ["".join(s.text for s in line) for line in lines])


class DurabilityCustomDataTests(unittest.TestCase):
    def plan(self, base="minecraft:stick", **kw):
        return gen.analyze_item("a", base, "", TEXT_SNBT, None, ItemProperties(**kw))

    def test_max_damage_needs_stack_size_one(self):
        self.assertTrue(self.plan(max_damage=100).errors)                  # stick stacks to 64
        self.assertEqual(self.plan(max_damage=100, max_stack_size=1).errors, [])
        self.assertTrue(self.plan(max_damage=100, max_stack_size=8).errors)
        self.assertEqual(self.plan("minecraft:diamond_sword", max_damage=100).errors, [])
        self.assertEqual(self.plan("minecraft:ender_pearl", max_damage=5, max_stack_size=1).errors, [])
        self.assertTrue(self.plan("minecraft:ender_pearl", max_damage=5).errors)   # default 16
        warn_only = self.plan("othermod:gizmo", max_damage=5)               # cannot know the default
        self.assertEqual(warn_only.errors, [])
        self.assertEqual(len(warn_only.warnings), 1)
        for bad in (0, -5):
            self.assertTrue(self.plan(max_damage=bad, max_stack_size=1).errors)

    def test_max_damage_and_stack_errors_are_not_doubled(self):
        plan = self.plan("minecraft:diamond_sword", max_damage=100, max_stack_size=5)
        self.assertEqual(len(plan.errors), 1)

    def test_fire_resistant(self):
        c = parse_give(gen.build_give_command("a", "minecraft:stick", "", TEXT_SNBT, None,
                                              ItemProperties(fire_resistant=True)))[1]
        self.assertEqual(c["damage_resistant"], {"types": "#minecraft:is_fire"})

    def test_snbt_reader(self):
        ok = ['{}', '{a:1}', '{a:1b,b:2s,c:3L,d:4.5f,e:6d,f:true,g:"x y",h:\'q\'}',
              '{list:[1,2,3],nested:{deep:{x:[{y:1}]}},arr:[I;1,2,3],b:[B;1b]}',
              '{"quoted key":1, other: hello}', '{s:"esc \\" \\\\ done"}', '  { a : 1 }  ']
        for text in ok:
            self.assertIsNone(check_compound(text), text)
        bad = ['', '[1,2]', '{', '{a:1', '{a 1}', '{a:}', '{a:1,,b:2}', '{a:"open}',
               '{a:1} trailing', '{a:[1,2}', '{a:1x}', '{:1}', '1']
        for text in bad:
            self.assertIsNotNone(check_compound(text), text)
        self.assertIn("character", check_compound("{a:1"))
        deep = "{a:" * 40 + "1" + "}" * 40
        self.assertIsNotNone(check_compound(deep))                          # bounded recursion

    def test_snbt_to_json_values(self):
        r = parse_compound('{a:1,b:2.5,c:true,d:"s",e:[1,2],f:{g:hello}}')
        self.assertEqual(r.value, {"a": 1, "b": 2.5, "c": True, "d": "s", "e": [1, 2], "f": {"g": "hello"}})
        self.assertFalse(r.lossy)
        self.assertTrue(parse_compound("{a:1b}").lossy)
        self.assertTrue(parse_compound("{a:[I;1]}").lossy)
        self.assertEqual(parse_compound("{a:1.5f}").value, {"a": 1.5})

    def test_custom_data_is_written_exactly_and_validated(self):
        text = '{tier:3b,owner:"ruby",tags:["a","b"]}'
        cmd = gen.build_give_command("a", "minecraft:stick", "", TEXT_SNBT, None,
                                     ItemProperties(custom_data="  " + text + "  "))
        self.assertTrue(cmd.endswith(f",custom_data={text}]"))
        _i, c = parse_give(cmd)
        self.assertEqual(c["custom_data"]["owner"], "ruby")
        plan = self.plan(custom_data="{oops")
        self.assertTrue(any(e.startswith("Custom data:") for e in plan.errors))
        self.assertEqual(self.plan(custom_data="   ").errors, [])           # blank = none
        self.assertNotIn("custom_data", [k for k, _v in self.plan(custom_data="").entries])

    def test_custom_data_recipe_json_and_lossy_warning(self):
        plain = self.plan(custom_data='{a:1,b:"x",c:true}')
        self.assertEqual(plain.json["minecraft:custom_data"], {"a": 1, "b": "x", "c": True})
        self.assertEqual(plain.warnings, [])
        typed = self.plan(custom_data="{a:1b}")
        self.assertEqual(len(typed.warnings), 1)
        self.assertIn("recipe", typed.warnings[0])

    def test_extras_that_clash_with_new_editor_values(self):
        extras = {"enchantments": "{}", "attribute_modifiers": "[]", "max_damage": "5",
                  "damage_resistant": "{}", "custom_data": "{}"}
        plan = gen.analyze_item("a", "minecraft:stick", "", TEXT_SNBT, extras, ItemProperties(
            enchantments=(("minecraft:mending", 1),), attributes=(A("minecraft:armor", 1),),
            max_damage=9, max_stack_size=1, fire_resistant=True, custom_data="{x:1}"))
        self.assertEqual(len([w for w in plan.warnings if "ignored" in w]), 5)
        self.assertEqual([v for k, v in plan.entries if k == "max_damage"], ["9"])
        # unset in the editor: the raw extras are used as before
        plain = gen.analyze_item("a", "minecraft:stick", "", TEXT_SNBT, {"max_damage": "5"}, None)
        self.assertEqual(plain.entries[-1], ("max_damage", "5"))

    def test_fire_resistant_extra_points_to_the_option(self):
        plan = gen.analyze_item("a", "minecraft:stick", "", TEXT_SNBT, {"fire_resistant": "{}"}, None)
        self.assertIn("Fire resistant", plan.warnings[0])


class TooltipTests(unittest.TestCase):
    def text(self, lines):
        return ["".join(s.text for s in line) for line in lines]

    def colors(self, line):
        return [s.color for s in line]

    def test_full_item_in_vanilla_order(self):
        props = ItemProperties(
            lore=("&7Forged", "", "&cHot"), rarity="uncommon", unbreakable=True,
            enchantments=(("minecraft:sharpness", 5), ("minecraft:mending", 1),
                          ("minecraft:vanishing_curse", 1)),
            attributes=(A("minecraft:attack_damage", 7, "add_value", "mainhand"),
                        A("minecraft:attack_speed", -0.4, "add_value", "mainhand"),
                        A("minecraft:movement_speed", 0.1, "add_multiplied_base", "feet"),
                        A("minecraft:armor", 3, "add_value", "head")))
        lines = build_tooltip("minecraft:stick", "Ruby", props)
        self.assertEqual(self.text(lines), [
            "Ruby", "Sharpness V", "Mending", "Curse of Vanishing", "Forged", "", "Hot", "",
            "When in Main Hand:", "+7 Attack Damage", "-0.4 Attack Speed", "",
            "When on Feet:", "+10% Speed", "", "When on Head:", "+3 Armor", "Unbreakable"])
        self.assertEqual(self.colors(lines[0]), ["aqua"])                 # enchanted: uncommon -> rare
        self.assertEqual(self.colors(lines[1]), ["gray"])
        self.assertEqual(self.colors(lines[3]), ["red"])                  # curse
        self.assertEqual(self.colors(lines[4]), ["gray"])                 # explicit &7
        self.assertEqual(self.colors(lines[6]), ["red"])
        self.assertEqual(self.colors(lines[9]), ["blue"])                 # positive
        self.assertEqual(self.colors(lines[10]), ["red"])                 # negative
        self.assertEqual(self.colors(lines[-1]), ["blue"])

    def test_defaults(self):
        lines = build_tooltip("minecraft:diamond_sword", "", ItemProperties(lore=("plain",)))
        self.assertEqual(self.text(lines), ["Diamond Sword", "plain"])
        self.assertEqual(self.colors(lines[0]), ["white"])                # no name: base item, white
        self.assertEqual(self.colors(lines[1]), ["dark_purple"])          # lore default color
        self.assertFalse(lines[1][0].italic)                              # written non-italic

    def test_name_colors_and_rarity(self):
        self.assertEqual(effective_rarity("", False), "common")
        self.assertEqual((effective_rarity("common", True), effective_rarity("rare", True),
                          effective_rarity("epic", True)), ("rare", "epic", "epic"))
        for rarity, color in (("common", "white"), ("uncommon", "yellow"), ("rare", "aqua"),
                              ("epic", "light_purple")):
            line = build_tooltip("minecraft:stick", "Name", ItemProperties(rarity=rarity))[0]
            self.assertEqual(self.colors(line), [color])
        own = build_tooltip("minecraft:stick", "&6Gold &lBold", ItemProperties(rarity="epic"))[0]
        self.assertEqual(self.colors(own), ["gold", "gold"])              # own color beats rarity
        self.assertTrue(own[1].bold)
        mixed = build_tooltip("minecraft:stick", "A&cB", ItemProperties(rarity="epic"))[0]
        self.assertEqual(self.colors(mixed), ["light_purple", "red"])

    def test_enchantment_levels(self):
        def shown(ench, level):
            return self.text(build_tooltip("minecraft:stick", "", ItemProperties(
                enchantments=((ench, level),))))[1]
        self.assertEqual(shown("minecraft:sharpness", 1), "Sharpness I")
        self.assertEqual(shown("minecraft:mending", 1), "Mending")        # no numeral
        self.assertEqual(shown("minecraft:mending", 2), "Mending II")
        self.assertEqual(shown("minecraft:sharpness", 10), "Sharpness X")
        self.assertEqual(shown("minecraft:sharpness", 11), "Sharpness 11")
        self.assertEqual(shown("pack:cool_thing", 3), "Cool Thing III")

    def test_attribute_lines(self):
        def only(m):
            return self.text(build_tooltip("minecraft:stick", "", ItemProperties(attributes=(m,))))[1:]
        self.assertEqual(only(A("minecraft:armor", 0, "add_value", "head")), [])      # zero: hidden
        self.assertEqual(only(A("minecraft:knockback_resistance", 0.5, "add_value", "chest")),
                         ["", "When on Body:", "+5 Knockback Resistance"])            # x10
        self.assertEqual(only(A("minecraft:attack_damage", 0.25, "add_multiplied_total", "mainhand"))[2],
                         "+25% Attack Damage")
        self.assertEqual(only(A("minecraft:max_health", -4, "add_value", "any"))[1:],
                         ["When Equipped:", "-4 Max Health"])
        self.assertEqual(only(A("minecraft:luck", 1.456, "add_value", "offhand"))[2], "+1.46 Luck")

    def test_hidden_tooltip_and_traits(self):
        self.assertIsNone(build_tooltip("minecraft:stick", "x", ItemProperties(hide_tooltip=True)))
        traits = item_traits("minecraft:stick", ItemProperties(
            glint=True, max_stack_size=8, max_damage=50, fire_resistant=True, custom_data="{a:1}"))
        self.assertEqual(traits, ["glint", "stack 8", "durability 50", "fire resistant", "custom data"])
        self.assertEqual(item_traits("minecraft:stick", ItemProperties()), [])
        self.assertIn("glint (enchanted)", item_traits("minecraft:stick", ItemProperties(
            enchantments=(("minecraft:mending", 1),))))

    def test_formatting_codes_reach_the_tooltip(self):
        line = build_tooltip("minecraft:stick", "&lBold&r Plain", ItemProperties(rarity="rare"))[0]
        self.assertEqual([(s.text, s.bold, s.color) for s in line],
                         [("Bold", True, "aqua"), (" Plain", False, "aqua")])


class StoreV3Tests(unittest.TestCase):
    def full(self):
        return ItemRecord(
            "ruby", base_item="minecraft:stick", display_name="&6R",
            enchantments=[("minecraft:sharpness", 5), ("minecraft:mending", 1)],
            attributes=[A("minecraft:attack_damage", 7.5, "add_value", "mainhand"),
                        A("mod:thing", -1.0, "add_multiplied_base", "feet")],
            max_damage=500, max_stack_size=1, fire_resistant=True, custom_data='{tier:3b}')

    def test_roundtrip_and_version(self):
        with tempfile.TemporaryDirectory() as t:
            path = Path(t) / STORE_FILENAME
            store = ProjectStore(path)
            store.put("ns", self.full())
            store.save()
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["version"], 3)
            item = data["namespaces"]["ns"]["items"]["ruby"]
            self.assertEqual(item["enchantments"], {"minecraft:sharpness": 5, "minecraft:mending": 1})
            self.assertEqual(item["attributes"][0], {"type": "minecraft:attack_damage", "amount": 7.5,
                                                     "operation": "add_value", "slot": "mainhand"})
            self.assertEqual((item["max_damage"], item["fire_resistant"], item["custom_data"]),
                             (500, True, "{tier:3b}"))
            again = ProjectStore.load(path)
            self.assertEqual(again.warnings, [])
            self.assertEqual(again.items("ns")["ruby"].to_dict(), self.full().to_dict())
            self.assertEqual(again.items("ns")["ruby"].properties(), self.full().properties())

    def test_file_is_only_as_new_as_needed(self):
        for record, expected in ((ItemRecord("a"), 1), (ItemRecord("a", lore=["x"]), 2),
                                 (ItemRecord("a", lore=["x"], max_damage=5), 3),
                                 (ItemRecord("a", enchantments=[("minecraft:mending", 1)]), 3)):
            with tempfile.TemporaryDirectory() as t:
                path = Path(t) / STORE_FILENAME
                store = ProjectStore(path)
                store.put("ns", record)
                store.save()
                self.assertEqual(json.loads(path.read_text())["version"], expected)

    def test_unusable_values_are_reported_not_silently_dropped(self):
        with tempfile.TemporaryDirectory() as t:
            path = Path(t) / STORE_FILENAME
            path.write_text(json.dumps({"version": 3, "namespaces": {"ns": {"items": {"a": {
                "enchantments": {"minecraft:sharpness": "five", "minecraft:mending": 1},
                "attributes": [{"type": "minecraft:armor", "amount": 2},
                               {"type": "minecraft:armor"}, "junk",
                               {"amount": 1}, {"type": "minecraft:luck", "amount": "x"}],
                "max_damage": 0, "custom_data": 5}}}}}))
            store = ProjectStore.load(path)
            rec = store.items("ns")["a"]
            self.assertEqual(rec.enchantments, [("minecraft:mending", 1)])
            self.assertEqual([m.type for m in rec.attributes], ["minecraft:armor"])
            self.assertEqual((rec.max_damage, rec.custom_data), (None, ""))
            self.assertEqual(len(store.warnings), 1 + 4 + 1 + 1)
            for fragment in ("sharpness", "attribute modifier 2", "attribute modifier 3",
                             "attribute modifier 4", "attribute modifier 5", "max_damage",
                             "custom_data"):
                self.assertTrue(any(fragment in w for w in store.warnings), fragment)

    def test_bare_ids_in_a_hand_edited_file_get_the_namespace(self):
        rec = ItemRecord.from_dict("a", {"enchantments": {"sharpness": 3},
                                         "attributes": [{"type": "attack_damage", "amount": 1}]})
        self.assertEqual(rec.enchantments, [("minecraft:sharpness", 3)])
        self.assertEqual(rec.attributes[0].type, "minecraft:attack_damage")

    def test_regenerate_end_to_end(self):
        with tempfile.TemporaryDirectory() as t:
            dp = make_dp(Path(t))
            rec = self.full()
            rec.base_item = "minecraft:stick"
            rec.recipe = Recipe(recipe_id="ruby", output="custom:ruby", count=1,
                                slots=["minecraft:diamond"] + [""] * 8, kind="shapeless")
            result = gen.regenerate_items(dp, "ns", {"ruby": rec}, ["ruby"], TEXT_SNBT)
            self.assertEqual(result.summary.errors, 0)
            self.assertEqual(result.summary.warnings, 2)    # lossy 3b custom data + unverified mod:thing
            give = dp.give_function_path("ns", "ruby").read_text(encoding="utf-8")
            _i, c = parse_give(give.rstrip("\n"))
            for key in ("enchantments", "attribute_modifiers", "max_damage", "damage_resistant",
                        "custom_data", "max_stack_size"):
                self.assertIn(key, c)
            recipe = json.loads(dp.recipe_file("ns", "ruby").read_text(encoding="utf-8"))
            self.assertEqual(recipe["result"]["components"]["minecraft:custom_data"], {"tier": 3})
            # a damageable-needs-stack-1 mistake blocks everything
            rec.max_stack_size = None
            bad = gen.regenerate_items(dp, "ns", {"ruby": rec}, ["ruby"], TEXT_SNBT)
            self.assertGreaterEqual(bad.summary.errors, 1)       # the item, and its recipe result


if __name__ == "__main__":
    unittest.main()
