# Shadow of COOP fixes

[![Discord](https://img.shields.io/badge/Discord-chat%20and%20help-5865F2?logo=discord&logoColor=white)](https://discord.gg/EXGB49R82t)

Unofficial bug-fix patch for **Shadow of COOP 8.0**, the S.T.A.L.K.E.R.: Shadow of Chernobyl
co-op add-on for the X-Ray Multiplayer Extension (xrMPE). It fixes crashes and stuck quests and
unlocks the true ending.

This is a fan patch. It is not made by or affiliated with the Shadow of COOP or xrMPE teams.
You need their launcher and add-on first.

## Latest version: 1.5.0 (use this one)

Download **`SoC_COOP_fixes_v1.5.0.zip`** from [Releases](../../releases), unzip it, close the game and the xrMPE launcher, and double-click
`installer\install.bat`. It adds the fixes and the original cut-scene movies to your `coop.addon` (the same way on every PC, so everybody gets the same add-on
fingerprint) and copies the movie sound of your language (Russian or English) to `game\patches`. Every player, the host and a dedicated server PC install it the same way.

The movies make the add-on larger than 4 GiB, which the 32-bit game engine could not load. The release therefore also carries a fix for one engine file
(`game\bin\xrCore.dll`), made with the OK of the xrMPE team; `install.bat` applies it for you. The fix is also a download of its own,
**`SoC_COOP_4GB_patch.zip`**, for anyone who just wants add-ons larger than 4 GiB. How it works and how it was tested: [tools/xrcore_4gb](tools/xrcore_4gb/README.md).

Language: the movie sound language is chosen when you install (from `voice_language` in your `coop_settings.ltx`, else the launcher language;
`install.bat -Voice rus` or `-Voice eng` to force one). Scripted voice lines follow `voice_language` in the `[client]` section of `coop_settings.ltx` (`auto`, `rus`, `eng`).

**Русский.** Скачайте **`SoC_COOP_fixes_v1.5.0.zip`** из [Releases](../../releases), распакуйте, закройте игру и лаунчер xrMPE и запустите `installer\install.bat`.
Он добавит исправления и оригинальные ролики в ваш `coop.addon` (одинаково на всех ПК, чтобы у всех был один отпечаток аддона) и скопирует звук роликов вашего языка
(русский или английский) в `game\patches`. Ставят все: каждый игрок, хост и ПК с выделенным сервером.
Ролики делают аддон больше 4 ГиБ, а 32-битный движок такое не загружал, поэтому в релизе есть и исправление одного файла движка (`game\bin\xrCore.dll`),
сделанное с разрешения команды xrMPE; `install.bat` ставит его сам. Исправление есть и отдельной загрузкой, **`SoC_COOP_4GB_patch.zip`**, для тех, кому нужны просто аддоны больше 4 ГиБ.
Язык звука роликов выбирается при установке (по `voice_language` в `coop_settings.ltx`, иначе по языку лаунчера; `-Voice rus` или `-Voice eng` чтобы задать вручную).

The older steps below are for the first versions (1.0 to 1.3).

## Play in three steps

1. Install the [xrMPE launcher](https://github.com/M4dMurloc/xrMPE_Launcher_Release/releases)
   (version 0.9.x) and run it once so it downloads the game. Then get
   [Shadow of COOP 8.0](https://drive.usercontent.google.com/download?id=1Xl1hKfbzVOKQFEla3wB-5WokiL6FcpAx&export=download&authuser=0)
   (2.2 GB, official link from the [xrMPE wiki](https://xrmpe.fandom.com/ru/wiki/S.T.A.L.K.E.R._Shadow_of_COOP)),
   put `coop.addon` in `X-Ray Multiplayer Extension\gameddons\` and switch it on in the
   launcher's Add-ons tab.
2. Download `SoC_COOP_fixes.zip` from [Releases](../../releases), close the game and launcher,
   open `X-Ray Multiplayer Extension\game\addons\coop.addon` with 7-Zip and drag
   `zzz_soc_coop_fixes.db` into it. Back up `coop.addon` first.
3. Host or join as usual. **Every player needs the same patch**, or the server reports
   "Different versions". Starting a new game is recommended.

To uninstall, open `coop.addon` with 7-Zip again and delete `zzz_soc_coop_fixes.db`.

## What it fixes

- Crash when wearing or buying the bandit jacket or trench coat (`actor_hud_bandit_novice`).
- Freedom turning hostile at the Army Warehouses when Duty or anyone else shoots them; only a
  player hitting Freedom counts now.
- Getting stuck in dialogue with the Freedom squad leader (Skull).
- Traders refusing quest artifacts (both artifact versions are accepted).
- X16: Controller door staying locked after a death or a save load, levers that stop working,
  the lab autosave firing again.
- Cordon: main quest stuck after handing the flash drive to Sidorovich (cut-off dialogue,
  helicopter never flying), and Sidorovich's door closing on the second player.
- X18: Barman refusing the documents when players split them up.
- The Hunter's family shotgun never spawning.
- Arena: Arnie only saying "talk to the boss", and the teleport to Arnie on every Bar visit.
- Crash near the Sea Urchin and Kolobok artifacts on the DX9 renderers ("Shader 'models\water' not
  found in library"; their model used a shader that does not exist).
- **True ending unlocked:** crash entering the Monolith control bunker and the server crash when
  CNPP-2 loads, caused by breakable-object models the levels reference but never shipped. Small
  stand-in models fix this on all 18 levels.

## Optional: Sarcophagus FPS fix (for weaker PCs)

If your FPS drops hard in the Sarcophagus and CNPP Monolith fights, download
`SoC_COOP_fixes_sarc_fix.zip` from [Releases](../../releases) instead. It is the same
patch with the FPS fix built in, so it is still one file (`zzz_soc_coop_fixes.db`). It:

- keeps at most 12 corpses in the Sarcophagus (30 on other levels, instead of 300);
- can trim the Monolith waves in the Sarcophagus (`sarcophagus_wave_percent`, now 100 = off by default,
  because the patch sarcophagus_count already cut the Monolith to about original SoC numbers);
- lowers NPC sight range to 40-80 m (the add-on had 100-300 m);
- puts the Monolith on the lighter vanilla model (same armour).

The host can change the numbers in `sarcophagus_fps.txt` (in the zip) with Notepad: put it in
`X-Ray Multiplayer Extension\game\`, edit, restart the server. Only the host needs that file;
every player needs the same `.db`. Thanks to Прапор for testing the settings.

## Status

Tested automatically on the real game:

- All 18 levels boot on a dedicated server with a local client and no crash (`tools/boottest.ps1`).
- An in-engine self-test script checks every fix from inside the running game: 20 of 20 pass
  (`tests/coop_selftest.script`).

## Known issues

- FPS can still drop in very large Monolith firefights, mostly on the server. The optional
  Sarcophagus FPS fix helps a lot. If you host on the same PC you play on, capping the game's FPS
  to 60-90 (NVIDIA panel or vsync) also leaves more CPU for the server. Extra mods in a loose
  `gamedata` folder make it worse.

## How it works

`coop.addon` is a tar of X-Ray `.db` archives, and the launcher loads every `.db` inside it, so
the patch is one extra archive that overrides the files it fixes. The server checksums the
add-on, which is why every player needs an identical copy. Each fix lives in its own folder under
`patches/` with a `NOTES.md` explaining the root cause.

## Building and tests

```
python build.py                    # writes build/zzz_soc_coop_fixes.db
python build.py --sarcophagus-fps # same, with the optional Sarcophagus FPS fix
python build.py --player-limit 8 # opt-in capacity 8; original four-player default is unchanged
```

The optional capacity 8 profile builds from this repository, with no separate
game archive or private work paths. Package it with
`python tools/release.py 1.4.7 --player-limit 8 --no-boot`; it writes a separate
`_players8.zip` containing the DB, generated profile, Windows installer and server
selector. Installation patches only the exact supported local x86 DLL and keeps
verified originals; Python is unnecessary on Windows. All players need the same
package. Read the [English instructions](docs/PLAYER_LIMIT_8.en.md) or
[инструкцию по-русски](docs/PLAYER_LIMIT_8.ru.md) for prerequisites, backups,
rollback, session selection 1–8 and balance/saved-setting limits. The standard
release retains its four-file ZIP format.

Offline Python checks: `python -m unittest discover -s tests -p 'test_*.py'`.
The optional PowerShell installer tests use an original supported local DLL via
`COOP_TEST_DLL` and PowerShell via `COOP_PWSH` when outside PATH; they run on
temporary game copies, without launching the game.

`tools/` holds the archive reader (`xdb.py`, LZHUF index + LZO1X data), `extract.py`, `pack.py`,
a Lua block checker and model checkers. `tools/boottest.ps1 -Levels <level> ...` boots levels on
the dedicated server and reports OK or the crash text. `tests/` holds the in-engine self-test and
census scripts (test builds only, not in the release).

## Part of coop-anything

This is one of the projects in [coop-anything](https://github.com/cranebeaker/coop-anything).

## Credits

- **Shadow of COOP** by Arcanum Team. This patch only exists because of their add-on.
  Official pages: [VK](https://vk.com/shadowofcoop), [Discord](https://discord.gg/bE4D7G4jAK),
  [wiki page with downloads](https://xrmpe.fandom.com/ru/wiki/S.T.A.L.K.E.R._Shadow_of_COOP).
- **X-Ray Multiplayer Extension (xrMPE)** by the xrMPE team, launcher by M4dMurloc:
  [launcher releases](https://github.com/M4dMurloc/xrMPE_Launcher_Release/releases),
  [xrMPE wiki](https://xrmpe.fandom.com/ru/wiki/).
- **S.T.A.L.K.E.R.: Shadow of Chernobyl** by GSC Game World.

## License

## Help fix things / Помочь с исправлениями

[DEVELOPMENT_RU.md](DEVELOPMENT_RU.md) (Russian) explains how to build, check and test the patch, including with free AI models: the build
(`tools/release.py`), the offline checks and tests, `tools/inspect_game.py` (search the installed game, find missing sections, unpack saves) and the
in-game test harness `tools/stalker_xrmpe` (bots, Lua inside the running game).

[DEVELOPMENT_RU.md](DEVELOPMENT_RU.md): как собрать, проверить и протестировать патч, в том числе с бесплатными ИИ-моделями.

The tools and build scripts in `tools/`, `tests/` and `build.py` are MIT licensed (see
`LICENSE`). The files under `patches/` and `optional/` are edited versions of Shadow of COOP and
GSC Game World files and stay theirs; they are shared here only as a non-commercial fan fix.
If the Shadow of COOP or xrMPE authors want anything changed or taken down, open an issue and it
will be done.
