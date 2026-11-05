# Профиль на 8 игроков / Eight-player build profile

## Русский

Из корня checkout:

```console
python build.py --player-limit 8
```

Сборщик использует только файлы репозитория; ZIP, `coop.addon`, каталог `work/` и установленная игра для сборки не нужны. Сжатие выполняется штатным `tools/pack.py` с `python-lzo` (см. его инструкции по установке зависимости). Результат: `build/zzz_soc_coop_fixes.db` и соседний `build/coop_player_limit_profile.json`. Для другого каталога укажите путь с тем же именем DB. Без `--player-limit 8` обычная четырёхместная сборка не создаёт, не удаляет и не меняет профиль. Не устанавливайте оставшийся профиль рядом с DB другой сборки: fingerprint должен соответствовать.

В `gamedata/` находятся 19 небольших игровых файлов: 18 `level.game` и UI лобби. Это изменённые данные Shadow of COOP / GSC Game World, на них **не распространяется MIT**; см. корневой `LICENSE`. MIT покрывает сборщик, инструменты и тесты в указанных там каталогах. Эти условия такие же, как у остальных игровых файлов `patches/` и `optional/` проекта.

`manifest.json` фиксирует точный набор путей, SHA256 каждого optional asset и ожидаемые baseline SHA256 текущей stage для Кордона и Саркофага. Их assets созданы из репозиторных `patches/cordon` и `patches/sarcophagus_count` проверенным `tools/build_coop_lobby_data.py:patch_level`, с восемью компактными transforms; все остальные chunks, metadata точек и существующие исправления сохранены. Ещё 16 карт подготовлены из оригинальных данных addon 8.1; UI использует компактный шаблон с областью чата. Эти подготовленные файлы уже включены в репозиторий: обычная сборка не повторяет извлечение данных.

Профиль применяется после обычных и выбранных optional overlays. До первой записи он проверяет hashes и весь набор путей, отсутствие symlink и неожиданных файлов, точный baseline двух репозиторных карт и отсутствие остальных 16 карт/UI в stage. Если upstream добавит или изменит такой map/UI файл, сборка явно откажет: сначала перенесите новые исправления в optional asset и обновите manifest. Не меняйте hash только ради прохождения проверки. Сочетания с `--sarcophagus-fps` и `--mm-style=...` разрешены, пока они не создают конфликтующий map/UI; при конфликте действует такой же отказ. `--skip=...`, исключающий необходимые baseline/config patches, также может сделать профиль несовместимым.

В текущих итоговых конфигах заменяются только цифры `[cooperative_gamedata] max_players` и `[ammo] max_players` с 4 на 8; значение 8 принимается повторно. Остальные байты и настройки сохраняются. Сохранённый пользовательский `coop_settings.ltx` с `[ammo] max_players=4` имеет приоритет и не изменяется сборщиком: владелец сервера выбирает его значение самостоятельно. Пределы врагов `max_factor=2.5`, `max_extra_members=6`, одна группа подкрепления на smart и статический player damage multiplier 1.5 сохраняются. Сборка не добавляет формулу добычи по числу игроков.

Машинный профиль описывает ёмкость клиента 8, addon 8.1, fingerprints поддерживаемого движка и SHA256/размер фактически собранного DB. Он нужен опциональному установщику и запускателю; сам build DLL не патчит. Чужой либо неподдерживаемый файл профиля не перезаписывается. Профиль записывается после упаковки, проверки чтения DB и штатной проверки размера addon ниже 4 GiB; `--no-budget-check` остаётся явным существующим обходом проверки размера.

Структурные проверки и успешная сборка не доказывают все игровые сценарии. Полная проверка восьми клиентов, UI/чата, Ready, входа в мир и баланса выполняется отдельно; готовность gameplay следует оценивать по её отчёту.

## English

Run `python build.py --player-limit 8` from the checkout root. The build uses checked-in files only: no ZIP, `coop.addon`, local `work/` directory or installed game is required. The existing packer uses `python-lzo` for compression. Outputs are `build/zzz_soc_coop_fixes.db` and the adjacent optional `coop_player_limit_profile.json`; custom output directories must retain that DB filename. A default build leaves any profile untouched, so distribute a profile only with the DB whose fingerprint it contains.

The 19 files under `gamedata/` (18 maps and one lobby UI XML) are edited Shadow of COOP / GSC Game World data and **are not MIT licensed**. The root `LICENSE` covers build tools/tests only and explicitly excludes `patches/` and `optional/` game data.

The strict asset manifest validates all paths and hashes before changing the private build stage. Cordon and Sarcophagus were generated from the existing repository fixes using the tested `patch_level` core, preserving unrelated chunks and point metadata. Sixteen other maps were prepared from addon 8.1 data. No extraction or scratch input is needed during an ordinary build. If upstream changes either baseline map, or introduces any other map/UI override covered by the profile, the build refuses and asks the maintainer to merge the changes into the optional assets and refresh the manifest. Review the changes instead of merely replacing a hash. FPS/menu options remain usable when their resulting stage is compatible; conflicting overlays fail clearly.

Only the numeric limits in the current `[cooperative_gamedata]` and `[ammo]` sections change from 4 to 8 (already-8 values are accepted). Other bytes/settings stay intact. Existing host `coop_settings.ltx` values take precedence: an explicit ammo cap of 4 remains the host's choice. Enemy scaling caps (2.5 factor, six extra members and one reinforcement squad per smart), static player damage 1.5 and existing loot behavior remain unchanged.

The generated profile binds client capacity 8/addon 8.1 and the supported engine fingerprints to the actual DB size/SHA256. It is for the optional installer/launcher; build does not patch an installed DLL. Unknown profiles are refused before packing. The profile is written after normal packing/readback and addon-size validation (the existing explicit `--no-budget-check` switch still bypasses the latter). Data/build checks do not certify all eight-client gameplay; consult the separate runtime verification report for UI/chat, Ready, world entry and balance coverage.
