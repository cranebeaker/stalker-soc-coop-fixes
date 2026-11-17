"""Проверки экспериментального сборщика без запуска игры и без сети."""
import io
import os
import struct
import subprocess
import sys
import tarfile
import tempfile
import tracemalloc
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
import build_coop_player_limit as builder
from stalker_xrmpe import xdb


class ConfigPatchTests(unittest.TestCase):
    def test_changes_only_target_digit_preserving_cp1251_and_crlf(self):
        # Ловит глобальную замену, перекодирование и нормализацию переводов строк.
        original = (
            "; Кириллица: игроки 4, ёж\r\n"
            "[another]\r\nmax_players = 4\r\n"
            "[cooperative_gamedata]\r\n"
            "\tmax_players \t= 4; max 4 — комментарий\r\n"
            "squad_community = 0\r\n"
            "[coop_team]\r\nmax_players = 4\r\n"
        ).encode("cp1251")
        expected = (
            "; Кириллица: игроки 4, ёж\r\n"
            "[another]\r\nmax_players = 4\r\n"
            "[cooperative_gamedata]\r\n"
            "\tmax_players \t= 8; max 4 — комментарий\r\n"
            "squad_community = 0\r\n"
            "[coop_team]\r\nmax_players = 4\r\n"
        ).encode("cp1251")
        result = builder.patch_config(original)
        self.assertEqual(result, expected)
        self.assertEqual(sum(a != b for a, b in zip(original, result)), 1)
        self.assertEqual(len(result), len(original))

    def test_preserves_no_final_newline_and_ignores_commented_keys(self):
        self.assertEqual(
            builder.patch_config(
                b"[cooperative_gamedata]; section\n; max_players = 9\n"
                b"max_players=4  ; keep this"
            ),
            b"[cooperative_gamedata]; section\n; max_players = 9\n"
            b"max_players=8  ; keep this",
        )

    def test_accepts_valid_source_limits_and_requested_boundaries(self):
        cases = [
            (b"1", 8, b"8"), (b"2", 1, b"1"),
            (b"3", 8, b"8"), (b"4", 1, b"1"),
            (b"5", 8, b"8"), (b"6", 1, b"1"),
            (b"7", 3, b"3"), (b"8", 1, b"1"),
        ]
        for original, players, expected in cases:
            with self.subTest(original=original, players=players):
                before = b"[cooperative_gamedata]\r\nmax_players=" + original + b" ; max 4\r\n"
                result = builder.patch_config(before, players=players)
                self.assertEqual(result, b"[cooperative_gamedata]\r\nmax_players=" + expected + b" ; max 4\r\n")
                self.assertEqual(len(result), len(before))
                self.assertEqual(sum(a != b for a, b in zip(result, before)), 1)

    def test_rejects_invalid_requested_limits(self):
        for players in (0, 9, -1, 1.5, "8", True, None):
            with self.subTest(players=players):
                with self.assertRaises(builder.PatchError):
                    builder.patch_config(b"[cooperative_gamedata]\nmax_players=4\n", players=players)

    def test_rejects_already_requested_limit_explicitly(self):
        for value in (1, 4, 8):
            with self.subTest(value=value):
                data = ("[cooperative_gamedata]\nmax_players=%d\n" % value).encode("ascii")
                with self.assertRaises(builder.PatchError):
                    builder.patch_config(data, players=value)

    def test_rejects_missing_ambiguous_and_unsupported_config(self):
        # Ловит выбор первого совпадения при дубликатах и небезопасные допущения.
        cases = {
            "missing section": b"[other]\nmax_players=4\n",
            "missing key": b"[cooperative_gamedata]\nsquad_community=0\n",
            "duplicate sections": (
                b"[cooperative_gamedata]\nmax_players=4\n"
                b"[cooperative_gamedata]\nmax_players=4\n"
            ),
            "duplicate keys": b"[cooperative_gamedata]\nmax_players=4\nmax_players=4\n",
            "duplicate spaced keys": b"[cooperative_gamedata]\nmax_players=4\n max_players = 4\n",
            "below range": b"[cooperative_gamedata]\nmax_players=0\n",
            "above range": b"[cooperative_gamedata]\nmax_players=9\n",
            "unknown text": b"[cooperative_gamedata]\nmax_players=banana\n",
            "noncanonical number": b"[cooperative_gamedata]\nmax_players=04\n",
            "missing assignment": b"[cooperative_gamedata]\nmax_players 4\n",
            "trailing value": b"[cooperative_gamedata]\nmax_players=4 5\n",
            "inherited section": b"[cooperative_gamedata]:parent\nmax_players=4\n",
            "included config": b'#include "extra.ltx"\n[cooperative_gamedata]\nmax_players=4\n',
            "malformed section": b"[cooperative_gamedata]\nmax_players=4\n[broken\n",
            "nul": b"[cooperative_gamedata]\nmax_players=4\x00\n",
        }
        for label, original in cases.items():
            with self.subTest(label=label):
                with self.assertRaises(builder.PatchError):
                    builder.patch_config(original)


class BoundedLzoTests(unittest.TestCase):
    def test_optional_bound_preserves_legacy_call_and_exact_size(self):
        stream = b"\x15abcd\x11\x00\x00"
        # Старые callers передают outlen, но upstream не использовал его как лимит.
        self.assertEqual(xdb.lzo1x(stream, 1), b"abcd")
        self.assertEqual(xdb.lzo1x(stream, 4, max_output=4), b"abcd")
        match_and_literal = b"\x12A\x41\x00B\x11\x00\x00"
        self.assertEqual(xdb.lzo1x(match_and_literal, 1), b"AAAAB")
        self.assertEqual(xdb.lzo1x(match_and_literal, 5, max_output=5), b"AAAAB")
        with self.assertRaises(ValueError):
            xdb.lzo1x(stream, 4, max_output=3)

    def test_rejects_single_large_literal_before_allocating_its_output(self):
        length = 500000
        zeros, tail = divmod(length - 18, 255)
        stream = b"\0" + b"\0" * zeros + bytes([tail]) + b"x" * length + b"\x11\x00\x00"
        tracemalloc.start()
        try:
            with self.assertRaises(ValueError):
                xdb.lzo1x(stream, 32, max_output=32)
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        self.assertLess(peak, 256 * 1024)

    def test_rejects_single_large_match_and_trailing_literal(self):
        bomb = b"\x15abcd\x20" + b"\0" * 40000 + b"\x01\x00\x00\x11\x00\x00"
        for stream, limit in ((bomb, 32), (b"\x12A\x41\x00B\x11\x00\x00", 4)):
            with self.subTest(limit=limit):
                with self.assertRaises(ValueError):
                    xdb.lzo1x(stream, limit, max_output=limit)


class ArchiveBuildTests(unittest.TestCase):
    """Настоящие .db от pack.py и настоящий tar; игра здесь не имитируется."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="coop_limit_test_")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.game = self.root / "game"
        for name in ("resources", "patches", "addons"):
            (self.game / name).mkdir(parents=True, exist_ok=True)
        self.output = self.root / "experiment.db"
        self.counter = 0
        self.base = b"[cooperative_gamedata]\r\nmax_players=4; resource\r\n"
        self.patch = b"[cooperative_gamedata]\r\nmax_players=4; patch\r\n"
        self.addon = (
            "; Исходный мод, не marked_one\r\n[cooperative_gamedata]\r\n"
            "max_players = 4; max 4\r\n[coop_team]\r\nskins=original\r\n"
        ).encode("cp1251")
        self.make_db(self.game / "resources" / "a.db0", {"configs/mp/cooperative_game.ltx": self.base})

    def make_db(self, destination, files):
        self.counter += 1
        stage = self.root / ("stage_%d" % self.counter)
        for name, data in files.items():
            path = stage / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        result = subprocess.run(
            [sys.executable, "-I", str(TOOLS / "pack.py"), str(stage), str(destination), "--no-compress", "--quiet"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return destination.read_bytes()

    def db_data(self, data):
        return self.make_db(self.root / ("member_%d.db" % self.counter), {"configs/mp/cooperative_game.ltx": data})

    def lzo_db_data(self, data, compressed, declared_real=None):
        packed = self.db_data(data)
        header_size = struct.unpack_from("<I", packed, 4)[0]
        blob_header = 8 + header_size
        index_header = blob_header + 8 + len(data)
        index = bytearray(packed[index_header + 8:])
        position = 0
        while position < len(index):
            entry_size, real = struct.unpack_from("<HI", index, position)
            if real:
                struct.pack_into("<II", index, position + 2, len(data) if declared_real is None else declared_real, len(compressed))
            position += entry_size + 2
        return packed[:blob_header] + struct.pack("<II", 0, len(compressed)) + compressed + struct.pack("<II", 1, len(index)) + index

    def make_addon(self, members):
        path = self.game / "addons" / "coop.addon"
        with tarfile.open(path, "w", format=tarfile.USTAR_FORMAT) as archive:
            for name, data in members:
                info = tarfile.TarInfo(name)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
        return path

    def snapshot_game(self):
        return {str(p.relative_to(self.game)): p.read_bytes() for p in self.game.rglob("*") if p.is_file()}

    def read_patch(self):
        with self.output.open("rb") as archive:
            result = {}
            for name, real, stored, position in xdb.index(archive, 0, self.output.stat().st_size):
                if name.endswith("\\"):
                    continue
                archive.seek(position)
                data = archive.read(stored)
                result[name] = data if real == stored else xdb.lzo1x(data, real)
            return result

    def assert_refused(self):
        before = self.snapshot_game()
        with self.assertRaises(builder.PatchError):
            builder.build_patch(self.game, self.output)
        self.assertFalse(self.output.exists())
        self.assertEqual(self.snapshot_game(), before)

    def test_cli_roundtrip_uses_addon_override_and_leaves_game_untouched(self):
        self.make_db(self.game / "patches" / "z.db", {"configs/mp/cooperative_game.ltx": self.patch})
        self.make_addon([
            ("gamedata.db0", self.db_data(self.base)),
            ("metadata.json", b'{"name":"fixture"}'),
            ("zzz_fix.db", self.db_data(self.addon)),
        ])
        before = self.snapshot_game()
        result = subprocess.run(
            [sys.executable, "-I", str(TOOLS / "build_coop_player_limit.py"), "--game", str(self.game), "--output", str(self.output)],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("zzz_fix.db", result.stdout)
        notice = (
            "Live-запуск с max_players >4 запрещён независимо от фактического числа "
            "подключённых игроков до установки проверенного обязательного патча данных лобби"
        )
        self.assertIn(notice, result.stdout)
        help_result = subprocess.run(
            [sys.executable, "-I", str(TOOLS / "build_coop_player_limit.py"), "--help"],
            capture_output=True, text=True,
        )
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertIn(notice, " ".join(help_result.stdout.split()))
        self.assertEqual(self.read_patch(), {
            "configs\\mp\\cooperative_game.ltx": (
                "; Исходный мод, не marked_one\r\n[cooperative_gamedata]\r\n"
                "max_players = 8; max 4\r\n[coop_team]\r\nskins=original\r\n"
            ).encode("cp1251")
        })
        self.assertEqual(self.snapshot_game(), before)

    def test_sorted_resource_and_patch_fallback_when_addon_has_no_config(self):
        self.make_db(self.game / "resources" / "z.db0", {"configs/mp/cooperative_game.ltx": self.patch})
        no_config = self.make_db(self.root / "other.db", {"configs/other.ltx": b"[other]\nx=1\n"})
        self.make_addon([("gamedata.db0", no_config)])
        builder.build_patch(self.game, self.output)
        self.assertEqual(self.read_patch()["configs\\mp\\cooperative_game.ltx"], b"[cooperative_gamedata]\r\nmax_players=8; patch\r\n")
        self.output.unlink()
        self.make_db(self.game / "patches" / "a.db", {"configs/mp/cooperative_game.ltx": self.addon})
        builder.build_patch(self.game, self.output)
        self.assertIn(b"skins=original", self.read_patch()["configs\\mp\\cooperative_game.ltx"])

    def test_refuses_conflicting_tar_and_name_order(self):
        self.make_addon([("zzz.db", self.db_data(self.addon)), ("gamedata.db0", self.db_data(self.base))])
        self.assert_refused()

    def test_refuses_db6_instead_of_claiming_agreement_with_qa_build(self):
        other = b"[cooperative_gamedata]\nmax_players=3\n"
        self.make_addon([("gamedata.db0", self.db_data(self.base)), ("gamedata.db6", self.db_data(other))])
        self.assert_refused()

    def test_refuses_unknown_numbered_db_suffix_in_base_sources(self):
        self.make_addon([("gamedata.db0", self.db_data(self.addon))])
        self.make_db(self.game / "patches" / "other.db6", {"configs/mp/cooperative_game.ltx": self.patch})
        self.assert_refused()

    def test_accepts_identical_config_under_both_orders(self):
        same = self.db_data(self.addon)
        self.make_addon([("zzz.db", same), ("gamedata.db0", same), ("gamedata.db5", same)])
        builder.build_patch(self.game, self.output)
        self.assertIn(b"max_players = 8; max 4", self.read_patch()["configs\\mp\\cooperative_game.ltx"])

    def test_refuses_duplicate_tar_member_and_duplicate_config_paths(self):
        for duplicate in (False, True):
            with self.subTest(duplicate_tar=duplicate):
                if duplicate:
                    db = self.db_data(self.addon)
                    self.make_addon([("gamedata.db0", db), ("gamedata.db0", db)])
                else:
                    db = self.make_db(self.root / "ambiguous.db", {
                        "configs/mp/cooperative_game.ltx": self.base,
                        "Configs/MP/Cooperative_Game.ltx": self.addon,
                    })
                    self.make_addon([("gamedata.db0", db)])
                self.assert_refused()

    def test_refuses_missing_addon_and_missing_config(self):
        self.assert_refused()
        (self.game / "resources" / "a.db0").unlink()
        no_config = self.make_db(self.root / "other.db", {"configs/other.ltx": b"[other]\nx=1\n"})
        self.make_addon([("gamedata.db0", no_config)])
        self.assert_refused()

    def test_refuses_unknown_overrides_instead_of_guessing_precedence(self):
        self.make_addon([("gamedata.db0", self.db_data(self.addon))])
        for name in ("gamedata", "GameData"):
            loose = self.game / name
            loose.mkdir()
            self.assert_refused()
            loose.rmdir()
        other = self.game / "addons" / "extra.addon"
        other.write_bytes(b"unknown addon")
        self.assert_refused()

    def test_refuses_existing_output_and_any_path_inside_game(self):
        self.make_addon([("gamedata.db0", self.db_data(self.addon))])
        before = self.snapshot_game()
        self.output.write_bytes(b"existing result")
        with self.assertRaises(builder.PatchError):
            builder.build_patch(self.game, self.output)
        self.assertEqual(self.output.read_bytes(), b"existing result")
        self.output.unlink()
        for path in (self.game / "resources" / "a.db0", self.game / "patches" / "new.db"):
            with self.subTest(path=path):
                with self.assertRaises(builder.PatchError):
                    builder.build_patch(self.game, path)
        self.assertEqual(self.snapshot_game(), before)

    def test_refuses_existing_or_dangling_output_symlink(self):
        self.make_addon([("gamedata.db0", self.db_data(self.addon))])
        for target in (self.game / "resources" / "a.db0", self.root / "absent.db"):
            with self.subTest(target=target):
                self.output.symlink_to(target)
                with self.assertRaises(builder.PatchError):
                    builder.build_patch(self.game, self.output)
                self.assertTrue(self.output.is_symlink())
                self.output.unlink()

    def test_refuses_corrupt_source_archives_and_empty_target(self):
        for data in (b"not a database", self.db_data(self.addon)[:-10], self.db_data(b"")):
            with self.subTest(data_length=len(data)):
                self.make_addon([("gamedata.db0", data)])
                self.assert_refused()
        self.make_addon([("gamedata.db0", self.db_data(self.addon))])
        (self.game / "patches" / "corrupt.db").write_bytes(b"bad")
        self.assert_refused()

    def test_reads_lzo_member_before_patching(self):
        # Валидный буквальный LZO1X stream, независимый от python-lzo/сети.
        data = self.base
        compressed = bytes([len(data) + 17]) + data + b"\x11\x00\x00"
        self.make_addon([("gamedata.db0", self.lzo_db_data(data, compressed))])
        builder.build_patch(self.game, self.output)
        self.assertEqual(self.read_patch()["configs\\mp\\cooperative_game.ltx"], b"[cooperative_gamedata]\r\nmax_players=8; resource\r\n")

    def test_builder_limits_lzo_output_before_large_backreference_expands(self):
        # Repro Astra: 40012 сжатых байт разворачиваются в 10200038 байт,
        # хотя индекс декларирует real=32. Отказ после такой аллокации недостаточен.
        compressed = b"\x15abcd\x20" + b"\0" * 40000 + b"\x01\x00\x00\x11\x00\x00"
        self.assertEqual(len(compressed), 40012)
        self.make_addon([("gamedata.db0", self.lzo_db_data(self.base, compressed, declared_real=32))])
        tracemalloc.start()
        try:
            self.assert_refused()
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        self.assertLess(peak, 1024 * 1024)

    def test_cli_failure_does_not_publish_patch(self):
        self.make_addon([("gamedata.db0", self.db_data(b"[cooperative_gamedata]\nmax_players=9\n"))])
        result = subprocess.run(
            [sys.executable, "-I", str(TOOLS / "build_coop_player_limit.py"), "--game", str(self.game), "--output", str(self.output)],
            capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("max_players", result.stderr)
        self.assertFalse(self.output.exists())

    def test_cli_reports_success_with_ascii_default_console(self):
        # Иначе успешная сборка заканчивается UnicodeEncodeError при отчёте.
        self.make_addon([("gamedata.db0", self.db_data(self.addon))])
        result = subprocess.run(
            [sys.executable, str(TOOLS / "build_coop_player_limit.py"), "--game", str(self.game), "--output", str(self.output)],
            env=dict(os.environ, PYTHONIOENCODING="ascii"),
            capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("max_players", result.stdout)
        self.assertTrue(self.output.is_file())

    def test_cli_selected_limit_one_roundtrips_and_invalid_limits_create_nothing(self):
        self.make_addon([("gamedata.db0", self.db_data(self.addon))])
        before = self.snapshot_game()
        command = [sys.executable, "-I", str(TOOLS / "build_coop_player_limit.py"), "--game", str(self.game), "--output", str(self.output)]
        for players in ("0", "9", "1.5", "text"):
            with self.subTest(players=players):
                result = subprocess.run(command + ["--players", players], capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("--players", result.stderr)
                self.assertFalse(self.output.exists())
        result = subprocess.run(command + ["--players", "1"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(b"max_players = 1; max 4", self.read_patch()["configs\\mp\\cooperative_game.ltx"])
        self.assertEqual(self.snapshot_game(), before)

    def test_no_db_is_created_when_requested_limit_already_matches(self):
        self.make_addon([("gamedata.db0", self.db_data(b"[cooperative_gamedata]\nmax_players=8\n"))])
        self.assert_refused()


if __name__ == "__main__":
    unittest.main()
