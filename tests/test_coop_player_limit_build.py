"""Контракт repo-only opt-in сборки, сохранения данных и отказов до записи."""
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from build_coop_lobby_data import patch_level, _chunks
try:
    import coop_player_limit_build as builder
except ImportError:
    builder = None

MAPS = (
    'coop_l01_escape', 'coop_l02_garbage', 'coop_l03_agroprom',
    'coop_l03_agroprom_underground', 'coop_l04_darkvalley', 'coop_l04_x18',
    'coop_l05_bar', 'coop_l06_rostok', 'coop_l07_military', 'coop_l08_x16',
    'coop_l08_yantar', 'coop_l09_radar', 'coop_l09_x10', 'coop_l10_pripyat',
    'coop_l11_control_monolith', 'coop_l11_sarcofag', 'coop_l11_stancia_1',
    'coop_l11_stancia_2',
)
UI = 'configs/ui/coop_lobby_wnd.xml'
COOP = 'configs/mp/cooperative_game.ltx'
AMMO = 'configs/misc/coop_balance.ltx'
BASE_MAPS = {'coop_l01_escape': 'cordon', 'coop_l11_sarcofag': 'sarcophagus_count'}
ACTORS = [{'position': [i, 1, 2], 'rotation': [0, i / 8, 0]} for i in range(8)]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def put(root, name, data):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def level(tag):
    # Внешние данные и последняя metadata byte различаются для двух фиксов.
    records = b''.join(struct.pack('<II6fBBHB', i, 29, i, 0, 0, 0, 0, 0,
                                   0, 0, 1, tag + i) for i in range(5))
    return (struct.pack('<II', 0x1000, 6) + b'fix:' + bytes([tag, 255]) +
            struct.pack('<II', 0x2000, len(records)) + records +
            struct.pack('<II', 0x3000, 4) + bytes([tag]) * 4)


def snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in root.rglob('*') if p.is_file() and not p.is_symlink()}


class ProfileBuildTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(builder, 'repo-only build helper is missing')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.stage = self.root / 'stage'
        self.optional = self.root / 'optional'
        self.stage.mkdir()
        self.optional.mkdir()
        self.assets = []
        for index, name in enumerate(MAPS):
            path = f'levels/{name}/level.game'
            base = level(index)
            generated = patch_level(base, ACTORS)
            put(self.optional / 'gamedata', path, generated)
            expected = None
            if name in BASE_MAPS:
                put(self.stage, path, base)
                expected = digest(base)
            self.assets.append({'path': path, 'sha256': digest(generated),
                                'stage_sha256': expected})
        put(self.optional / 'gamedata', UI, b'<lobby>eight; checked template</lobby>')
        self.assets.append({'path': UI, 'sha256': digest((self.optional / 'gamedata' / UI).read_bytes()),
                            'stage_sha256': None})
        self.save_manifest()
        self.coop = (b'; untouched\r\n[other]\r\nmax_players=4\r\n'
                     b'[cooperative_gamedata]\r\n max_players \t= 4 ; keep comment\r\n'
                     b'new_upstream_key=yes\r\n[coop_team]\r\nskins=custom\r\n')
        self.ammo = (b'[damage]\r\nplayer_damage_mult=1.5\r\nmax_players=4\r\n'
                     b'[ammo] ; comment\r\n\tmax_players = 4 ; original cap\r\n'
                     b'new_upstream_key=yes\r\n[scaling]\r\nmax_factor=2.5\r\n'
                     b'max_extra_members=6\r\nmax_extra_squads_per_smart=1\r\n')
        put(self.stage, COOP, self.coop)
        put(self.stage, AMMO, self.ammo)
        put(self.stage, 'configs/coop_settings.ltx', b'[ammo]\nmax_players=4\n')
        put(self.stage, 'scripts/unrelated.script', b'upstream fix')

    def save_manifest(self, assets=None):
        (self.optional / 'manifest.json').write_text(json.dumps(
            {'schema_version': 1, 'assets': self.assets if assets is None else assets}), encoding='utf-8')

    def reject_unchanged(self, pattern=None):
        before = snapshot(self.stage)
        with self.assertRaisesRegex(builder.ProfileError, pattern or '.'):
            builder.apply_profile(self.stage, self.optional)
        self.assertEqual(snapshot(self.stage), before)

    def test_apply_preserves_foreign_chunks_metadata_configs_and_host_override(self):
        before = snapshot(self.stage)
        builder.apply_profile(self.stage, self.optional)
        self.assertEqual((self.stage / COOP).read_bytes(), self.coop.replace(b'= 4 ;', b'= 8 ;'))
        self.assertEqual((self.stage / AMMO).read_bytes(), self.ammo.replace(b'= 4 ;', b'= 8 ;'))
        for path in ('configs/coop_settings.ltx', 'scripts/unrelated.script'):
            self.assertEqual((self.stage / path).read_bytes(), before[path])
        for name in BASE_MAPS:
            path = f'levels/{name}/level.game'
            original = {i: b for i, _, b in _chunks(before[path], name)}
            result = {i: b for i, _, b in _chunks((self.stage / path).read_bytes(), name)}
            self.assertEqual(original[0x1000], result[0x1000])
            self.assertEqual(original[0x3000], result[0x3000])
            old_records = _chunks(original[0x2000], name)
            records = _chunks(result[0x2000], name)
            self.assertEqual(len(records), 9)
            self.assertEqual(records[0][2], old_records[0][2])
            for index in range(1, 5):
                self.assertEqual(records[index][2][24:], old_records[index][2][24:])
                self.assertEqual(records[index + 4][2][24:], old_records[index][2][24:])

    def test_already_eight_configs_are_accepted_without_other_edits(self):
        put(self.stage, COOP, self.coop.replace(b'= 4 ;', b'= 8 ;'))
        put(self.stage, AMMO, self.ammo.replace(b'= 4 ;', b'= 8 ;'))
        builder.apply_profile(self.stage, self.optional)
        self.assertEqual((self.stage / COOP).read_bytes(), self.coop.replace(b'= 4 ;', b'= 8 ;'))
        self.assertEqual((self.stage / AMMO).read_bytes(), self.ammo.replace(b'= 4 ;', b'= 8 ;'))

    def test_changed_baselines_and_new_stage_map_or_ui_refuse_before_any_overlay(self):
        for path in [f'levels/{name}/level.game' for name in BASE_MAPS] + [
                'levels/coop_l02_garbage/level.game', UI]:
            with self.subTest(path=path):
                target = self.stage / path
                old = target.read_bytes() if target.exists() else None
                put(self.stage, path, b'new upstream fix')
                self.reject_unchanged('update|обнов')
                if old is None:
                    target.unlink()
                else:
                    target.write_bytes(old)

    def test_asset_hash_missing_extra_duplicate_and_unsafe_manifest_refuse(self):
        original = snapshot(self.optional)
        cases = ['hash', 'missing', 'extra', 'duplicate', 'escape', 'unexpected', 'baseline']
        for case in cases:
            with self.subTest(case=case):
                shutil.rmtree(self.optional)
                self.optional.mkdir()
                for path, data in original.items():
                    put(self.optional, path, data)
                assets = json.loads((self.optional / 'manifest.json').read_text())['assets']
                if case == 'hash':
                    (self.optional / 'gamedata' / UI).write_bytes(b'corrupt')
                elif case == 'missing':
                    (self.optional / 'gamedata' / UI).unlink()
                elif case == 'extra':
                    put(self.optional / 'gamedata', 'scripts/surprise.script', b'bad')
                elif case == 'duplicate':
                    assets[-1] = assets[0]
                elif case == 'escape':
                    assets[-1]['path'] = '../outside'
                elif case == 'unexpected':
                    assets[-1]['path'] = 'configs/ui/other.xml'
                elif case == 'baseline':
                    assets[0]['stage_sha256'] = None
                self.save_manifest(assets)
                self.reject_unchanged()

    def test_blocking_parent_and_missing_baseline_or_config_refuse_without_partial_copy(self):
        # Build владеет stage; даже ошибки структуры должны быть preflight.
        for relative in ['levels/coop_l11_stancia_2', 'configs/ui']:
            with self.subTest(parent=relative):
                parent = self.stage / relative
                if parent.exists():
                    shutil.rmtree(parent)
                put(self.stage, relative, b'blocking file')
                self.reject_unchanged()
                parent.unlink()
        for relative in ['levels/coop_l01_escape/level.game', COOP, AMMO]:
            with self.subTest(missing=relative):
                path = self.stage / relative
                previous = path.read_bytes()
                path.unlink()
                self.reject_unchanged()
                path.write_bytes(previous)

    def test_duplicate_json_keys_refuse(self):
        path = self.optional / 'manifest.json'
        path.write_text(path.read_text().replace('"schema_version": 1', '"schema_version": 1, "schema_version": 1'))
        self.reject_unchanged()

    def test_symlink_asset_stage_and_parent_refuse(self):
        asset = self.optional / 'gamedata' / UI
        external = put(self.root, 'external.xml', asset.read_bytes())
        asset.unlink()
        asset.symlink_to(external)
        self.reject_unchanged()
        asset.unlink()
        asset.write_bytes(external.read_bytes())
        target = self.stage / COOP
        external.write_bytes(target.read_bytes())
        target.unlink()
        target.symlink_to(external)
        self.reject_unchanged()
        target.unlink()
        target.write_bytes(external.read_bytes())
        real = self.stage / 'configs' / 'misc'
        moved = self.root / 'moved'
        real.rename(moved)
        real.symlink_to(moved, target_is_directory=True)
        self.reject_unchanged()

    def test_invalid_config_rejects_without_partial_asset_copy(self):
        for path, content in [(COOP, b'[cooperative_gamedata]\nmax_players=5\n'),
                              (AMMO, b'[ammo]\nmax_players=4\nmax_players=4\n'),
                              (AMMO, b'[ammo]:parent\nmax_players=4\n'),
                              (AMMO, b'[ammo]\nmax_players=3\n'),
                              (AMMO, b'#include "other"\n[ammo]\nmax_players=4\n')]:
            with self.subTest(content=content):
                old = (self.stage / path).read_bytes()
                (self.stage / path).write_bytes(content)
                self.reject_unchanged()
                (self.stage / path).write_bytes(old)

    def test_profile_is_bound_to_actual_db_and_only_own_profiles_are_replaced(self):
        db = put(self.root, 'zzz_soc_coop_fixes.db', b'db bytes')
        profile = builder.write_output_profile(db)
        data = json.loads(profile.read_text())
        self.assertEqual(data['schema_version'], 1)
        self.assertEqual(data['capacity'], 8)
        self.assertEqual(data['addon_version'], '8.1')
        self.assertEqual(data['engine']['size'], 7915520)
        self.assertEqual(data['engine']['original_sha256'], 'ef430b5f39628dcd03a4dd6e44b114559549660dd06d3f3218296d1eee1c462e')
        self.assertEqual(data['engine']['patched_sha256'], 'de8e7b892203abc0e7a667b1a56ad0844140f02a82461e8432edc6a3150f2860')
        self.assertEqual(data['patch_db'], {'name': db.name, 'size': 8, 'sha256': digest(b'db bytes')})
        db.write_bytes(b'new db bytes')
        builder.write_output_profile(db)
        self.assertEqual(json.loads(profile.read_text())['patch_db']['sha256'], digest(b'new db bytes'))
        for content in [b'{}', b'not JSON', json.dumps({**data, 'app_id': 'another'}).encode()]:
            profile.write_bytes(content)
            with self.assertRaises(builder.ProfileError):
                builder.write_output_profile(db)
            self.assertEqual(profile.read_bytes(), content)

    def test_build_cli_default_equivalence_opt_in_and_existing_options(self):
        checkout = self.root / 'checkout'
        checkout.mkdir()
        shutil.copy2(ROOT / 'build.py', checkout / 'build.py')
        tools = checkout / 'tools'
        tools.mkdir()
        for name in ['pack.py', 'verify_db.py', 'budget.py', 'coop_player_limit_build.py', 'build_coop_player_limit.py']:
            shutil.copy2(ROOT / 'tools' / name, tools / name)
        shutil.copytree(ROOT / 'tools/stalker_xrmpe', tools / 'stalker_xrmpe')
        shutil.copytree(self.stage, checkout / 'patches/base/gamedata')
        shutil.copytree(self.optional, checkout / 'optional/player_limit_8')
        put(checkout, 'optional/sarcophagus_fps/gamedata/scripts/fps.script', b'fps fix')
        put(checkout, 'optional/mm_style_ue4_a/gamedata/configs/ui/menu.xml', b'menu style')
        default_out = self.root / 'default/zzz_soc_coop_fixes.db'
        default_profile = put(default_out.parent, 'coop_player_limit_profile.json', b'unrelated profile')
        def run(*options):
            return subprocess.run([sys.executable, str(checkout / 'build.py'), *map(str, options), '--no-compress'],
                                  capture_output=True, text=True)
        kept = self.root / 'kept'
        result = run(default_out, f'--stage={kept}')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(snapshot(kept / 'gamedata'), snapshot(self.stage))
        self.assertEqual(default_profile.read_bytes(), b'unrelated profile')
        out = self.root / 'eight/zzz_soc_coop_fixes.db'
        kept8 = self.root / 'kept8'
        result = run(out, '--player-limit', '8', '--sarcophagus-fps', '--mm-style=ue4_a', f'--stage={kept8}')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((kept8 / 'gamedata/scripts/fps.script').read_bytes(), b'fps fix')
        self.assertEqual((kept8 / 'gamedata/configs/ui/menu.xml').read_bytes(), b'menu style')
        data = json.loads((out.parent / 'coop_player_limit_profile.json').read_text())
        self.assertEqual(data['patch_db']['sha256'], digest(out.read_bytes()))
        self.assertIn(b'max_players \t= 8', (kept8 / 'gamedata' / COOP).read_bytes())
        # Unknown profile refuses before pack can replace the previous DB.
        (out.parent / 'coop_player_limit_profile.json').write_bytes(b'foreign')
        before = out.read_bytes()
        result = run(out, '--player-limit=8')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(out.read_bytes(), before)
        self.assertEqual((out.parent / 'coop_player_limit_profile.json').read_bytes(), b'foreign')
        # Все обычные optional overlays применены до проверки profile.
        for folder, relative, option in [
                ('sarcophagus_fps', 'levels/coop_l01_escape/level.game', '--sarcophagus-fps'),
                ('mm_style_ue4_a', UI, '--mm-style=ue4_a')]:
            conflict = put(checkout / 'optional' / folder / 'gamedata', relative, b'upstream optional fix')
            failed_out = self.root / folder / 'zzz_soc_coop_fixes.db'
            failed_stage = self.root / (folder + '_stage')
            result = run(failed_out, '--player-limit=8', option, f'--stage={failed_stage}')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('обнов', result.stderr)
            self.assertFalse(failed_out.exists())
            self.assertFalse(failed_stage.exists())
            conflict.unlink()
        result = run(self.root / 'bad.db', '--player-limit', '5')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / 'bad.db').exists())

    def test_checked_in_real_assets_preserve_repo_map_fixes(self):
        optional = ROOT / 'optional/player_limit_8'
        manifest = json.loads((optional / 'manifest.json').read_text())
        self.assertEqual(len(manifest['assets']), 19)
        for entry in manifest['assets']:
            data = (optional / 'gamedata' / entry['path']).read_bytes()
            self.assertEqual(entry['sha256'], digest(data))
            name = Path(entry['path']).parent.name
            if name in BASE_MAPS:
                base = (ROOT / 'patches' / BASE_MAPS[name] / 'gamedata' / entry['path']).read_bytes()
                self.assertEqual(entry['stage_sha256'], digest(base))
                original = {i: b for i, _, b in _chunks(base, name)}
                result = {i: b for i, _, b in _chunks(data, name)}
                self.assertEqual(set(result), set(original))
                for identifier in set(original) - {0x2000}:
                    self.assertEqual(result[identifier], original[identifier])
                records = _chunks(result[0x2000], name)
                old = _chunks(original[0x2000], name)
                self.assertEqual(len(records), len(old) + 4)
                self.assertEqual(records[0][2], old[0][2])
                for index, (identifier, _, payload) in enumerate(old):
                    self.assertEqual(records[index][0], identifier)
                    self.assertEqual(records[index][2][24:], payload[24:])
                    if not (payload[24] == 0 and payload[25] == 0 and struct.unpack_from('<H', payload, 26)[0] & 1):
                        self.assertEqual(records[index][2], payload)


if __name__ == '__main__':
    unittest.main()
