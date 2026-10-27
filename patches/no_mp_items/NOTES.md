# No MP items - notes

## Problem
xrMPE keeps separate `mp_*` copies of items for its PvP modes. Co-op must use the normal (single-player) items only:
for example MP ammo does not fit the normal AK-74 (maintainer report). Places where co-op still handed out MP items:
- every player spawned with `mp_wpn_knife`, `mp_device_torch`, `mp_wpn_binoc` (`configs\mp\cooperative_game.ltx`, `default_items`),
- quick slots 1 and 3 defaulted to `mp_medkit` / `mp_antirad` (`configs\creatures\actor.ltx`),
- a generic task reward was `mp_wpn_toz34` (`configs\alife.ltx`, `[reward_for_genric_task]`),
- anomalies could spawn the MP-only artifacts `mp_af_electra_flash`, `mp_af_cta_green`, `mp_af_cta_blue` (`configs\misc\artefacts.ltx`).

## Fix
- `default_items = wpn_knife, device_torch, wpn_binoc`. The engine only hands out items that have an entry in the game
  type's cost table, so the three items were added to `[cooperative_base_cost]` with cost 0. This file is shipped by
  `patches\marked_one` (one patch per file), the edit is there.
- Quick items: `medkit`, `antirad`. This file is shipped by `patches\no_grenade_tinnitus`, the edit is there.
- `gamedata\configs\alife.ltx`: reward `wpn_toz34`.
- `gamedata\configs\misc\artefacts.ltx`: the three MP artifact lines are commented out.
Not changed: the buy-menu groups in cooperative_game.ltx (co-op has no buy menu) and the MP item definitions themselves.

## Test (Cordon, dedicated server + 1 client)
Stock: the spawned player carries `mp_wpn_knife, mp_device_torch, mp_wpn_binoc`. Patched: `wpn_knife, device_torch,
wpn_binoc`, no `mp_*` item (PASS). Without the cost entries the player got no knife, torch or binoculars at all.

## Кратко (RU)
В коопе больше не выдаются МП-предметы: стартовые нож, фонарик и бинокль теперь обычные (не mp_), быстрые слоты по умолчанию обычная аптечка и антирад, награда за задание обычная ТОЗ-34, МП-артефакты больше не появляются в аномалиях.

## Artifact icons (2026-10-21)
Report: "Stone Flower from the Cordon elevator has the Jellyfish icon". Checked with `tools\artifact_icons.py` (every artifact section,
inheritance resolved, inv_name + grid cell, the cell compared pixel by pixel with the Steam SoC `ui_icon_equipment.dds`):
- `af_cristall_flower` / `_soc` (24,0) show exactly the SoC Stone Flower icon (SoC 11,4, orange stone). The Jellyfish is a different, brown
  icon (9,4, same in the mod and SoC). The CoP Stone Flower (blue holes) stays unused at 11,4 of the mod texture. No flower fix needed;
  the two icons only look alike in outline.
- One real mismatch found and fixed: `af_dummy_battery_soc` (name "Battery") used the icon of SoC `af_dummy_dummy` (vase, 32,0) instead of
  SoC `af_dummy_battery` (lattice). The mod texture already holds the lattice at 36,1: `artefacts_soc.ltx` (copy of the mod file, only
  that cell changed) now uses it; `af_dummy_battery` inherits it. The world model (`artefact_pustishka1.ogf`) is unchanged on purpose.
- Test: `tests\artifact_icons_hook.lua` (reads inv_grid of the sections from system_ini and gives them to the player).
  run: `powershell -NoProfile -ExecutionPolicy Bypass -File <games>\tools\stalker_xrmpe\run_coop.ps1 -Map coop_l01_escape -Mode listen -Owner ai -Clients 1 -ExtraDir <stage>\gamedata -Hooks <repo>\patches\no_mp_items\tests\artifact_icons_hook.lua -SoakSeconds 60 -ResultDir <dir>`

## Artifact world models (2026-10-22)
Report (maintainer FOSTER): Vyvert "has the old icon and an unsuitable model" (inventory icon = orange-brown rock, the model on the ground = a beige,
bony, star-shaped lump).
- Cause: not the section. `af_vyvert` (alias of `af_vyvert_soc`) already has the SoC icon (25,0 = pixel-identical to SoC 14,0) and the SoC
  `visual` (`physics\anomaly\artefact_gravy1.ogf`, byte-identical to Steam SoC). But the objects lying in the world come from `all.spawn`, and a
  spawn entity stores its own `visual_name`, which wins over the section. The CoP-based all.spawn stores `dynamics\artefacts\af_vyvert` (CoP star
  model, texture `artifact_myasorubka3`), so a found Vyvert showed the CoP model next to the SoC icon. Same for 18 other ids: 6 Vyvert, 10 Medusa,
  6 Night Star, 5 Fireball, ... (19 ids, 64 objects, listed by `tools\artifact_models.py`). Objects spawned from the section (quest rewards, loot
  boxes via `[spawn] af_x_soc`, anomalies) were already right.
- Fix without touching all.spawn (saves keep working): `gamedata\meshes\dynamics\artefacts\af_<id>.ogf` for every baked id is now a copy of the
  SoC model the section points to (alias resolved: `af_eye` -> gravy2, `af_fire` -> gravy3, `af_ice` -> electra1, `af_baloon` -> cristall).
  Saves store the visual name only, so they are fixed too.
- Full scan over ALL artifacts (`tools\artifact_models.py`: section `visual` vs SoC, all.spawn baked ids vs shipped files): the section visuals
  all matched SoC except `af_dummy_battery_soc` (used `artefact_pustishka1`, SoC uses `artefact_battery`; its texture `artifact_magnit` was in no
  archive, so it is shipped, 88 KB, plus the model copy). Icons: `tools\artifact_icons.py` again, all OK. `af_dummy_dummy` stays an alias of the film
  artifact on purpose.
- Fireball: the mod's `fx\fx_lavahell1` is a bright orange CoP-edited texture, the SoC one is darker. It is shared with other effects, so the SoC
  `artefact_fire.ogf` is shipped with the texture name changed in place to `fx\fx_soc_lava1` (same length, texture shipped, 43 KB) for both the
  section path and the baked `af_fireball`.
- Size: 20 meshes + 2 textures, 5.3 MB raw, 4.1 MB in the compressed db (build budget headroom 9.7 MB after it).
- Offline checks: `check_conflicts.py` (only the 7 known), `check_ogf_includes.py` (0 missing), build.py BUDGET OK. Not run in the game.
- Run the scan: `python tools\artifact_models.py <patched artefacts.ltx> <artefacts_addon.ltx> <artefacts_soc.ltx> <SoC artefacts.ltx> <all.spawn> <this gamedata> <SoC extracted meshes dir>`
  (the SoC files come from `tools\xdb_soc.py`).

## Кратко (RU): модели артефактов
Выверт лежал на земле моделью из Зова Припяти (костлявая бежевая звезда), а в инвентаре был значок SoC: объекты на уровнях берут модель из all.spawn,
а не из секции. Секции и значки уже совпадали с SoC. Теперь файлы `meshes\dynamics\artefacts\af_<id>.ogf` для 19 id подменены моделями SoC
(all.spawn не тронут, сохранения работают). Заодно: у Батарейки модель и текстура SoC (`artefact_battery`, `artifact_magnit`), у Огненного шара
оригинальная тёмная текстура лавы. Размер +4.1 МБ в сжатом db.

## 1.4.3 fix: flashlight and night vision
Report (2026-10-22): flashlights and night vision did not work. The flashlight and the night vision are one item (`device_torch`, `night_vision = on`).
Since 1.4 players got `device_torch` instead of the mod's `mp_device_torch` (the two sections are the same, `mp_device_torch` only has an empty `$spawn`).
Checked in the game (live session, Cordon): `device_torch` sits in slot 10 and `enable_torch(true)` from a script works, so the item is fine, but the
keys go through the engine, and the mod's own scene effects (`xr_effects.disable_actor_torch` etc.) also look for `mp_device_torch` by name.
Fix: `default_items` gives `mp_device_torch` again (knife and binoculars stay the normal items), and `gamedata\scripts\coop_scn_torch_fix.script`
(server tick, every level) swaps the `device_torch` of players restored from 1.4 to 1.4.3 saves: release first, the new one on the next tick so it
goes into the free flashlight slot.

## Original artifact stats (v1.5.1)
Report (maintainer FOSTER): "bring back the properties of the artifacts from the ORIGINAL SoC". Compared every `af_*_soc` section with the Steam SoC 1.0006
`config\misc\artefacts.ltx` (inheritance resolved): 25 of 31 differed. The add-on had changed the price (Vyvert 1000 to 4000, Gravi 2500 to 6000, Gold Fish 5000 to 9000,
Crystal 5000 to 1000, and more) and made every `*_restore_speed` 10 to 40 times the original (Medusa radiation 0.0005 to 0.01, Moonlight power 0.006 to 0.1, Soul health
0.0006 to 0.007). The immunity sections already matched. `tools\restore_soc_artifact_stats.py <original artefacts.ltx> <artefacts_soc.ltx>` sets cost and the five
restore speeds of each `_soc` section to the original numbers (bytes and encoding of the rest of the file stay). Checked in game: `system_ini()` reads the original numbers.
Left as they are: `af_rank = 0` and `additional_inventory_weight = 0`, which the original has no line for (same effect).
