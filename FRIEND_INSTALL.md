# Friend install: Shadow of COOP fix patch v1.5.8

Easy route: ONE download, ONE file to run. Everybody who plays or hosts needs it, and every player must end with the same add-on fingerprint.

Host's fingerprint (what you must see at the end): **564999CA38D1**

## You (human)

1. Close the game and the xrMPE launcher.
2. Download `SoC_COOP_fixes_v1.5.8.zip` (1.4 GB):
   https://github.com/cranebeaker/stalker-soc-coop-fixes/releases/tag/v1.5.8
3. Unzip it anywhere, open the folder `installer`, double-click `install.bat`.
4. Wait until it prints `Installed.` and a line `Addon fingerprint ...: 564999CA38D1`.
5. Open the launcher and join the host. If the launcher updates the game later, run `install.bat` again.

Need about 6 GB free on the drive (zip, unzipped copy, and the add-on grows by about 1.5 GB). Windows only.
Do NOT use v1.5.0 (it can crash when a level loads) or v1.5.2 to v1.5.7 (older, other fingerprints). v1.5.8 is the one.

## Paste this to your Claude

```
Install the Shadow of COOP fix patch v1.5.8 on this PC and verify it. The game is the xrMPE launcher's "X-Ray Multiplayer Extension" with the Shadow of COOP mod (coop.addon). Do the steps in order and report each result. Do not publish or send anything anywhere.

1. Find the install folder (the one with xrmpe-launcher.exe, usually C:\X-Ray Multiplayer Extension, check other drives and Games\ and Program Files too). The game folder is <install>\game. If coop.addon is missing from <install>\game\addons, stop and tell me: the Shadow of COOP mod must be installed through the launcher first.
2. Make sure the game and the launcher are closed (tasklist: xrEngine.exe, xrmpe-launcher.exe). If one runs, ask me before closing it.
3. Check free disk space on that drive: need at least 6 GB. If less, tell me and stop.
4. Download https://github.com/cranebeaker/stalker-soc-coop-fixes/releases/download/v1.5.8/SoC_COOP_fixes_v1.5.8.zip (1.4 GB) into a new empty folder in my Downloads (curl.exe -L -o ... or gh release download v1.5.8 --repo cranebeaker/stalker-soc-coop-fixes). Check the file is about 1,502,845,014 bytes. Extract it into its own new empty folder (Expand-Archive).
5. Run the installer: powershell -NoProfile -ExecutionPolicy Bypass -File "<extracted>\SoC_COOP_fixes_v1.5.8\installer\install.ps1" -Db "<extracted>\SoC_COOP_fixes_v1.5.8\zzz_soc_coop_fixes.db"
   It patches game\bin\xrCore.dll (keeps xrCore.dll.orig), writes the fixes, the movies and the Full HD movies into coop.addon and copies the movie sound of my language into game\patches. If it says it cannot open coop.addon, the game or launcher is still open: close it and run again. If it says xrCore.dll is not the one the patch was made for, the launcher has a different game version: stop and tell me.
6. Verify, and show me the results:
   a. The installer printed "Installed." and the line "Addon fingerprint ... : 564999CA38D1". If the fingerprint differs, something is wrong (wrong add-on version or an extra file in coop.addon): tell me, do not continue.
   b. <game>\addons\coop.addon is 5,718,425,600 bytes.
   c. SHA-256 of <game>\bin\xrCore.dll starts with CAF069C239C4394B, and <game>\bin\xrCore.dll.orig exists and starts with 073172E1766BA125.
   d. <game>\patches contains zz_soc_cutscenes_voice_eng.db or zz_soc_cutscenes_voice_rus.db.
7. Tell me to open the launcher and join the host, and to run install.bat again if the launcher ever updates the game ("Different Versions" on joining means the fingerprint differs: rerun the installer).

If the game closes right after start, run <extracted>\...\xrcore_4gb\install_xrcore_patch.bat -Check and then without -Check to repair the engine patch. To remove everything: installer\install.bat -Uninstall (and xrcore_4gb\install_xrcore_patch.bat -Uninstall for the engine file).
```
