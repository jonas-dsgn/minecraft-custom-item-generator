"""Curated ingredient suggestions. Any other valid item ID or #tag can be typed in."""

_ITEMS = """
stick diamond emerald gold_ingot iron_ingot copper_ingot netherite_ingot netherite_scrap
coal charcoal redstone lapis_lazuli quartz amethyst_shard glowstone_dust gunpowder string
leather feather flint bone bone_meal slime_ball ender_pearl ender_eye blaze_rod blaze_powder
nether_star ghast_tear paper book sugar wheat apple golden_apple carrot golden_carrot potato
egg milk_bucket water_bucket lava_bucket bucket glass glass_bottle stone cobblestone deepslate
cobbled_deepslate sand gravel dirt clay_ball brick bricks iron_block gold_block diamond_block
emerald_block redstone_block coal_block lapis_block copper_block netherite_block obsidian
crying_obsidian oak_planks spruce_planks birch_planks jungle_planks acacia_planks
dark_oak_planks mangrove_planks cherry_planks bamboo_planks crimson_planks warped_planks
oak_log white_wool iron_nugget gold_nugget diamond_sword diamond_pickaxe iron_sword
iron_pickaxe golden_sword shield bow arrow crossbow trident totem_of_undying heart_of_the_sea
nautilus_shell phantom_membrane rabbit_foot prismarine_shard prismarine_crystals echo_shard
honey_bottle honeycomb sweet_berries glow_berries cocoa_beans pumpkin melon_slice beetroot
torch lantern chest ender_chest crafting_table furnace anvil enchanting_table beacon tnt
turtle_scute armadillo_scute breeze_rod heavy_core mace wind_charge
""".split()

_TAGS = """
planks logs logs_that_burn wool coals sand stone_crafting_materials stone_tool_materials
wooden_slabs wooden_stairs wooden_fences leaves flowers fishes trim_materials
""".split()

VANILLA_ITEMS: list[str] = [f"minecraft:{n}" for n in _ITEMS]
VANILLA_TAGS: list[str] = [f"#minecraft:{n}" for n in _TAGS]
