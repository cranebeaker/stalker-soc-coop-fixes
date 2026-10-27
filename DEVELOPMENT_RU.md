Всем привет! Если у вас есть классная и продуманная идея для кооп-мода, но нет доступа к подписке Claude/Codex (или нет возможности платить за платные модели), над ней можно работать и бесплатно:

Скачайте opencode и пользуйтесь бесплатными моделями. На момент написания одни из лучших:
Big Pickle («стелс»-модель, которую гайд от 13 октября назвал лучшей для сложных задач по программированию), DeepSeek V4 / V4.1 Flash, GLM 5.3 Flash, MiMo-V2.5, Nemotron 3 и LongCat для повседневной работы с агентом. По одному источнику, 6 октября в Zen было 11 бесплатных моделей для кода.

Запустите opencode и напишите:
Read https://github.com/cranebeaker/coop-anything and follow AGENTS.md.
Хочу играть в <игра> в кооперативе с друзьями.

Если кто-то здесь уже работает над кооп-модом (или это один из моих, конечно), вы можете помочь с разработкой! Просто напишите в чат, и я помогу, если хотите поработать над одним из кооп-модов, которые уже в процессе.

---

# Как чинить и дорабатывать патч Shadow of COOP (для людей и для ИИ-агентов)

Здесь всё, чем собирается, проверяется и тестируется патч исправлений для Shadow of COOP 8.1 (xrMPE 0.9). Всё работает на Windows, нужны Python 3 и PowerShell. Если работаете через агента (opencode и т.п.), дайте ему прочитать этот файл, `README.md` и `NOTES.md` нужного патча.

Для агента можно начать так:

```
Read DEVELOPMENT_RU.md and README.md of https://github.com/cranebeaker/stalker-soc-coop-fixes, then the NOTES.md of the patch you touch.
Bug: <текст ошибки или описание>. Find the cause, fix it in patches\<patch>, run the offline tests and tools\release.py <version> --no-boot.
```

## 1. Как устроен репозиторий

| Папка | Что там |
|---|---|
| `patches\<имя>\gamedata\...` | 82 патча. Каждый кладёт свои файлы по путям игры (`configs`, `scripts`, `meshes`, `sounds` ...). Один файл игры может лежать только в одном патче. |
| `patches\<имя>\NOTES.md` | Что патч делает, почему, какие флаги и файлы трогает, как проверен. Читайте перед правкой. |
| `patches\<имя>\tests\` | Офлайн-тесты: настоящий скрипт патча запускается в Lua 5.1 с заглушкой движка (без игры). |
| `patches\<имя>\tools\` | Генераторы: многие файлы не правятся руками, а пересобираются скриптом (например `make_tm_coop_l01_escape.py`). Если в NOTES.md написано, что файл генерируется, правьте генератор. |
| `installer\` | `install.bat` / `install.ps1` (ставят патч в `coop.addon` одинаково на всех ПК) и списки изменений `changes_<версия>.en/ru.txt`. |
| `cutscene_pack\` | Отдельный пакет роликов (`build_cutscene_pack.py`, `install_cutscenes.ps1`). |
| `tools\` | Сборка, проверки, разбор архивов игры (ниже). |
| `tools\stalker_xrmpe\` | Тестовый стенд: запускает настоящую игру с ботами и даёт выполнять Lua внутри игры. |

Как патч попадает в игру: `build.py` собирает все патчи в один архив `zzz_soc_coop_fixes.db`, а `install.ps1` дописывает его в конец `coop.addon`. Скрипты `.dscript` движок xrMPE дописывает к одноимённому `.script`, поэтому так можно менять и базовые скрипты, не копируя их целиком.

## 2. Сборка

```
python -I tools\release.py 1.4.4 --no-boot
```

Шаги: проверка конфликтов файлов между патчами, проверка Lua-строк, сборка `build\release_v1.4.4\stage\gamedata` и `zzz_soc_coop_fixes.db`, проверка лимита 4 ГБ (`coop.addon` вместе с патчем не может быть больше 4 GiB, иначе игра не прочитает архив), упаковка zip с установщиком, проверка установщика на тестовом файле. В конце `RELEASE OK` и путь к zip. Без `--no-boot` ещё загружается каждый уровень в настоящей игре (долго, нужна игра и место на диске).

Установка на свой ПК: `build\release_v<версия>\SoC_COOP_fixes_v<версия>\installer\install.bat`. В конце печатается отпечаток (fingerprint): он должен совпадать у всех игроков, иначе «другая версия» при подключении.

## 3. Проверки (быстро, без игры)

| Команда | Что ловит |
|---|---|
| `python -I tools\check_conflicts.py` | два патча кладут один и тот же файл (побеждает последний, правка первого молча теряется) |
| `python -I tools\check_lua_escapes.py` | ошибки экранирования в Lua-строках |
| `python -I tools\luabal.py <file.script>` | непарные `function/if/do ... end` |
| `python -I tools\verify_db.py <file.db> <stage\gamedata>` | архив читается, каждый файл совпадает с исходником байт в байт |
| `python -I tools\budget.py` | сколько места осталось до 4 GiB |
| `python -I tools\check_ogf_includes.py` | модели ссылаются на существующие файлы |
| `python -I tools\inspect_game.py models build\release_v<версия>\stage\gamedata` | модели NPC ссылаются на секции урона, которых нет (вылет `Can't open section ...`) |

Офлайн-тесты патчей (32 файла): сначала `pip install lupa`, потом например

```
python patches\agroprom_soc\tests\docs_case_mock_test.py
python patches\agroprom_soc\tests\agroprom_chain_mock_test.py
```

Тест печатает `PASS` / `FAIL` по каждой проверке и итог. Тесты запускаются без `-I` (иначе Python не видит установленный lupa).

## 4. Как найти причину ошибки

Лог игры: `X-Ray Multiplayer Extension\game\_appdata_\logs\xray_<имя пользователя Windows>.log` (у выделенного сервера `_appdata_server\logs`). При вылете там есть `Expression`, `Description`, `Arguments`: это первое, что нужно агенту.

`tools\inspect_game.py` ищет прямо в установленной игре (базовые архивы xrMPE и все архивы внутри `coop.addon`), ничего не распаковывая:

```
python -I tools\inspect_game.py grep "kombez_antigas"                 все строки во всех скриптах и конфигах
python -I tools\inspect_game.py grep "device_torch" --ext .script     только в скриптах
python -I tools\inspect_game.py sections wpn_pb killer_outfit         где определена секция (MISSING = её нет в игре) и её русское имя
python -I tools\inspect_game.py extract out "configs\creatures\actor.ltx"   копия файла из каждого архива, чтобы сравнить
python -I tools\inspect_game.py save <file.scop | папка> [текст]     распаковать сохранение, найти в нём текст
```

Если игра не в `C:\X-Ray Multiplayer Extension\game`, задайте переменную `XRMPE_GAME`.

Примеры реальных ошибок, найденных так:
- вылет на Свалке `Can't open section 'kombez_antigas_damage'`: `grep` нашёл модели охраны Долга, которые ссылались на несуществующую секцию урона;
- два кейса с документами на Агропроме: логика зон (restrictor) в этом моде работает на машине КАЖДОГО игрока, поэтому `spawn_object` в зоне создавал по кейсу на игрока. Всё, что должно случиться один раз, делается на сервере (`OnServer()`, тик через `level.add_call`);
- не работали фонарик и ПНВ: в коопе нужен предмет `mp_device_torch`, а не `device_torch`.

## 5. Тесты в настоящей игре (`tools\stalker_xrmpe`)

Стенд запускает игру в окне 800x600 без звука, со своей папкой настроек (`_appdata_qa_*`), и не трогает ваши сохранения и настройки. Перед запуском закройте свою игру. Каждый слот делает копию мода `addons\qalane<N>.addon` (4,2 ГБ), так что нужно место на диске (стенд не запускается при свободном месте меньше 4 ГБ).

Живая сессия: игра запущена, вы выполняете Lua внутри неё:

```
cd tools\stalker_xrmpe\live
powershell -ExecutionPolicy Bypass -File start_live.ps1 -Map coop_l01_escape -Mode listen -Clients 1 -DbFile <путь к zzz_soc_coop_fixes.db> -Name dbg
powershell -ExecutionPolicy Bypass -File lua.ps1 -Name dbg -Role A "return level.name()"
powershell -ExecutionPolicy Bypass -File save_live.ps1 -As my_save -Name dbg
powershell -ExecutionPolicy Bypass -File stop_live.ps1 -Name dbg
```

В режиме `listen` клиент `A` и есть хост (сервер + игрок). Помощники внутри игры: `live.travel("bar")`, `live.tp`, `live.spawn`, `live.inv`, `live.census` и другие, см. `live\README.md` и `lua\QA_LIB.md`. Пример реальной проверки: `db.actor:item_in_slot(10):section()` показал, какой фонарик у игрока, а `enable_torch(true)` проверил, что сам предмет исправен.

Автотест двух клиентов: `run_coop.ps1 -Map coop_l01_escape -Owner my -Hooks my_hooks.lua` (хост и второй клиент, боты появляются сами, итог `RESULT: PASS|FAIL`). Свои проверки пишутся как Lua-хуки, примеры в `lua\example_hooks.lua` и `patches\*\tests\*_hooks.lua`.

Если игровой процесс завис и не закрывается (виден в диспетчере задач с памятью в сотни КБ), он держит свою копию `qalane<N>.addon` до перезагрузки. Тогда `start_live.ps1 -ForceLane 1` использует другую копию.

## 6. Правила, чтобы ничего не сломать

- Не меняйте `spawns\all.spawn` и данные уровней в обычном обновлении: тогда перестают работать сохранения игроков.
- Один файл игры, один патч. Если файл уже есть в другом патче, правьте его там (или через генератор этого патча).
- Конфиги `.ltx` и тексты `.xml` в кодировке cp1251 (Windows-1251). Сохраняйте в ней, иначе русский текст сломается.
- Всё, что должно случиться один раз на всех (выдать предмет, создать NPC, дать флаг), делайте на сервере. Логика зон и диалогов работает у каждого игрока отдельно.
- Сохранения кооператива возвращают персонажа по нику игрока: не завязывайтесь на ник.
- Каждое исправление: строка в `installer\changes_<версия>.en.txt` и `.ru.txt`, запись в `NOTES.md` патча, по возможности офлайн-тест.
- Перед выпуском: `tools\release.py <версия>` должен закончиться `RELEASE OK`.

## 7. Как прислать исправление

Сделайте fork репозитория на GitHub, внесите правку, приложите вывод `release.py` и тестов, откройте Pull Request. Или опишите ошибку в Issues: текст из лога (`Expression` / `Arguments`), уровень, что делали, сколько игроков.

## 8. Аддон больше 4 ГиБ и сборка релиза v1.5

Раньше `coop.addon` упирался в предел 4 ГиБ 32-битного движка. Теперь есть патч движка и установщик, которому предел не мешает. Всё в `tools\xrcore_4gb` (описание: `tools\xrcore_4gb\README.md`).

- `python tools\xrcore_4gb\build_patch.py <оригинальный xrCore.dll> <пропатченный xrCore.dll>` собирает пропатченный движок и печатает листинг всего нового кода
  (нужны `pip install capstone keystone-engine pefile`). Код патча лежит в двух новых секциях DLL (`.xpat2` код, `.xpad2` данные) и позиционно независим (в DLL включён ASLR).
- `python tools\xrcore_4gb\make_applier.py <оригинал> <пропатченный> <папка>` делает `install_xrcore_patch.bat/.ps1`, установщик без Python: в нём только изменения байтов, не файл xrMPE.
- `python tools\release_bundle.py 1.5.0 --xrcore-orig <оригинальный xrCore.dll>` собирает релиз: `SoC_COOP_fixes_v1.5.0.zip` (установщик + исправления + ролики + патч движка)
  и `SoC_COOP_4GB_patch.zip` (только патч движка). Ничего не публикует.
- `installer\install.ps1` кладёт в аддон несколько файлов подряд (исправления, затем ролики) в фиксированном порядке и с одинаковыми заголовками tar, поэтому отпечаток аддона у всех одинаковый.
  Если аддон станет больше 4 ГиБ, а `xrCore.dll` не пропатчен, установщик сам ставит патч движка (или отказывается с ключом `-NoEnginePatch`). Звук роликов (русский или английский) он кладёт в `game\patches`:
  язык у каждого игрока свой и на отпечаток аддона не влияет.

Проверки патча без игры (нужны `pip install unicorn pefile`):

```
python tools\xrcore_4gb\test\emu_calc_test.py <пропатченный xrCore.dll>
python tools\xrcore_4gb\test\emu_register_test.py <пропатченный xrCore.dll> <listing.txt от build_patch.py>
python tools\xrcore_4gb\test\run_inst_test.py <корень репозитория> <оригинальный xrCore.dll> <рабочая папка> <папка с install_xrcore_patch.ps1>
```

Первые два запускают настоящий машинный код патча в эмуляторе и сравнивают с обычной 64-битной арифметикой. Третий проверяет установщик на искусственном аддоне 4,4 ГБ из разрежённых файлов (почти не занимает место).
Проверка в игре: `tools\xrcore_4gb\test\gen_bigtest.py` делает скрипт-зонд, который читает файлы из баз внутри аддона через движок и сравнивает байты с исходными файлами (`lua.ps1 ... "return xrbigtest.probe(1, true)"`;
закрывать файлы из этого скрипта (`r_close`) нельзя, команда зависает, это особенность привязки Lua).
Если игра не запускается с `Unable to initialize SDL` (`SDL_Init(SDL_INIT_VIDEO) == 0`), у Windows нет дисплея (сеанс заблокирован или отключён): это не ошибка патча.
