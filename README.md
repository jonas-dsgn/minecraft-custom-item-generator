# Minecraft Custom Item Generator

A small PySide6 desktop tool (Windows 10/11) that generates, for custom items:

- `assets/minecraft/items/<name>.json` (item definition)
- `assets/minecraft/models/item/<name>.json` (item model)
- `data/<namespace>/function/give/<name>.mcfunction` (give function)
- `data/<namespace>/function/display/<name>.mcfunction` (optional `item_display` summon function)

It works on a resource pack and a datapack at the same time. It never creates textures, never
touches `pack.mcmeta` / `pack.png` / existing textures, and never overwrites files unless you
explicitly enable and confirm it.

## Setup

Requires Python 3.9+ (Windows: tick "Add python.exe to PATH" in the installer).

Double-click `run.bat`. On first run it creates `.venv`, installs PySide6 and starts the app.

Manual alternative:

```bat
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python main.py
```

## Usage

1. Pick the **Resource Pack Folder** and **Datapack Folder** (dot: green = valid, amber = usable but
   something will be created or is missing, red = invalid). Paths and settings are remembered
   between launches (QSettings).
2. The namespace box lists namespaces found in `data/` (default `customfood`). Set the base item
   (default `minecraft:stick`).
3. **Mode A** - enter texture names (one per line, no `.png`, lowercase `a-z 0-9 _ -`) and press
   **Generate Items**. Missing textures trigger a prompt (generate anyway / skip / cancel), or tick
   "Generate JSON even if texture is missing" to skip the prompt.
4. **Mode B** - press **Scan Existing Models**, select models, press
   **Generate Missing Item Definitions**. `items/<model>.json` is written if missing (models are never
   touched) and give functions are generated exactly like in Mode A. Definitions already in
   `items/` are listed too.
5. In game: `/function customfood:give/custom_sword` (reload with `/reload` after adding functions).

Datapack directory names follow what the pack already has: `function` (1.21+) is used by default;
if the namespace already has a legacy `functions` folder, that one is used.

### Example

Input:

```text
custom_sword
ruby_sword
```

with `custom_sword.png` present and `ruby_sword.png` missing, "allow missing" unchecked and
"Skip those items" chosen:

```text
[WARNING] Texture not found: ruby_sword.png
[SKIPPED] ruby_sword: item skipped (missing texture)
[OK] Created items/custom_sword.json
[OK] Created models/item/custom_sword.json
[OK] Created give/custom_sword.mcfunction
```

`items/custom_sword.json`:

```json
{
  "model": {
    "type": "minecraft:model",
    "model": "minecraft:item/custom_sword"
  }
}
```

`models/item/custom_sword.json`:

```json
{
  "parent": "minecraft:item/generated",
  "textures": {
    "layer0": "minecraft:item/custom_sword"
  }
}
```

`function/give/custom_sword.mcfunction`:

```mcfunction
give @p minecraft:stick[item_model="minecraft:custom_sword"]
```

## Window, scrolling and fullscreen

The whole page scrolls vertically (one scroll area; mouse wheel and scrollbar work) when the window is
too small, and widens/heightens normally when maximized or resized. **F11** toggles fullscreen. A footer
bar below the page always shows the main action of the current tab (**Generate Items**, **Generate Item
Definitions**, **Save & Regenerate Files**) and the last result summary. Combo boxes ignore the wheel
until focused, so scrolling the page never changes a setting by accident. The recipe dialog scrolls too,
with Save/Cancel pinned at the bottom and a size capped to the screen. Window size/position are remembered.

## Item display function (optional)

Tick **Generate Item Display Function** (off by default) in the datapack settings (applies to items
created in tabs A/B) or per item in tab C. It writes `function/display/<name>.mcfunction`:

```mcfunction
summon minecraft:item_display ~ ~ ~ {item:{id:"minecraft:stick",count:1,components:{"minecraft:item_model":"minecraft:andesite_greek_pillar"}},item_display:"fixed",transformation:{left_rotation:[0f,0f,0f,1f],right_rotation:[0f,0f,0f,1f],translation:[0f,0f,0f],scale:[1.0f,1.0f,1.0f]}}
```

Call it with `/function <namespace>:display/<name>`. By default the scale is 1.0 on all axes (no
automatic resizing) and the mode is `fixed`; the name, base item and extra components match the give
function.

**Display mode and scale.** Under the checkbox (settings group for new items, and in tab C per item):

- *Display mode*: `fixed`, `ground`, `head`, `gui`, `firstperson_righthand`, `firstperson_lefthand`,
  `thirdperson_righthand`, `thirdperson_lefthand`. It is written as `item_display:"<mode>"` and only
  decides how the item is positioned/oriented - it does **not** change the size.
- *Scale X / Y / Z*: written as `transformation:{...,scale:[X f,Y f,Z f]}`. **Link axes** (on by default)
  makes one value drive all three axes; untick it for non-uniform scaling. Values must be plain decimals
  between 0.001 and 1000 (comma accepted as decimal separator); invalid fields turn red, show an error in
  the command preview and block Save/Generate, so no broken command is ever written.
- Both settings are saved with the item (`display_mode` / `display_scale` in
  `item_generator_items.json`, only when not default). **Save & Regenerate Files** rewrites the display
  function when they change; the give function is unaffected.
- Items created in tabs A/B take the settings from the settings group; items that already have a
  display function keep their own. The give function does not depend
on the checkbox. Unticking it for an item whose display function this tool generated removes only
that file (after confirmation); other files in `display/` are never touched.

## Lore, properties and formatting codes (tab C)

Tab C is the single item editor for name, lore, properties and recipe. Everything is saved with the
item in `item_generator_items.json` and written to the give function, the optional display function
and the recipe result, so all three always agree.

**Formatting code reference.** A grid of every code sits under the name field: the 16 colors as real
color tiles (`&0` Black ... `&f` White), and `&k` Obfuscated (animated), `&l` Bold, `&m`
Strikethrough, `&n` Underline, `&o` Italic and `&r` Reset drawn in their own style, plus a `&#RRGGBB`
color picker and `&&` (literal `&`). Click a tile to insert it **at the cursor**:

- nothing is ever replaced; a selection stays selected (code goes after it if the caret is at its
  end, before it if the caret is at its start); with no selection the caret moves behind the code;
- the tile never takes keyboard focus, caret and selection are restored even after a real mouse
  click, and Ctrl+Z undoes the insertion;
- **one reference serves the name and every lore line**: it inserts into whichever of them you
  clicked in last (shown as "Inserting into: Lore line 2"). There is no second name editor.
- tooltips show the exact component syntax that code produces for the selected target version.

**Lore.** Add Line, remove (X) and reorder (up/down) lines; Enter inside a line adds one below it.
Each line takes the same codes as the name; empty lines are kept as blank lore lines, spaces are kept,
up to 256 lines. Lines are written non-italic (like names, unless `&o`) and, without a color code,
appear in the game's default dark purple (the preview shows this). Unknown codes such as `&z` are
written as plain text and reported as warnings.

**Item properties.**

| Property | Component | Notes |
| --- | --- | --- |
| Stack size | `max_stack_size` | 1-99 (both targets). "Default (N)" shows the base item's own size. Damageable items (tools, armor, bow, shield, elytra, ...) can only be 1: anything higher is an error. Items outside the built-in table are accepted with a warning. |
| Enchantment glint | `enchantment_glint_override=true` | |
| Rarity | `rarity` | common / uncommon / rare / epic |
| Unbreakable | `unbreakable={}` | |
| Hide tooltip | `hide_tooltip={}` (1.21.4) / `tooltip_display={hide_tooltip:true}` (1.21.5+) | the syntax follows the target version |

**More components.**

| Option | Component | Notes |
| --- | --- | --- |
| Max durability | `max_damage` | Makes the item damageable, so the stack size must be 1 (the editor tells you; items that are already damageable, like swords, need nothing). |
| Fire resistant | `damage_resistant={types:"#minecraft:is_fire"}` | The 1.21.2+ replacement of the old `fire_resistant`. |
| Custom data | `custom_data` | An SNBT compound for your own functions, e.g. `{tier:3,owner:"ruby"}`. Checked for syntax; written exactly as typed. In a recipe result JSON cannot express typed numbers (`1b`, `2.5f`, `[I;...]`), so they become plain int/double there (a warning says so). |
| Enchantments | `enchantments` | Rows of id + level 1-255. Pick from the vanilla list or type any id (datapack enchantments need their namespace). Duplicates and bad levels are errors. |
| Attribute modifiers | `attribute_modifiers` | Rows of attribute, operation, amount and slot. |

**Attribute modifiers.** Attributes use the 1.21.2+ names (`attack_damage`, not `generic.attack_damage`);
typing an old name gives an error that suggests the new one. Operations: *Add* is a plain number
(7 = +7); *Multiply base* / *Multiply total* take fractions (0.1 = +10%). Slots: any, main hand, off
hand, hand, head, chest, legs, feet, armor, body, saddle (1.21.5+). Every modifier gets a unique id generated from the
item name (`minecraft:<item>_<attribute>_<n>`), identical in the give command, the display function and the
recipe result. Bare ids get `minecraft:`; other namespaces are accepted and reported as unverified.
Ids that are not in the built-in list (mob-only attributes, newer ones) are accepted with a warning.

| | 1.21.5 and newer | 1.21.4 |
| --- | --- | --- |
| attributes | `attribute_modifiers=[{...}]` | `attribute_modifiers={modifiers:[{...}]}` |
| enchantments | `enchantments={"minecraft:sharpness":5}` | `enchantments={levels:{"minecraft:sharpness":5}}` |

The in-game `show_in_tooltip` switches of these components are not offered (1.21.5 removed them); use
*Hide tooltip* to hide the whole tooltip. This syntax is written from the known formats and checked by
the tests, but has not been run against a live game: generate one item and check it in your version.

**In-game tooltip preview.** The top-left panel of tab C shows the item like the game does and
updates as you type: name (colored by rarity, which an enchanted item raises one step, as in
game), enchantments (gray, curses red, roman numerals, no numeral for single-level ones like Mending
at level 1), lore (default dark purple), attribute modifiers grouped by slot ("When in Main Hand:" ...)
with blue positive / red negative lines, `%` for multiplier operations, numbers rounded to two decimals
and knockback resistance shown x10 like the game, then *Unbreakable*. *Hide tooltip* shows an empty
tooltip. Properties without tooltip text (glint, stack size, durability, fire resistance, custom data)
are listed under the panel. It is a close representation, not the game's renderer: the font is not
Minecraft's, line order follows the 1.21 client from memory, and items whose own default rarity is not
common (golden apple, ...) show the rarity you chose or white.

**Target version.** There is no pack-version auto-detection in this tool; the existing *Target
version* setting decides the syntax for everything. 1.21.5+ writes SNBT text components
(`lore=[{text:"a",italic:false}]`); 1.21.4 writes JSON strings (`lore=['{"text":"a",...}']`). Recipe
results use the matching JSON components.

**Escaping.** Quotes, backslashes and apostrophes in names and lore are escaped for both syntaxes
(verified by parsing the generated commands back in the tests). Control characters are removed, so a
command is always one line.

**Nothing is dropped silently.**
- `extra_components` from the project file are still written verbatim. If one is **not supported by the
  target version** (`hide_tooltip` on 1.21.5+, `tooltip_display` on 1.21.4, `fire_resistant`) it is left
  out of the commands, shown in the editor and logged as a warning; it stays in the project file.
- An extra that clashes with an editor value (`max_stack_size` when a stack size is set) loses to the
  editor value, with a warning. Extras are listed in the editor's notes.
- Values in the project file that cannot be used (a `lore` that is not a list, `max_stack_size: 500`,
  unknown `rarity`) are ignored and logged as warnings when the project loads.
- Invalid data blocks saving and nothing is written: a stack size on a damageable item, max durability
  without stack size 1, more than 256 lore lines, malformed custom data, a pre-1.21.2 attribute name,
  an unknown operation or slot, a duplicate enchantment, a level outside 1-255.

**Project file.** Items gain optional keys, written only when not default: `lore` (list of &-code
strings), `max_stack_size`, `glint`, `rarity`, `unbreakable`, `hide_tooltip` (store version 2) and
`enchantments` (`{id: level}`), `attributes` (list of `{type, amount, operation, slot}`), `max_damage`,
`fire_resistant`, `custom_data` (store version 3). The file is written with the lowest version that can
hold its data (1, 2 or 3), so older builds can still open files that do not use the new fields and refuse,
instead of silently dropping data from, files that do.

## New pack template (export an empty resource pack + datapack)

**Project paths > New Pack Template...** creates a fresh, empty resource pack and datapack that this
tool accepts right away. Pick a name, a namespace and a folder; the dialog shows the exact folder tree and
both `pack.mcmeta` files before anything is written. Press **Create Template Pack**, and the packs
are loaded into the tool (switch this off with *Use the new packs in this tool*).

```
<name> - Resource Pack/                 <name> - Data Pack/
    pack.mcmeta                             pack.mcmeta
    assets/minecraft/items/                 data/<namespace>/function/give/
    assets/minecraft/models/item/
    assets/minecraft/textures/item/
```

- **Formats.** Presets for *26.2 and newer (26.2 - 26.3)* (default), *26.3 only* and *26.2 only*
  (data pack 107.1 / 121.0, resource pack 88.0 / 97.1, taken from the release notes, last compared
  2026-10-13). The files use `min_format` / `max_format` only, because `pack_format` and
  `supported_formats` must be absent in packs for 1.21.9 and newer. Newer versions: choose *Custom
  formats...* and enter the numbers from the release notes (minimum `major.minor`, maximum major).
  Formats below 82 (datapack) or 65 (resource pack) are refused.
- **Safe.** Nothing is ever overwritten: if a target folder already exists (even an empty one) the
  dialog says so and stays disabled. If writing fails half way, everything this run created is removed
  again; folders that were not created by the run are never touched. The save location must be a full
  path, so a template can never end up in an unexpected working directory.
- **Names.** The pack name becomes the folder names. Characters Windows forbids, trailing dots or
  spaces, reserved names (CON, NUL, ...) and over-long names are rejected; the description (shown in
  Minecraft's pack list, default: the pack name) may contain any text, including non-ASCII.
- **Either or both.** Untick *Resource pack* or *Datapack* to create only one.
- Not included: a `pack.png` icon (optional; drop a 64x64 png named `pack.png` into the pack folder)
  and any items. The packs contain nothing but the structure the tool checks for.

## Compatibility with Minecraft 26.x (checked 2026-10-13)

Use target version **"1.21.5 and newer"** for 26.1, 26.2 and 26.3. Checked against the 26.2 release
(16 Jun 2026; data pack format 107.1, resource pack format 88.0), the 26.3 release (15 Sep 2026; data pack
121.0, resource pack 97.1), the Minecraft Wiki's data component reference and `pack.mcmeta` page, and the
datapack breaking-changes list. Nothing the tool writes was changed or removed in 26.1-26.3:

| What the tool writes | Status on 26.2 / 26.3 |
| --- | --- |
| `custom_name`, `lore` as SNBT text components | unchanged since 1.21.5 |
| `enchantments` as a plain map, `attribute_modifiers` as a plain list | matches the documented format |
| `max_stack_size` (1-99), `max_damage` (cannot combine with stack > 1), `damage_resistant`, `custom_data`, `rarity`, `unbreakable`, `enchantment_glint_override`, `item_model`, `tooltip_display` | present and documented |
| `/give`, `/summon item_display`, `function/`, `recipe/` folders, crafting recipe JSON, `items/*.json` model definitions | unchanged (26.3 only changes cooking/brewing recipes and loot-table references, which this tool does not write) |

The item generator itself never reads or writes pack formats, it only checks that `pack.mcmeta`
exists (the *New Pack Template* feature above writes a correct one for you). A pack that targets
1.21.9 or newer needs the new fields (`pack_format` and `supported_formats` must be absent unless the
pack also supports versions older than 1.21.9):

```json
{ "pack": { "description": "My items", "min_format": [107, 1], "max_format": 121 } }
```

for a data pack covering 26.2 and 26.3, and `"min_format": [88, 0], "max_format": 97` for the resource
pack. Do not copy one pack's numbers into the other: 88 is the 26.2 *resource* pack format but was also the
*data* pack format of 1.21.9/1.21.10. In 26.3, `/give` and `/tick` signal errors properly, so an invalid
command in a generated function now fails visibly instead of silently.

Limits: this was checked against documentation, not by running the game, and 26.4 is still in snapshots.
Not offered: the attribute modifier `display` field (hidden/override). The tooltip preview lists
enchantments in the order you entered them, while the game orders them by the `#minecraft:tooltip_order`
enchantment tag. The `saddle` attribute slot (added in 1.21.5) is offered and rejected on the 1.21.4 target.

## Item names and recipes (tab C)

Every item created in tabs A/B (and every `give/*.mcfunction` already in the datapack) shows up in
**C. Name & recipe**. Select one to edit it, then press **Save & Regenerate Files**.

**item_model IDs.** `item_model` must be the ID of the *item definition*, i.e. the file name in
`assets/minecraft/items/`: `items/gui_accept.json` -> `minecraft:gui_accept`. (Earlier versions wrote
`minecraft:item/gui_accept`, which shows the error cube.) The model and texture paths inside the JSON
files are unchanged (`minecraft:item/<name>`). Old give functions are repaired by
**Regenerate All Functions**, which keeps each item's base item.

**Display name.** Type legacy codes: `&6Ancient Sword` -> gold name. Supported: `&0-&9`, `&a-&f`,
`&#RRGGBB`, `&l` bold, `&o` italic, `&n` underline, `&m` strikethrough, `&k` obfuscated, `&r` reset,
`&&` literal `&`. A color code resets earlier formatting (like legacy Minecraft). Names are non-italic
unless you use `&o`. Empty = no custom name. Quotes and backslashes are escaped. Generated command
(1.21.5+):

```mcfunction
give @p minecraft:stick[item_model="minecraft:ancient_sword",custom_name={text:"Ancient Sword",color:"gold",italic:false}]
```

**Target version** (datapack settings): *1.21.5 and newer* (default, includes 26.x) writes names and
lore as SNBT text components; *1.21.4* writes the older JSON-string form. After changing it, press
**Regenerate All Functions**. Recipes differ only where a component changed (`hide_tooltip`).

**Recipes.** **Edit Recipe...** opens a dialog with shaped (3x3 grid) or shapeless mode, recipe ID,
output item (a custom item keeps its `item_model` and display name) and count, plus a live JSON preview
and validation. Ingredients: type or pick any vanilla item ID or `#tag` (a curated list is offered),
or a custom item as `custom:<name>`. Output uses the 1.21.2+ schema (string ingredients, `result.id`,
`result.components`) in `data/<namespace>/recipe/<id>.json`.

**Saved data.** Names, base items and recipes are stored in `item_generator_items.json` in the datapack
root (ignored by Minecraft). Saving an item regenerates its give function and every recipe that
belongs to it or produces it, so renames stay consistent. Existing files that would change are listed
and need confirmation; unrelated files are never touched.

**Limitations.**
- Vanilla recipes cannot match item components on *inputs*. A custom ingredient is therefore exported
  as its base item (any stick, for example) and the editor warns about it.
- Ingredient IDs are checked for syntax only, not against the game's item registry.
- The item ID (file name) cannot be renamed in the tool; only display name, base item and recipe.
- Removing a recipe from an item does not delete its JSON file (the tool never deletes files).
- `extra_components` (raw component values kept in `/give` commands) can only be edited in the
  project file and are not copied into recipe results. Name, lore and the item properties above *are*
  copied into the result of a recipe that produces the custom item.
- The stack-size rules use a built-in table of vanilla items (damageable items, default sizes), not the
  game registry; unknown or modded items are reported as unverified.

## Project structure

```text
main.py                 entry point
ui/main_window.py       main window (tabs A/B/C, log, settings)
ui/recipe_dialog.py     recipe editor dialog
ui/template_dialog.py   "New Pack Template" dialog (live validation, preview)
ui/widgets.py           wheel-safe combo/spin box, display mode/scale editor, page layout,
                        formatting code reference, lore editor, tooltip preview,
                        attribute and enchantment row editors
core/ids.py             item_model / model / texture identifiers (single source of truth)
core/text_components.py &-codes -> text components (SNBT / JSON), escaping, lore lines
core/components.py      item components for give/display/recipes; version syntax, warnings
core/item_rules.py      damageable / default stack size table, stack size validation
core/format_codes.py    code reference data, per-version snippets, cursor/selection rules
core/attributes.py      attribute modifiers + enchantments: data, validation, syntax per version
core/tooltip.py         in-game tooltip model (lines of colored segments)
core/snbt.py            SNBT checker/converter for custom_data
core/recipes.py         recipe model, validation, shaped/shapeless JSON
core/items.py           ItemRecord + project store (item_generator_items.json)
core/vanilla_items.py   curated ingredient suggestions
core/templates.py       empty resource pack + datapack templates (plan, validation, safe creation)
core/validation.py      name / namespace / base item validation, input parsing
core/project_paths.py   path helpers, folder status, namespace detection
core/generator.py       file contents, safe writing with rollback, batch logic, log/summary
tests/test_core.py      unit tests for core (no Qt needed)
tests/test_properties.py lore, components, attributes, enchantments, tooltip, store, generation
                        (generated commands are parsed back with an independent SNBT reader)
tests/test_templates.py pack template planning, validation, creation, rollback
tests/test_gui.py       headless GUI tests (scrolling, resizing, display options); skipped without PySide6
requirements.txt        PySide6
run.bat                 Windows launcher (creates venv, installs, runs)
```

UI code never writes files; everything goes through `core/generator.py`, so features such as
display names, extra components, recipes or texture previews can be added as new generator
functions plus UI controls.

## Safety behaviour

- Existing files are skipped and logged; overwrite requires the checkbox plus a confirmation dialog.
- New files are created exclusively (`open(..., "x")`); if one item fails, the files created for
  that item are rolled back (and overwritten files restored).
- Names must be lowercase `a-z 0-9 _ -`; path separators, `..`, absolute paths, extensions and
  Windows-reserved names (`con`, `nul`, ...) are rejected. Duplicates and blanks are ignored.
- Only the expected output directories are created, and each creation is logged.

## Testing

Automated (core logic):

```bat
.venv\Scripts\python -m unittest discover -s tests
```

GUI tests run headless (`set QT_QPA_PLATFORM=offscreen`; set automatically by the test file).

Manual, with the folder structures from the spec:

1. Create `resource_pack/assets/minecraft/{items,models/item,textures/item}` + `pack.mcmeta`, and
   `datapack/data/customfood/{advancement,function/foods,recipe}` + `pack.mcmeta`.
2. Drop `custom_sword.png` into `textures/item/`.
3. Select both folders (both dots green), enter `custom_sword` and `ruby_sword`, click
   **Generate Items**, choose "Skip those items": expect 3 files for `custom_sword`, a warning for
   `ruby_sword`.
4. Click Generate again: expect 3 `[SKIPPED] ... already exists` lines and no changes.
5. Put `pre_made.json` into `models/item/`, click **Scan Existing Models**, select it, click
   **Generate Missing Item Definitions**: only `items/pre_made.json` appears.
6. Open tab C, select `custom_sword`, set the name `&6Ancient Sword`, click **Edit Recipe...**, fill a
   grid, check the preview, **Save**. Confirm the file list; check `give/custom_sword.mcfunction` and
   `recipe/custom_sword.json`.
7. Copy both packs into a Minecraft world/resourcepacks folder, `/reload`, run
   `/function customfood:give/custom_sword` and craft the recipe.
