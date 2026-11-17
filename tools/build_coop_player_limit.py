"""Экспериментальный .db с верхним лимитом режима от 1 до 8 игроков.

Меняется только цифра max_players в cooperative_gamedata; по умолчанию 8.
Артефакт не подтверждает возможность подключения восьми игровых клиентов.
Live-запуск с max_players >4 запрещён независимо от фактического числа подключённых
игроков до установки проверенного обязательного патча данных лобби.
Генерация для offline/scratch анализа допустима.
Использование: python tools/build_coop_player_limit.py --game GAME --output NEW.db [--players 1..8]
Поддерживается стандартный resources → patches → addons/coop.addon без loose
gamedata и других дополнений. Порядок tar и сортировка имён должны давать
одинаковые байты итогового конфига; иначе сборка отклоняется.
"""
import argparse
import hashlib
import os
import re
import struct
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from stalker_xrmpe import xdb  # noqa: E402


CONFIG_PATH = "configs\\mp\\cooperative_game.ltx"
MAX_CONFIG_SIZE = 8 * 1024 * 1024
MAX_INDEX_SIZE = 64 * 1024 * 1024


class PatchError(ValueError):
    """Исходные данные не позволяют однозначно и безопасно собрать патч."""


def _validate_players(players):
    if type(players) is not int or not 1 <= players <= 8:
        raise PatchError("Верхний лимит players должен быть целым числом от 1 до 8.")


def patch_config(data, players=8):
    """Сохранить исходные байты, заменив единственный нужный ASCII-символ."""
    _validate_players(players)
    if b"\0" in data:
        raise PatchError("Конфиг содержит NUL; поддерживается текстовый LTX.")
    section = None
    sections = 0
    values = []
    offset = 0
    for raw_line in data.splitlines(keepends=True):
        code = raw_line.rstrip(b"\r\n").split(b";", 1)[0].strip(b" \t")
        if code.startswith(b"#"):
            raise PatchError("Директивы/include не поддерживаются: эффективное значение неизвестно.")
        if code.startswith(b"["):
            match = re.fullmatch(rb"\[([^\]]+)\]([ \t]*:[^\r\n]*)?", code)
            if not match:
                raise PatchError("Неизвестный синтаксис заголовка LTX.")
            section = match[1].strip().lower()
            if section == b"cooperative_gamedata":
                sections += 1
                if match[2]:
                    raise PatchError("Наследование cooperative_gamedata не поддерживается.")
        elif section == b"cooperative_gamedata":
            # Работаем с исходной строкой: позиции не должны зависеть от strip().
            line = raw_line.rstrip(b"\r\n").split(b";", 1)[0]
            if re.match(rb"[ \t]*max_players\b", line, re.IGNORECASE):
                match = re.fullmatch(
                    rb"[ \t]*max_players[ \t]*=[ \t]*(?P<value>[^ \t]*)[ \t]*",
                    line, re.IGNORECASE,
                )
                if not match:
                    raise PatchError("Неизвестная запись max_players в cooperative_gamedata.")
                values.append((offset + match.start("value"), match["value"]))
        offset += len(raw_line)
    if sections != 1:
        raise PatchError("Нужна ровно одна секция cooperative_gamedata; найдено %d." % sections)
    if len(values) != 1:
        raise PatchError("Нужен ровно один max_players в cooperative_gamedata; найдено %d." % len(values))
    position, value = values[0]
    if not re.fullmatch(rb"[1-8]", value):
        raise PatchError("Ожидался исходный max_players от 1 до 8, получено %r; патч не создан." % value)
    desired = str(players).encode("ascii")
    if value == desired:
        raise PatchError("max_players уже равен %d; новый DB не нужен и не создан." % players)
    return data[:position] + desired + data[position + 1:]


@dataclass(frozen=True)
class Archive:
    path: Path
    label: str
    offset: int
    size: int


@dataclass(frozen=True)
class BuildResult:
    output: Path
    source: str
    original_sha256: str
    patched_sha256: str
    players: int


def _validate_chunks(stream, archive):
    """Проверить границы до вызова upstream-декодера, который им доверяет."""
    position, end = archive.offset, archive.offset + archive.size
    indexes = 0
    while position < end:
        stream.seek(position)
        header = stream.read(8)
        if len(header) != 8:
            raise PatchError("Обрезан заголовок DB.")
        chunk, size = struct.unpack("<II", header)
        if position + 8 + size > end:
            raise PatchError("Чанк выходит за границу DB.")
        if chunk & 0x7FFFFFFF == 1:
            indexes += 1
            if size > MAX_INDEX_SIZE:
                raise PatchError("Индекс DB превышает поддерживаемые 64 MiB.")
            if chunk & 0x80000000:
                if size < 4:
                    raise PatchError("Обрезан сжатый индекс DB.")
                real = struct.unpack("<I", stream.read(4))[0]
                if real > MAX_INDEX_SIZE:
                    raise PatchError("Распакованный индекс DB превышает 64 MiB.")
        position += 8 + size
    if indexes != 1:
        raise PatchError("В DB нужен ровно один индекс; найдено %d." % indexes)


def _read_config(archive):
    """Прочитать единственную копию пути через существующие index/LZO API."""
    try:
        with archive.path.open("rb") as stream:
            if archive.offset + archive.size > os.fstat(stream.fileno()).st_size:
                raise PatchError("Обрезан файл архива.")
            _validate_chunks(stream, archive)
            found = []
            for name, real, stored, pointer in xdb.index(stream, archive.offset, archive.size):
                if real or stored:
                    if pointer < 8 or pointer + stored > archive.size:
                        raise PatchError("Данные %s выходят за границу DB." % name)
                if name.replace("/", "\\").lower() != CONFIG_PATH:
                    continue
                if not real or not stored or real > MAX_CONFIG_SIZE or stored > MAX_CONFIG_SIZE:
                    raise PatchError("Пустой или слишком большой cooperative_game.ltx (предел 8 MiB).")
                stream.seek(archive.offset + pointer)
                data = stream.read(stored)
                if len(data) != stored:
                    raise PatchError("Обрезаны данные cooperative_game.ltx.")
                if real != stored:
                    data = xdb.lzo1x(data, real, max_output=real)
                if len(data) != real:
                    raise PatchError("Неверная длина распакованного cooperative_game.ltx.")
                found.append(data)
            if len(found) > 1:
                raise PatchError("Неоднозначный путь cooperative_game.ltx внутри одного DB.")
            return found[0] if found else None
    except Exception as error:
        raise PatchError("%s: %s" % (archive.label, error)) from error


def _addon_archives(addon):
    """Порядок обычных tar-членов соответствует inspect_game.sources()."""
    out, names = [], set()
    try:
        with tarfile.open(addon, "r:") as stream:
            for member in stream:
                name = member.name.replace("\\", "/").lower()
                if name in names:
                    raise PatchError("Повторный tar-член: %s." % member.name)
                names.add(name)
                if member.offset_data + member.size > addon.stat().st_size:
                    raise PatchError("Обрезан tar-член %s." % member.name)
                if member.isdir():
                    continue
                if not member.isfile():
                    raise PatchError("Неподдерживаемый тип tar-члена: %s." % member.name)
                if re.search(r"\.db[0-5]?$", name):
                    if "/" in name:
                        raise PatchError("DB в подкаталоге tar не поддерживается: %s." % member.name)
                    out.append(Archive(addon, "coop.addon:" + member.name, member.offset_data, member.size))
                elif re.search(r"\.db[0-9]+$", name):
                    raise PatchError("Неподдерживаемый DB-суффикс: %s; допускаются .db и .db0…5." % member.name)
                elif name not in ("metadata.json", "icon.webp"):
                    raise PatchError("Неизвестный tar-член; его приоритет не определён: %s." % member.name)
    except (OSError, tarfile.TarError) as error:
        raise PatchError("Не удалось прочитать coop.addon: %s" % error) from error
    if not out:
        raise PatchError("coop.addon не содержит поддерживаемых .db/.db0…5.")
    return out


def _effective_config(game):
    """Следовать inspect_game и отказывать при конфликте с qa_build."""
    if not game.is_dir():
        raise PatchError("Каталог игры не найден: %s." % game)
    for entry in game.iterdir():
        if entry.name.lower() == "gamedata":
            raise PatchError("Loose gamedata не поддерживается: порядок перекрытий неизвестен.")
    addon = game / "addons" / "coop.addon"
    if not addon.is_file():
        raise PatchError("Не найден addons/coop.addon; нужна конкретная установка Shadow of COOP.")
    for path in addon.parent.iterdir():
        if path != addon and path.suffix.lower() == ".addon":
            raise PatchError("Другие addons не поддерживаются: %s; активный профиль неизвестен." % path.name)
    found = None
    for directory in ("resources", "patches"):
        root = game / directory
        if not root.exists():
            continue
        for path in sorted(root.iterdir()):
            if path.is_file():
                if re.search(r"\.db[0-9]+$", path.name.lower()) and not re.search(r"\.db[0-5]$", path.name.lower()):
                    raise PatchError("Неподдерживаемый DB-суффикс: %s; допускаются .db и .db0…5." % path.name)
                archive = Archive(path, directory + "/" + path.name, 0, path.stat().st_size)
                data = _read_config(archive)
                if data is not None:
                    found = (data, archive.label)
    archives = _addon_archives(addon)
    copies = [(archive, _read_config(archive)) for archive in archives]
    in_tar_order = found
    for archive, data in copies:
        if data is not None:
            in_tar_order = (data, archive.label)
    in_name_order = found
    for archive, data in sorted(copies, key=lambda item: item[0].label.removeprefix("coop.addon:")):
        if data is not None:
            in_name_order = (data, archive.label)
    if in_tar_order is None:
        raise PatchError("configs/mp/cooperative_game.ltx не найден в поддерживаемых источниках.")
    if in_tar_order[0] != in_name_order[0]:
        raise PatchError(
            "Порядок загрузки неоднозначен: порядок tar выбирает %s, сортировка имён — %s; патч не создан."
            % (in_tar_order[1], in_name_order[1])
        )
    return in_tar_order


def _run_tool(name, arguments):
    # --no-compress исключает load_lzo(), создание venv и установку пакетов.
    result = subprocess.run(
        [sys.executable, "-I", str(HERE / name), *map(str, arguments)],
        capture_output=True, text=True,
    )
    if result.returncode:
        raise PatchError("%s завершился с кодом %d: %s" % (name, result.returncode, (result.stdout + result.stderr)[-4000:]))


def build_patch(game, output, players=8):
    """Собрать и проверить новый DB вне игры; существующий путь не заменяется."""
    _validate_players(players)
    game, requested = Path(game).resolve(), Path(output).absolute()
    if os.path.lexists(requested):
        raise PatchError("Выходной путь уже существует; перезапись запрещена: %s." % requested)
    output = requested.resolve()
    if output.suffix.lower() != ".db":
        raise PatchError("Выходной файл должен иметь расширение .db.")
    if output.is_relative_to(game):
        raise PatchError("Выходной файл должен находиться вне каталога игры.")
    if not output.parent.is_dir():
        raise PatchError("Каталог для результата должен уже существовать: %s." % output.parent)
    data, source = _effective_config(game)
    patched = patch_config(data, players)
    try:
        with tempfile.TemporaryDirectory(prefix=".coop_player_limit_", dir=output.parent) as directory:
            temporary = Path(directory)
            stage = temporary / "gamedata"
            config = stage / "configs" / "mp" / "cooperative_game.ltx"
            config.parent.mkdir(parents=True)
            config.write_bytes(patched)
            packed = temporary / "patch.db"
            _run_tool("pack.py", [stage, packed, "--no-compress", "--quiet"])
            _run_tool("verify_db.py", [packed, stage])
            # Hard link публикует проверенный файл атомарно и отказывает при гонке.
            # Временный каталог на той же FS; при выходе удаляется только temp-link.
            os.link(packed, output)
    except OSError as error:
        raise PatchError("Не удалось создать новый DB без перезаписи: %s" % error) from error
    return BuildResult(output, source, hashlib.sha256(data).hexdigest(), hashlib.sha256(patched).hexdigest(), players)


def main(argv=None):
    # Русский отчёт должен работать и при перенаправлении в Windows-консоли.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", required=True, type=Path, help="Стандартный каталог игры с addons/coop.addon")
    parser.add_argument("--output", required=True, type=Path, help="Новый .db вне каталога игры; родительский каталог существует")
    parser.add_argument("--players", type=int, choices=range(1, 9), default=8, help="Верхний лимит режима 1–8, по умолчанию 8; фактическое число в сеансе выбирается отдельно")
    args = parser.parse_args(argv)
    try:
        result = build_patch(args.game, args.output, args.players)
    except (PatchError, OSError) as error:
        print("Патч не создан: %s" % error, file=sys.stderr)
        return 1
    print("Создан экспериментальный DB для offline/scratch анализа: %s" % result.output)
    print("Live-запуск с max_players >4 запрещён независимо от фактического числа подключённых игроков до установки проверенного обязательного патча данных лобби.")
    print("Источник: %s:%s" % (result.source, CONFIG_PATH))
    print("SHA256 исходного конфига: %s" % result.original_sha256)
    print("SHA256 изменённого конфига: %s" % result.patched_sha256)
    print("В созданном DB задан верхний лимит режима: max_players = %d (изменён один байт)." % result.players)
    print("Фактическое число игроков при запуске выбирается отдельно и должно быть не выше этого лимита.")
    print("Подключение восьми клиентов и работа игровых сценариев не проверены.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
