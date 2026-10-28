"""Ограниченный патч cap 4→8: проверки без игры и без поставки DLL."""

import contextlib
import errno
import hashlib
import importlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


TOOLS = Path(__file__).resolve().parents[1] / "tools"
SCRIPT = TOOLS / "patch_coop_player_limit.py"
sys.path.insert(0, str(TOOLS))

# Маленький образ только для проверки механизма guards; CLI его не принимает.
CLIENT = bytes.fromhex("3c047607c6864914000004")
SERVER = bytes.fromhex("3c047607c686d045000004")
IMAGE = b"\xcc" * 16 + CLIENT + b"\xcc" * 21 + SERVER + b"\xcc" * 37
PATCHED = (
    b"\xcc" * 16
    + bytes.fromhex("3c087607c6864914000008")
    + b"\xcc" * 21
    + bytes.fromhex("3c087607c686d045000008")
    + b"\xcc" * 37
)


class EnginePatchTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.is_file(), "Отсутствует генератор бинарного патча")
        self.engine = importlib.import_module("patch_coop_player_limit")
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source = self.root / "xrGame.dll"
        self.source.write_bytes(IMAGE)
        self.output = self.root / "xrGame-cap8.dll"
        # Подмена констант существует только в тестовом процессе. В CLI нет
        # параметра выбора версии, адресов, сигнатур или пользовательского hash.
        profile = mock.patch.multiple(
            self.engine,
            EXPECTED_SIZE=96,
            EXPECTED_SHA256=hashlib.sha256(IMAGE).hexdigest(),
            PATCH_SITES=((16, CLIENT), (48, SERVER)),
        )
        profile.start()
        self.addCleanup(profile.stop)

    def test_changes_exactly_four_immediates_and_preserves_source_bytes(self):
        result = self.engine.patch_image(IMAGE)
        self.assertEqual(result, PATCHED)
        self.assertEqual(len(result), 96)
        self.assertEqual(
            [i for i, (old, new) in enumerate(zip(IMAGE, result)) if old != new],
            [17, 26, 49, 58],
        )
        self.assertEqual(IMAGE[17], 4)
        self.assertEqual(IMAGE[26], 4)
        self.assertEqual(IMAGE[49], 4)
        self.assertEqual(IMAGE[58], 4)

    def test_rejects_wrong_size_even_when_hash_matches(self):
        shortened = IMAGE[:-1]
        with mock.patch.object(
            self.engine, "EXPECTED_SHA256", hashlib.sha256(shortened).hexdigest()
        ):
            with self.assertRaisesRegex(self.engine.PatchError, "размер"):
                self.engine.patch_image(shortened)

    def test_rejects_unrecognized_hash_with_unchanged_patch_sites(self):
        changed = b"\x00" + IMAGE[1:]
        with self.assertRaisesRegex(self.engine.PatchError, "SHA256"):
            self.engine.patch_image(changed)

    def test_rejects_signature_mismatch_even_when_size_and_hash_match(self):
        for position in (18, 50):
            with self.subTest(position=position):
                changed = bytearray(IMAGE)
                changed[position] = 0x77  # Нельзя патчить изменённое ветвление.
                changed = bytes(changed)
                with mock.patch.object(
                    self.engine, "EXPECTED_SHA256", hashlib.sha256(changed).hexdigest()
                ):
                    with self.assertRaisesRegex(self.engine.PatchError, "сигнатур"):
                        self.engine.patch_image(changed)

    def test_rejects_already_patched_image(self):
        with self.assertRaises(self.engine.PatchError):
            self.engine.patch_image(PATCHED)

    def test_publishes_new_complete_file_without_changing_source(self):
        self.engine.patch_file(self.source, self.output)
        self.assertEqual(self.output.read_bytes(), PATCHED)
        self.assertEqual(self.source.read_bytes(), IMAGE)
        self.assertEqual({p.name for p in self.root.iterdir()}, {"xrGame.dll", "xrGame-cap8.dll"})

    def test_rejects_existing_output_and_preserves_it(self):
        self.output.write_bytes(b"keep existing")
        with self.assertRaises(self.engine.PatchError):
            self.engine.patch_file(self.source, self.output)
        self.assertEqual(self.output.read_bytes(), b"keep existing")
        self.assertEqual(self.source.read_bytes(), IMAGE)

    def test_rejects_in_place_output(self):
        with self.assertRaises(self.engine.PatchError):
            self.engine.patch_file(self.source, self.source)
        self.assertEqual(self.source.read_bytes(), IMAGE)

    def test_rejects_output_hardlink_to_input(self):
        os.link(self.source, self.output)
        with self.assertRaises(self.engine.PatchError):
            self.engine.patch_file(self.source, self.output)
        self.assertEqual(self.source.read_bytes(), IMAGE)
        self.assertEqual(self.output.read_bytes(), IMAGE)

    def test_rejects_input_symlink(self):
        link = self.root / "input-link.dll"
        link.symlink_to(self.source)
        with self.assertRaisesRegex(self.engine.PatchError, "[Сс]имволическ"):
            self.engine.patch_file(link, self.output)
        self.assertFalse(self.output.exists())

    def test_rejects_output_symlink_including_dangling_link(self):
        for target in (self.source, self.root / "missing.dll"):
            with self.subTest(target=target):
                self.output.symlink_to(target)
                try:
                    with self.assertRaises(self.engine.PatchError):
                        self.engine.patch_file(self.source, self.output)
                    self.assertTrue(self.output.is_symlink())
                    self.assertEqual(self.source.read_bytes(), IMAGE)
                    self.assertFalse((self.root / "missing.dll").exists())
                finally:
                    self.output.unlink()

    def test_rejects_symlink_parent_for_input_or_output(self):
        link = self.root / "linked-directory"
        link.symlink_to(self.root, target_is_directory=True)
        for source, output in (
            (link / "xrGame.dll", self.output),
            (self.source, link / "xrGame-cap8.dll"),
        ):
            with self.subTest(source=source, output=output):
                with self.assertRaisesRegex(self.engine.PatchError, "[Сс]имволическ"):
                    self.engine.patch_file(source, output)
                self.assertFalse(self.output.exists())

    def test_rejects_non_regular_input(self):
        with self.assertRaises(self.engine.PatchError):
            self.engine.patch_file(self.root, self.output)
        self.assertFalse(self.output.exists())

    def test_rejects_unrecognized_input_without_creating_output(self):
        self.source.write_bytes(b"\x00" + IMAGE[1:])
        with self.assertRaises(self.engine.PatchError):
            self.engine.patch_file(self.source, self.output)
        self.assertEqual({p.name for p in self.root.iterdir()}, {"xrGame.dll"})

    def test_publication_race_never_overwrites_competing_file(self):
        real_link = os.link

        def publish_after_competitor(temporary, destination, **kwargs):
            self.assertEqual(Path(temporary).read_bytes(), PATCHED)
            self.assertFalse(Path(destination).exists())
            Path(destination).write_bytes(b"another writer")
            return real_link(temporary, destination, **kwargs)

        with mock.patch.object(self.engine.os, "link", side_effect=publish_after_competitor):
            with self.assertRaises(self.engine.PatchError):
                self.engine.patch_file(self.source, self.output)
        self.assertEqual(self.output.read_bytes(), b"another writer")
        self.assertEqual(self.source.read_bytes(), IMAGE)
        self.assertEqual({p.name for p in self.root.iterdir()}, {"xrGame.dll", "xrGame-cap8.dll"})

    def test_failed_publication_leaves_no_output_or_temporary_file(self):
        with mock.patch.object(self.engine.os, "link", side_effect=OSError(errno.EPERM, "no links")):
            with self.assertRaises((OSError, self.engine.PatchError)):
                self.engine.patch_file(self.source, self.output)
        self.assertEqual({p.name for p in self.root.iterdir()}, {"xrGame.dll"})
        self.assertEqual(self.source.read_bytes(), IMAGE)

    def test_check_validates_without_creating_files(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            status = self.engine.main(["--input", str(self.source), "--check"])
        self.assertEqual(status, 0)
        self.assertIn(hashlib.sha256(IMAGE).hexdigest(), stdout.getvalue())
        self.assertEqual({p.name for p in self.root.iterdir()}, {"xrGame.dll"})

    def test_cli_keeps_official_whitelist_and_rejects_synthetic_image(self):
        command = [sys.executable, str(SCRIPT), "--input", str(self.source), "--check"]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("размер", result.stderr)
        self.assertEqual({p.name for p in self.root.iterdir()}, {"xrGame.dll"})

    def test_cli_requires_exactly_one_output_mode(self):
        for extra in ([], ["--check", "--output", str(self.output)]):
            with self.subTest(extra=extra):
                result = subprocess.run(
                    [sys.executable, str(SCRIPT), "--input", str(self.source), *extra],
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertFalse(self.output.exists())

    def test_success_reporting_does_not_fail_after_publication_on_ascii_console(self):
        # Иначе output уже создан, но пользователь получает traceback вместо успеха.
        raw_output = io.BytesIO()
        stdout = io.TextIOWrapper(raw_output, encoding="ascii")
        self.addCleanup(stdout.close)
        with contextlib.redirect_stdout(stdout):
            status = self.engine.main(
                ["--input", str(self.source), "--output", str(self.output)]
            )
        stdout.flush()
        self.assertEqual(status, 0)
        self.assertIn(hashlib.sha256(PATCHED).hexdigest().encode("ascii"), raw_output.getvalue())
        self.assertEqual(self.output.read_bytes(), PATCHED)

    def test_cli_help_is_usable_on_ascii_console(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--help"],
            capture_output=True,
            env={**os.environ, "PYTHONIOENCODING": "ascii"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(b"--check", result.stdout)

    def test_success_prohibits_configured_cap_above_four_for_any_player_count(self):
        # Ловит опасный отчёт об успехе, в котором DLL+LTX выглядят достаточными
        # для игры, хотя UI выходит за вектор исходных lobby RPoints.
        for mode in (["--check"], ["--output", str(self.output)]):
            with self.subTest(mode=mode):
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    status = self.engine.main(["--input", str(self.source), *mode])
                message = stdout.getvalue()
                self.assertEqual(status, 0)
                self.assertIn("статический", message)
                self.assertIn(
                    "Live-запуск с max_players >4 запрещён независимо от фактического "
                    "числа подключённых игроков; необходим проверенный патч данных лобби.",
                    message,
                )
                self.assertIn("отдельный проверенный патч данных лобби", message)
                self.assertIn("ещё разрабатывается", message)


if __name__ == "__main__":
    unittest.main()
