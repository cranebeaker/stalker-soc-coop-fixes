# Optional capacity 8 (addon 8.1, supported x86 DLL only)

The regular build/release stays at the original four-player capacity. The opt-in
package includes all normal selected fixes plus cooperative capacity 8 data:
18 level.game files, eight lobby cards and the cooperative/ammo count ceilings.
The number beside Ready counts connected players, rather than the session limit.
All host/client installations must use the same package and addon fingerprint.
This mode is experimental; lobby/network checks do not prove the whole campaign.

Build from this repository, without a separate game archive or private work paths:

```text
python build.py --player-limit 8
python tools/release.py 1.4.7 --player-limit 8 --no-boot
```

The release command writes `SoC_COOP_fixes_v1.4.7_players8.zip` in a separate
output directory. Nothing is uploaded or tagged. The optional installer self-test
needs PowerShell (`COOP_PWSH` if outside PATH) and a local unmodified supported DLL
(`COOP_TEST_DLL`, or the original DLL/backup under `XRMPE_GAME`). It tests copies
and a synthetic addon, never starts the game. `--no-installer-test` explicitly
skips it; the release report records that choice. The regular release format is
unchanged. No proprietary DLL is shipped in source or the ZIP.

Close the game and launcher, extract the package and run `installer/install.bat`.
Choose the `coop.addon` file or its game folder when prompted. Python is not needed
for Windows installation or the native server selector. The opt-in installer
verifies the package DB and exact DLL fingerprint/signatures, including a separate
dedicated DLL when present. It refuses unknown DLLs, extra mod DBs, broken backup
pairs and conflicting loose cooperative/UI/level.game files, including case variants
and linked directories. Restore the original addon or remove conflicting files
yourself; the installer does not silently discard an unrelated mod DB.

Supported original `bin/xrGame.dll`: 7,915,520 bytes, SHA256
`ef430b5f39628dcd03a4dd6e44b114559549660dd06d3f3218296d1eee1c462e`.
Patched SHA256:
`de8e7b892203abc0e7a667b1a56ad0844140f02a82461e8432edc6a3150f2860`.
Only four `04` immediates become `08`; no x64 or other xrMPE DLL is accepted.

The installer keeps `xrGame.dll.cap8-original` beside each DLL and
`coop.addon.cap8-original` plus its `.sha256` beside the addon. Keep them: an
already patched DLL without verified originals is refused. Allow space for a
full addon backup and a staged addon (several GB each). Data publishes before
DLLs; `coop_player_limit_profile.json` reaches the game root only after all
publishes succeed. Failures trigger rollback; `ROLLBACK INCOMPLETE` identifies
any file the OS prevented restoring and its recovery file. Stop using that
installation until those files have been restored. Do not delete recovery files.

To restore the original addon and DLLs, use the same opt-in package's
`installer/install.bat -Uninstall`. Backups are retained. This restores the full
addon as it existed before the first optional install, including an older standard
fix DB if one was present; install the desired standard package afterward.
Restoration refuses if the installed DB or base addon changed since installation;
your newer data is preserved for manual review. A regular package refuses to
install or uninstall while a capacity 8 marker or patched DLL remains. Use the
matching opt-in package to restore first. Alternate addon filenames are refused:
capacity 8 installation/restoration targets only `game/addons/coop.addon`.

Installer tests can skip their separate symlink scenario on Windows accounts
that lack permission to create symlinks; core install/restore/rollback tests still run.

For a native Windows host run `Start-Server-1-8.bat`. It asks for the game root and
session players 1–8; Enter chooses 5. Explicit example:

```text
Start-Server-1-8.bat -GamePath "D:\X-Ray Multiplayer Extension\game" -Players 5
python tools/start_coop_server.py --game "D:\X-Ray Multiplayer Extension\game" --players 5
```

Linux/Wine hosts use Python 3.10+ and an existing separate Wine prefix:

```text
python3 tools/start_coop_server.py --game /absolute/game --players 5 --wine /path/to/wine --wine-prefix /absolute/existing-prefix
```

The selector verifies the installed DLLs, actual DB SHA256 and physical archive
order `[gamedata.db0, gamedata.db1, zzz_soc_coop_fixes.db]` before launching;
icon/metadata can appear between DBs. Python uses the game-root JSON or an explicit
`--profile /path/profile.json`, retaining the previous fixed standalone profile
only when neither JSON is supplied nor installed. Python `--dry-run` prints the
command without verifying data or starting the game. PowerShell `-DryRun` verifies
data and prints its command. Saved host settings are never edited silently.

Capacity 8 is independent of session `maxplayers=N`. The server starts Cordon
with a private session and port 5495. Existing balance formulas count living
players. Other caps (`max_factor=2.5`, `max_extra_members=6`, one reinforcement
group per smart and the fixed damage multiplier) remain as before. A saved
`coop_settings.ltx` with an explicit ammo/player ceiling of 4 overrides the new
default; inspect your saved setting if that is unwanted. Normal loot tables have
not acquired a new player-count scaling formula.
