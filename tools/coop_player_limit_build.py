"""Repo-only профиль 8 игроков: строгая проверка assets/stage до любых правок.

Игровые файлы находятся в optional/player_limit_8. Здесь нет поиска addon,
установленной игры или локальных scratch-данных; чужие overlays не затираются.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile

from build_coop_player_limit import PatchError, patch_config


MAPS = (
    'coop_l01_escape', 'coop_l02_garbage', 'coop_l03_agroprom',
    'coop_l03_agroprom_underground', 'coop_l04_darkvalley', 'coop_l04_x18',
    'coop_l05_bar', 'coop_l06_rostok', 'coop_l07_military', 'coop_l08_x16',
    'coop_l08_yantar', 'coop_l09_radar', 'coop_l09_x10', 'coop_l10_pripyat',
    'coop_l11_control_monolith', 'coop_l11_sarcofag', 'coop_l11_stancia_1',
    'coop_l11_stancia_2',
)
BASE_MAPS = {'coop_l01_escape', 'coop_l11_sarcofag'}
UI_PATH = 'configs/ui/coop_lobby_wnd.xml'
EXPECTED_PATHS = {f'levels/{name}/level.game' for name in MAPS} | {UI_PATH}
BASE_PATHS = {f'levels/{name}/level.game' for name in BASE_MAPS}
COOP_PATH = 'configs/mp/cooperative_game.ltx'
AMMO_PATH = 'configs/misc/coop_balance.ltx'
PROFILE_NAME = 'coop_player_limit_profile.json'
DB_NAME = 'zzz_soc_coop_fixes.db'
ENGINE = {
    'size': 7915520,
    'original_sha256': 'ef430b5f39628dcd03a4dd6e44b114559549660dd06d3f3218296d1eee1c462e',
    'patched_sha256': 'de8e7b892203abc0e7a667b1a56ad0844140f02a82461e8432edc6a3150f2860',
}


class ProfileError(ValueError):
    """Профиль несовместим с текущей stage или выходным файлом."""


def _plain(path):
    path = Path(path).absolute()
    for part in (*reversed(path.parents), path):
        if part.is_symlink():
            raise ProfileError(f'Symlink запрещён: {part}')
        if part != path and part.exists() and not part.is_dir():
            raise ProfileError(f'Родитель пути не является каталогом: {part}')
    return path


def _read(path):
    path = _plain(path)
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
    flags |= getattr(os, 'O_NONBLOCK', 0)
    with os.fdopen(os.open(path, flags), 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ProfileError(f'Требуется обычный файл: {path}')
        return stream.read()


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProfileError(f'Повторный JSON key: {key}')
        result[key] = value
    return result


def _json(path):
    try:
        return json.loads(_read(path).decode('utf-8'), object_pairs_hook=_object)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ProfileError(f'Некорректный JSON {path}: {error}') from error


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _is_sha(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def _asset_manifest(optional):
    data = _json(optional / 'manifest.json')
    if (not isinstance(data, dict) or set(data) != {'schema_version', 'assets'} or
            type(data['schema_version']) is not int or data['schema_version'] != 1 or
            not isinstance(data['assets'], list) or len(data['assets']) != 19):
        raise ProfileError('Manifest требует schema_version=1 и ровно 19 assets; обновите профиль.')
    entries = {}
    for entry in data['assets']:
        if not isinstance(entry, dict) or set(entry) != {'path', 'sha256', 'stage_sha256'}:
            raise ProfileError('Manifest asset требует только path, sha256, stage_sha256.')
        path = entry['path']
        if not isinstance(path, str) or path not in EXPECTED_PATHS or path in entries:
            raise ProfileError(f'Missing/duplicate/unexpected asset path: {path!r}')
        if not _is_sha(entry['sha256']):
            raise ProfileError(f'Некорректный SHA256 asset: {path}')
        baseline = entry['stage_sha256']
        if (path in BASE_PATHS and not _is_sha(baseline)) or (path not in BASE_PATHS and baseline is not None):
            raise ProfileError(f'Некорректный stage baseline: {path}; обновите профиль.')
        entries[path] = entry
    if set(entries) != EXPECTED_PATHS:
        raise ProfileError('Manifest не описывает точный набор 19 assets.')
    gamedata = _plain(optional / 'gamedata')
    if not gamedata.is_dir():
        raise ProfileError(f'Нет gamedata: {gamedata}')
    found = set()
    allowed_dirs = {str(parent).replace('\\', '/') for name in EXPECTED_PATHS
                    for parent in Path(name).parents if str(parent) != '.'}
    for path in gamedata.rglob('*'):
        path = _plain(path)
        rel = path.relative_to(gamedata).as_posix()
        if path.is_dir():
            if rel not in allowed_dirs:
                raise ProfileError(f'Unexpected asset directory: {rel}')
        elif path.is_file():
            found.add(rel)
        else:
            raise ProfileError(f'Asset не является обычным файлом: {rel}')
    if found != EXPECTED_PATHS:
        raise ProfileError(f'Missing/unexpected asset paths: {sorted(found ^ EXPECTED_PATHS)}')
    return entries


def _patch_coop(data):
    # Используем проверенный core; обратное преобразование ограничивает baseline
    # ровно значениями 4/8, не принимая незаметно иной upstream лимит.
    try:
        result = patch_config(data, players=8)
    except PatchError as error:
        try:
            four = patch_config(data, players=4)
            if patch_config(four, players=8) == data:
                return data
        except PatchError:
            pass
        raise ProfileError(f'{COOP_PATH}: {error}; обновите профиль.') from error
    if patch_config(result, players=4) != data:
        raise ProfileError(f'{COOP_PATH}: ожидается max_players=4 или 8; обновите профиль.')
    return result


def _patch_ammo(data):
    if b'\0' in data:
        raise ProfileError(f'{AMMO_PATH}: NUL в LTX.')
    section, count, values, offset = None, 0, [], 0
    for raw in data.splitlines(keepends=True):
        line = raw.rstrip(b'\r\n').split(b';', 1)[0]
        code = line.strip(b' \t')
        if code.startswith(b'#'):
            raise ProfileError(f'{AMMO_PATH}: include/directive не поддерживается; обновите профиль.')
        if code.startswith(b'['):
            match = re.fullmatch(rb'\[([^\]]+)\]([ \t]*:[^\r\n]*)?', code)
            if not match:
                raise ProfileError(f'{AMMO_PATH}: некорректный заголовок LTX.')
            section = match[1].strip().lower()
            if section == b'ammo':
                count += 1
                if match[2]:
                    raise ProfileError(f'{AMMO_PATH}: наследование ammo не поддерживается.')
        elif section == b'ammo' and re.match(rb'[ \t]*max_players\b', line, re.I):
            match = re.fullmatch(rb'[ \t]*max_players[ \t]*=[ \t]*(?P<value>[48])[ \t]*', line, re.I)
            if not match:
                raise ProfileError(f'{AMMO_PATH}: ожидается [ammo] max_players=4 или 8; обновите профиль.')
            values.append(offset + match.start('value'))
        offset += len(raw)
    if count != 1 or len(values) != 1:
        raise ProfileError(f'{AMMO_PATH}: требуется единственная секция ammo и max_players; обновите профиль.')
    position = values[0]
    return data[:position] + b'8' + data[position + 1:]


def apply_profile(stage, optional):
    """Проверить весь набор и оба LTX; только затем внести overlay в свою stage.

    Функция предназначена для приватной временной stage build.py. Отказ по
    данным/путям не оставляет частичных правок; I/O failure обрабатывает build,
    удаляя всю временную stage, а не публикуя её как пригодную к упаковке.
    """
    stage, optional = _plain(stage), _plain(optional)
    if stage == optional or stage in optional.parents or optional in stage.parents:
        raise ProfileError('Stage и optional должны быть отдельными деревьями.')
    if not stage.is_dir():
        raise ProfileError(f'Нет stage: {stage}')
    try:
        entries = _asset_manifest(optional)
        writes = {}
        for name, entry in sorted(entries.items()):
            data = _read(optional / 'gamedata' / name)
            if _sha(data) != entry['sha256']:
                raise ProfileError(f'Asset SHA256 mismatch: {name}; обновите профиль.')
            target = _plain(stage / name)
            baseline = entry['stage_sha256']
            if baseline is None:
                if os.path.lexists(target):
                    raise ProfileError(f'Stage уже содержит {name}; обновите optional asset/profile, чтобы сохранить upstream fix.')
            elif _sha(_read(target)) != baseline:
                raise ProfileError(f'Stage baseline SHA256 mismatch: {name}; обновите optional asset/profile.')
            writes[target] = data
        # До первой записи проверены также пути/синтаксис обоих текущих LTX.
        writes[_plain(stage / COOP_PATH)] = _patch_coop(_read(stage / COOP_PATH))
        writes[_plain(stage / AMMO_PATH)] = _patch_ammo(_read(stage / AMMO_PATH))
    except OSError as error:
        raise ProfileError(f'Неполный/нечитаемый профиль или stage: {error}; обновите профиль.') from error
    for target, data in writes.items():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def validate_output_profile(db):
    """Чужой профиль запрещает сборку до pack/перезаписи DB."""
    db = _plain(db)
    if db.name != DB_NAME:
        raise ProfileError(f'Профиль 8 требует имя DB {DB_NAME}; получено {db.name}.')
    profile = _plain(db.parent / PROFILE_NAME)
    if not os.path.lexists(profile):
        return profile
    data = _json(profile)
    if (not isinstance(data, dict) or set(data) != {'schema_version', 'capacity', 'addon_version', 'engine', 'patch_db'} or
            type(data['schema_version']) is not int or data['schema_version'] != 1 or
            type(data['capacity']) is not int or data['capacity'] != 8 or
            data['addon_version'] != '8.1' or data['engine'] != ENGINE):
        raise ProfileError(f'Чужой/неподдерживаемый профиль: {profile}; перезапись запрещена.')
    patch = data['patch_db']
    if (not isinstance(patch, dict) or set(patch) != {'name', 'size', 'sha256'} or
            patch['name'] != DB_NAME or type(patch['size']) is not int or patch['size'] <= 0 or
            not _is_sha(patch['sha256'])):
        raise ProfileError(f'Чужой/повреждённый профиль DB: {profile}; перезапись запрещена.')
    return profile


def write_output_profile(db):
    """Записать точный fingerprint упакованного DB через atomic replace."""
    db = _plain(db)
    profile = validate_output_profile(db)
    sha, size = hashlib.sha256(), 0
    with db.open('rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ProfileError(f'Требуется обычный DB: {db}')
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            sha.update(block)
            size += len(block)
    if not size:
        raise ProfileError(f'Пустой DB: {db}')
    data = {'schema_version': 1, 'capacity': 8, 'addon_version': '8.1', 'engine': dict(ENGINE),
            'patch_db': {'name': DB_NAME, 'size': size, 'sha256': sha.hexdigest()}}
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n',
                                         prefix='.' + PROFILE_NAME, suffix='.tmp',
                                         dir=profile.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, indent=2, ensure_ascii=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, profile)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return profile
