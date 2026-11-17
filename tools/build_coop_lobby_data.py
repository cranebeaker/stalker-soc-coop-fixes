#!/usr/bin/env python3
"""Сборка новой stage level.game из 18 оригиналов и явного layout-профиля.

Чистый patch_level переносим; атомарная публикация каталога требует Linux
renameat2(RENAME_NOREPLACE). Координат по умолчанию у инструмента нет.
"""

import argparse
import ctypes
import errno
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import struct
import sys
import tempfile


TARGET_CHUNK = 0x2000
RECORD_SIZE = 29
MAP_COUNT = 18


class PatchError(ValueError):
    """Вход или путь не соответствует явно поддерживаемому контракту."""


def _chunks(data: bytes, label: str):
    """Строго разобрать границы, не интерпретируя неизвестные payload."""
    chunks = []
    identifiers = set()
    offset = 0
    while offset < len(data):
        if len(data) - offset < 8:
            raise PatchError(f"{label}: усечён заголовок chunk по смещению {offset}.")
        identifier, size = struct.unpack_from("<II", data, offset)
        end = offset + 8 + size
        if end > len(data):
            raise PatchError(f"{label}: payload chunk {identifier:#x} выходит за границы.")
        if identifier in identifiers:
            raise PatchError(f"{label}: повторяется ID chunk {identifier:#x}.")
        identifiers.add(identifier)
        chunks.append((identifier, offset, data[offset + 8 : end]))
        offset = end
    return chunks


def _actor_bytes(actor_transforms):
    if not isinstance(actor_transforms, (list, tuple)) or len(actor_transforms) != 8:
        raise PatchError("Требуются ровно 8 явных actor transforms.")
    result = []
    for index, transform in enumerate(actor_transforms, start=1):
        if not isinstance(transform, dict) or set(transform) != {"position", "rotation"}:
            raise PatchError(f"Actor {index}: нужны только поля position и rotation.")
        values = []
        for name in ("position", "rotation"):
            vector = transform[name]
            if not isinstance(vector, (list, tuple)) or len(vector) != 3:
                raise PatchError(f"Actor {index}: {name} должен содержать 3 числа.")
            for number in vector:
                if isinstance(number, bool) or not isinstance(number, (float, int)):
                    raise PatchError(f"Actor {index}: {name} содержит не число.")
                try:
                    value = float(number)
                    if not math.isfinite(value):
                        raise ValueError("non-finite")
                    # Проверяем именно представимость в дисковом f32.
                    struct.pack("<f", value)
                except (OverflowError, ValueError, struct.error) as error:
                    raise PatchError(f"Actor {index}: требуется конечное число f32.") from error
                values.append(value)
        result.append(struct.pack("<6f", *values))
    return result


def patch_level(data: bytes, actor_transforms) -> bytes:
    """Заменить transforms четырёх актёров и добавить ещё четыре RPoint.

    actor_transforms: восемь dict с position=[x,y,z], rotation=[x,y,z].
    Исходник должен иметь ровно 5 lobby RPoints: reserved и четыре актёра.
    Дочерние chunks должны идти с ID 0..n-1: loader ищет их по ID
    последовательно с нуля и прекращает чтение на первом пропуске.
    """
    transforms = _actor_bytes(actor_transforms)
    if not isinstance(data, bytes):
        raise PatchError("level.game должен быть передан как bytes.")
    outer = _chunks(data, "level.game")
    targets = [entry for entry in outer if entry[0] == TARGET_CHUNK]
    if len(targets) != 1:
        raise PatchError("Требуется единственный исходный chunk 0x2000.")
    _, target_offset, payload = targets[0]
    records = _chunks(payload, "RPoints")
    if any(identifier != index for index, (identifier, _, _) in enumerate(records)):
        raise PatchError("RPoints: требуются ID 0..n-1 в том же порядке, без пропусков и перестановок.")
    lobby = []
    for index, (identifier, _offset, record) in enumerate(records):
        if len(record) != RECORD_SIZE:
            raise PatchError(f"RPoint ID {identifier}: ожидается длина 29, получена {len(record)}.")
        if not all(math.isfinite(value) for value in struct.unpack_from("<6f", record)):
            raise PatchError(f"RPoint ID {identifier}: исходный transform содержит NaN/Inf.")
        if record[24] == 0 and record[25] == 0 and struct.unpack_from("<H", record, 26)[0] & 1:
            lobby.append(index)
    if len(lobby) != 5:
        raise PatchError(f"Требуется ровно 5 исходных lobby RPoints; найдено {len(lobby)}. "
                         "Повторный патч не допускается.")
    maximum_id = max(identifier for identifier, _, _ in records)
    if maximum_id > 0xFFFFFFFF - 4:
        raise PatchError("Нет четырёх свободных u32 ID выше максимального исходного ID.")
    actors = lobby[1:]
    replacements = dict(zip(actors, transforms[:4]))
    parts = []
    for index, (_identifier, offset, record) in enumerate(records):
        raw = payload[offset : offset + 8 + len(record)]
        if index in replacements:
            raw = raw[:8] + replacements[index] + record[24:]
        parts.append(raw)
    for index in range(4):
        metadata = records[actors[index]][2][24:]
        parts.append(struct.pack("<II", maximum_id + index + 1, RECORD_SIZE) +
                     transforms[index + 4] + metadata)
    patched_payload = b"".join(parts)
    if len(patched_payload) > 0xFFFFFFFF:
        raise PatchError("Размер изменённого chunk превышает u32.")
    # До length target и после target сохраняется исходный поток байтов.
    return (data[: target_offset + 4] + struct.pack("<I", len(patched_payload)) +
            patched_payload + data[target_offset + 8 + len(payload) :])


def _plain_path(path: Path) -> Path:
    absolute = Path(path)
    if not absolute.is_absolute():
        absolute = Path.cwd() / absolute
    # До abspath: '..' не должен скрыть символическую ссылку в исходном пути.
    for component in (*reversed(absolute.parents), absolute):
        if component.is_symlink():
            raise PatchError(f"Символические ссылки в путях запрещены: {component}")
    return Path(os.path.abspath(absolute))


def _read_regular(path: Path) -> bytes:
    path = _plain_path(path)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    with os.fdopen(os.open(path, flags), "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise PatchError(f"Требуется обычный файл: {path}")
        return stream.read()


def _json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise PatchError(f"Профиль содержит повторный JSON key: {key}")
        result[key] = value
    return result


def _json_constant(value):
    raise PatchError(f"Профиль содержит недопустимое JSON число: {value}")


def _load_layout(path: Path):
    try:
        layout = json.loads(_read_regular(path).decode("utf-8"),
                            object_pairs_hook=_json_object, parse_constant=_json_constant)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise PatchError(f"Профиль должен содержать корректный UTF-8 JSON: {error}") from error
    if (not isinstance(layout, dict) or set(layout) != {"format", "maps"} or
            type(layout["format"]) is not int or layout["format"] != 1):
        raise PatchError("Профиль должен содержать только format=1 и maps.")
    maps = layout["maps"]
    if not isinstance(maps, dict) or len(maps) != MAP_COUNT:
        raise PatchError(f"Профиль должен явно описывать все {MAP_COUNT} карт.")
    for name, entry in maps.items():
        if not re.fullmatch(r"[A-Za-z0-9_]+", name):
            raise PatchError(f"Недопустимое имя карты в профиле: {name!r}")
        if not isinstance(entry, dict) or set(entry) != {"sha256", "actors"}:
            raise PatchError(f"Карта {name}: нужны только sha256 и actors.")
        if not isinstance(entry["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]):
            raise PatchError(f"Карта {name}: требуется исходный SHA256 из 64 строчных hex символов.")
        _actor_bytes(entry["actors"])
    return maps


def _publish_stage(temporary: Path, output: Path):
    # os.rename на POSIX способен заменить существующий пустой каталог.
    # RENAME_NOREPLACE нужен и после предварительной проверки lexists.
    if not sys.platform.startswith("linux"):
        raise PatchError("Атомарная публикация stage пока поддерживается только на Linux.")
    libc = ctypes.CDLL(None, use_errno=True)
    rename = getattr(libc, "renameat2", None)
    if rename is None:
        raise PatchError("libc не предоставляет renameat2; безопасная публикация недоступна.")
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(temporary), -100, os.fsencode(output), 1) != 0:
        code = ctypes.get_errno()
        if code in (errno.EEXIST, errno.ENOTEMPTY):
            raise PatchError(f"Выход уже существует; перезапись запрещена: {output}")
        if code in (errno.ENOSYS, errno.EINVAL, errno.EOPNOTSUPP):
            raise PatchError("Файловая система/ядро не поддерживает безопасный renameat2.")
        raise OSError(code, os.strerror(code), str(output))


def build_stage(source_dir: Path, layout_file: Path, output_dir: Path) -> dict:
    """Проверить весь комплект, затем атомарно опубликовать новую stage.

    Возвращает map name -> SHA256 результата. Исходники не записываются.
    SHA256 в профиле является явной границей поддерживаемой версии данных.
    """
    source = _plain_path(source_dir)
    profile = _plain_path(layout_file)
    output = _plain_path(output_dir)
    if source == output or source in output.parents or output in source.parents:
        raise PatchError("Вход и выход должны быть отдельными деревьями; in-place запрещён.")
    if os.path.lexists(output):
        raise PatchError(f"Выход уже существует; перезапись запрещена: {output}")
    if not output.parent.is_dir():
        raise PatchError(f"Родительский каталог выхода должен существовать: {output.parent}")
    maps = _load_layout(profile)
    levels = _plain_path(source / "levels")
    if not levels.is_dir():
        raise PatchError(f"Отсутствует исходный каталог levels: {levels}")
    found = {}
    for directory in levels.iterdir():
        candidate = directory / "level.game"
        if candidate.exists() or candidate.is_symlink():
            candidate = _plain_path(candidate)
            found[directory.name] = candidate
    if set(found) != set(maps):
        raise PatchError("Набор карт в профиле не совпадает с levels/*/level.game: "
                         f"нет в исходнике={sorted(set(maps) - set(found))}; "
                         f"нет в профиле={sorted(set(found) - set(maps))}.")
    # Все результаты рассчитываются до создания временной директории.
    patched = {}
    for name in sorted(maps):
        data = _read_regular(found[name])
        digest = hashlib.sha256(data).hexdigest()
        if digest != maps[name]["sha256"]:
            raise PatchError(f"Карта {name}: неизвестный исходный SHA256 {digest}; "
                             f"ожидается {maps[name]['sha256']}.")
        patched[name] = patch_level(data, maps[name]["actors"])
    hashes = {name: hashlib.sha256(data).hexdigest() for name, data in patched.items()}
    with tempfile.TemporaryDirectory(prefix=f".{output.name}-", dir=output.parent) as temporary:
        stage = Path(temporary)
        for name, data in patched.items():
            directory = stage / "levels" / name
            directory.mkdir(parents=True)
            with (directory / "level.game").open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        _publish_stage(stage, output)
    return hashes


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    parser = argparse.ArgumentParser(
        description="Создать новую stage 18 level.game с 8 явными actor transforms из JSON. "
                    "Проверяет данные и SHA256; качество размещения требует игровой проверки. "
                    "Публикация stage пока только Linux."
    )
    parser.add_argument("--source-dir", required=True, type=Path, help="корень с levels/<map>/level.game")
    parser.add_argument("--layout-file", required=True, type=Path, help="UTF-8 JSON: format=1, maps[18]")
    parser.add_argument("--output-dir", required=True, type=Path, help="новый каталог stage")
    args = parser.parse_args(argv)
    try:
        hashes = build_stage(args.source_dir, args.layout_file, args.output_dir)
    except (PatchError, OSError) as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 1
    print(f"Создана stage: {args.output_dir}; карт: {len(hashes)}; lobby RPoints на карту: 9.")
    for name, digest in hashes.items():
        print(f"{name}: SHA256 {digest}")
    print("Сборка подтверждает структуру данных; размещение и 8 клиентов требуют runtime-проверки.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
