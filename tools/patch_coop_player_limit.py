#!/usr/bin/env python3
"""Экспериментальный cooperative cap 4→8 для одной версии xrGame.dll."""

import argparse
import hashlib
import os
from pathlib import Path
import stat
import sys
import tempfile


EXPECTED_SIZE = 7915520
EXPECTED_SHA256 = "ef430b5f39628dcd03a4dd6e44b114559549660dd06d3f3218296d1eee1c462e"
# File offsets, не VA. Никакого поиска совпадений по всей DLL.
PATCH_SITES = (
    (0x2BE435, bytes.fromhex("3c047607c6864914000004")),
    (0x2F1A71, bytes.fromhex("3c047607c686d045000004")),
)


class PatchError(ValueError):
    """Вход или путь не удовлетворяет ограниченному профилю патча."""


def validate_image(data: bytes) -> str:
    """Проверить размер, полный hash и обе исходные последовательности."""
    if len(data) != EXPECTED_SIZE:
        raise PatchError(
            f"Неподдерживаемый размер: {len(data)}; ожидается {EXPECTED_SIZE} байт."
        )
    digest = hashlib.sha256(data).hexdigest()
    if digest != EXPECTED_SHA256:
        raise PatchError(
            f"Неподдерживаемый SHA256: {digest}; ожидается {EXPECTED_SHA256}. "
            "Изменённая или уже пропатченная DLL не принимается."
        )
    for offset, signature in PATCH_SITES:
        if data[offset : offset + len(signature)] != signature:
            raise PatchError(f"Не совпадает исходная сигнатура по file offset {offset:#x}.")
    return digest


def patch_image(data: bytes) -> bytes:
    """После guards изменить ровно четыре immediate байта 04→08."""
    validate_image(data)
    result = bytearray(data)
    for offset, _signature in PATCH_SITES:
        result[offset + 1] = 8
        result[offset + 10] = 8
    return bytes(result)


def _plain_path(path: Path) -> Path:
    # Проверяем компоненты до нормализации '..', чтобы не скрыть symlink.
    absolute = Path(path)
    if not absolute.is_absolute():
        absolute = Path.cwd() / absolute
    for component in (*reversed(absolute.parents), absolute):
        if component.is_symlink():
            raise PatchError(f"Символические ссылки в путях запрещены: {component}")
    return Path(os.path.abspath(absolute))


def _read_image(path: Path) -> bytes:
    path = _plain_path(path)
    if not stat.S_ISREG(path.stat(follow_symlinks=False).st_mode):
        raise PatchError(f"Вход должен быть обычным файлом: {path}")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    with os.fdopen(os.open(path, flags), "rb") as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise PatchError(f"Вход должен быть обычным файлом: {path}")
        if info.st_size != EXPECTED_SIZE:
            raise PatchError(
                f"Неподдерживаемый размер: {info.st_size}; ожидается {EXPECTED_SIZE} байт."
            )
        return source.read(EXPECTED_SIZE + 1)


def patch_file(source: Path, output: Path) -> str:
    """Создать новый файл атомарно; исходник и существующие пути не менять."""
    source = _plain_path(source)
    output = _plain_path(output)
    if source == output:
        raise PatchError("Вход и выход совпадают; патч на месте запрещён.")
    if os.path.lexists(output):
        raise PatchError(f"Выход уже существует; перезапись запрещена: {output}")
    result = patch_image(_read_image(source))
    # mkstemp в том же каталоге: hard link публикует уже закрытый полный файл.
    # os.link не заменяет destination даже при гонке с другим писателем.
    fd, temporary_name = tempfile.mkstemp(prefix=".coop-cap8-", suffix=".tmp", dir=output.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as destination:
            destination.write(result)
            destination.flush()
            os.fsync(destination.fileno())
        try:
            os.link(temporary, output)
        except FileExistsError as error:
            raise PatchError(f"Выход уже существует; перезапись запрещена: {output}") from error
    finally:
        temporary.unlink(missing_ok=True)
    return hashlib.sha256(result).hexdigest()


def main(argv=None) -> int:
    # Русский отчёт не должен падать уже после создания файла из-за кодировки
    # консоли. В неподдерживаемой кодировке остаются читаемые ASCII escapes.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    parser = argparse.ArgumentParser(
        description=(
            "Экспериментальный cap 4→8: только статический анализ. "
            "Live-запуск с max_players >4 запрещён независимо от фактического "
            "числа подключённых игроков; необходим проверенный патч данных лобби."
        )
    )
    parser.add_argument("--input", required=True, type=Path, help="исходная официальная xrGame.dll")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--output", type=Path, help="новый файл; существующий путь запрещён")
    mode.add_argument("--check", action="store_true", help="только проверить исходник, не писать файлы")
    args = parser.parse_args(argv)
    try:
        if args.check:
            digest = validate_image(_read_image(args.input))
            print(f"Проверен официальный xrGame.dll: {EXPECTED_SIZE} байт; SHA256 {digest}")
            print("Обе исходные сигнатуры подтверждены. Файлы не создавались.")
        else:
            digest = patch_file(args.input, args.output)
            print(f"Создан новый файл для статического анализа: {args.output}")
            print(f"SHA256 {digest}; изменены ровно четыре immediate байта 04→08.")
        print("Только статический анализ.")
        print(
            "Live-запуск с max_players >4 запрещён независимо от фактического "
            "числа подключённых игроков; необходим проверенный патч данных лобби."
        )
        print("Обязателен отдельный проверенный патч данных лобби; он ещё разрабатывается.")
    except (PatchError, OSError) as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
