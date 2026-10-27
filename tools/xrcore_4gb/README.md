# xrCore.dll patch: add-ons larger than 4 GiB

Русская версия ниже / Russian version below.

## English

xrMPE loads a `.addon` (a tar of X-Ray `.db` archives). The engine is 32-bit and the add-on loader still kept some file offsets in 32 bits, so an add-on larger than 4 GiB
(4,294,967,296 bytes) crashed at start (`R_ASSERT` in `CLocatorAPI::LoadArchive`: the archive header was read from a wrapped offset). Shadow of COOP 8.1 plus the fix patch fills the limit
(about 11 MB were left), so nothing more could be added to the add-on.

The xrMPE team agreed to this fix. The loader was already half 64-bit (the chunk reader uses `SetFilePointerEx`, `struct file` has a 64-bit position, `file_from_addon` calls
`MapViewOfFile` with the high offset). This patch fixes the places that still used 32 bits. It changes only `game\bin\xrCore.dll`.

What you get:
* an add-on can be larger than 4 GiB (tested at 5.35 GiB with members at 4.2 GiB, straddling 4 GiB and above it, and the last member at the very end of the file);
* video textures (.ogm) and other stream-read files work inside such an add-on;
* an add-on below 4 GiB behaves exactly as before.

Limits: one tar member (one `.db`) must stay below 2 GiB; plain (non-`.db`) files stored directly in the tar above 4 GiB are not supported; every player, the host and the dedicated
server need the patched `xrCore.dll` (an unpatched engine crashes at start with such an add-on). A launcher update can restore the original `xrCore.dll`: run the patch again.

### Use (players)

Download `SoC_COOP_4GB_patch.zip` from the release page, close the game, the dedicated server and the launcher, run `install_xrcore_patch.bat`. It checks the SHA-256 of your
`xrCore.dll` (it must be the xrMPE 0.9 file), keeps a copy as `xrCore.dll.orig`, applies the byte changes and verifies the result.
`install_xrcore_patch.bat -Check` shows the state, `-Uninstall` restores the original. The patch contains only the byte changes, not xrMPE's file.

### Files

| File | What |
|---|---|
| `build_patch.py` | builds the patched DLL from the original (python 3, `pip install capstone keystone-engine pefile`): `python build_patch.py xrCore.dll xrCore.patched.dll` prints a listing of every new instruction |
| `make_applier.py` | makes `install_xrcore_patch.ps1/.bat` (the standalone installer, no Python needed) from the original and the patched DLL |
| `ghidra/*.java` | Ghidra headless scripts used to find the code (decompile and disassemble functions by name, cross references, check that no jump lands inside a patched range) |
| `test/gen_bigtest.py` | in-game probe: opens files of cutscene dbs through the engine and compares their bytes with the source |
| `test/mdmp.py` | prints the exception and module/offset of an x86 minidump |
| `test/emu_calc_test.py`, `test/emu_register_test.py` | run the real new machine code in the Unicorn emulator against a 64-bit reference (`pip install unicorn pefile`) |
| `test/run_inst_test.py` | end-to-end test of `installer\install.ps1` on a synthetic add-on above 4 GiB (sparse files, almost no disk) |

### How it works (for developers)

The new code lives in two new sections: `.xpat` (code, read+execute) and `.xpad` (two dwords and a 32 entry table, read+write). Everything is position independent (the DLL uses ASLR).
Twelve places of the original code are replaced by a `JMP` into `.xpat` plus NOPs; the original bytes are checked before patching, the rest of the file is unchanged.

| Place | Problem | Change |
|---|---|---|
| `ProcessAddon` | tar position is a `u32` | a wrap counter `H`; the position saved for each member is `position / 512` (members start on 512 byte boundaries), 32 bits for up to 2 TiB, stored in `archive.offset` as before |
| `ProcessArchive`, `LoadArchive` (chunk open) | `open_chunk(hFile, id, offset_low, 0)` | push `(offset << 9)` as low and high |
| `LoadArchive` (file list) | `file.ptr64 = entry.ptr + archive.offset` computed in 32 bits, high half hard-coded 0 | 64-bit sum, high half passed to `Register` |
| `file_from_addon(IReader)` | view end clamped to the low 32 bits of the file size | `GetFileSize(hFile, &high)` and a 64-bit clamp |
| `CStreamReader::construct/map/remap/advance` | window computed with `u32` start offset and `u32` archive size | a shared routine `calc` for readers found in a table; `file_from_archive(CStreamReader)` registers the reader (start offset high dword, archive size high dword) before `construct`, `destroy` unregisters it |

A source level fix in `xray16_xrMPE` is shorter: make `archive::offset` and `archive::size` `u64`, keep the tar position `u64` in `ProcessAddon`, pass `u64` to `ProcessArchive` and
`open_chunk`, compute `file::ptr64` in 64 bits, and make `CStreamReader::m_start_offset`, `m_file_size` and `m_archive_size` `u64` (`MapViewOfFile` already takes the high dword). `fseek` of a member
larger than 2 GiB needs `_fseeki64`.

### Tested

* In the game, on a 5.35 GiB add-on (Shadow of COOP + fix patch + the cut-scene databases, members at 4.2 GiB, straddling 4 GiB and above it, the last one at the end of the file):
  the game loads the level, the engine opens files from the databases above 4 GiB and the bytes read match the source files (26 files compared byte by byte; Russian and English sound,
  standard and Full HD movies), and the Full HD intro movie, streamed from a database that straddles 4 GiB, starts without errors. With the original `xrCore.dll` the same add-on crashes at start.
* On the real add-on of the v1.5.0 release (4.05 GiB, the movie database straddles 4 GiB): the game loads all four databases, passes the add-on version check and reaches the lobby.
* The machine code of the new routines runs in an emulator against a 64-bit reference (`test/emu_calc_test.py`: 19,702 random readers, 542 of them with a window crossing a 4 GiB multiple;
  `test/emu_register_test.py`: registration, removal, full table) and `test/run_inst_test.py` runs the installer on a synthetic 4.4 GB add-on (refusal without the patch, automatic patch,
  byte-identical members above 4 GiB, languages, uninstall).

## Русский

xrMPE грузит `.addon` (tar с архивами X-Ray `.db`). Движок 32-битный, а загрузчик аддонов хранил часть смещений в 32 битах, поэтому аддон больше 4 ГиБ (4 294 967 296 байт) падал при запуске
(`R_ASSERT` в `CLocatorAPI::LoadArchive`: заголовок архива читался по "завернувшемуся" смещению). Shadow of COOP 8.1 с патчем исправлений уже упирается в предел (оставалось около 11 МБ),
так что добавить в аддон было нечего.

Команда xrMPE согласна на это исправление. Загрузчик уже был наполовину 64-битным; патч исправляет оставшиеся места. Меняется только `game\bin\xrCore.dll`.

Что даёт: аддон может быть больше 4 ГиБ (проверено на 5,35 ГиБ), видео (.ogm) и другие потоковые файлы работают внутри такого аддона, аддон меньше 4 ГиБ ведёт себя как раньше.

Ограничения: один `.db` внутри аддона меньше 2 ГиБ; обычные (не `.db`) файлы в tar выше 4 ГиБ не поддерживаются; патч нужен всем игрокам, хосту и выделенному серверу (без патча игра при запуске падает).
После обновления лаунчером `xrCore.dll` может вернуться оригинальный: запустите патч снова.

Игрокам: скачайте `SoC_COOP_4GB_patch.zip`, закройте игру, сервер и лаунчер, запустите `install_xrcore_patch.bat`. Он проверяет SHA-256 вашего `xrCore.dll` (должен быть файл xrMPE 0.9), сохраняет
копию `xrCore.dll.orig`, применяет изменения и проверяет результат. `-Check` показывает состояние, `-Uninstall` возвращает оригинал. В патче только изменения байтов, самого файла xrMPE нет.
