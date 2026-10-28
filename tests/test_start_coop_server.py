"""Контракты выбора лимита и безопасного плана без запуска игры или Wine."""

import contextlib
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock


TOOLS = Path(__file__).resolve().parents[1] / "tools"
SCRIPT = TOOLS / "start_coop_server.py"
sys.path.insert(0, str(TOOLS))
PATCH_NAME = "zzz_coop_player_limit_1_8.db"
FIXTURE_DLL = b"cap8 DLL test profile; not an executable"
FIXTURE_DB = b"known config and lobby DB test profile"


def write_addon(path, members):
    with tarfile.open(path, "w", format=tarfile.USTAR_FORMAT) as archive:
        for name, payload in members:
            member = tarfile.TarInfo(name)
            member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))


def install_patch_fixture(test, starter, game):
    (game / "bin" / "xrGame.dll").write_bytes(FIXTURE_DLL)
    write_addon(game / "addons" / "coop.addon", [
        ("gamedata.db0", b"base0"), ("gamedata.db1", b"base1"),
        (PATCH_NAME, FIXTURE_DB), ("icon.png", b"metadata"),
    ])
    profile = mock.patch.multiple(
        starter,
        EXPECTED_ENGINE_SHA256=hashlib.sha256(FIXTURE_DLL).hexdigest(),
        EXPECTED_PATCH_DB_SHA256=hashlib.sha256(FIXTURE_DB).hexdigest(),
        EXPECTED_PATCH_DB_SIZE=len(FIXTURE_DB),
    )
    profile.start()
    test.addCleanup(profile.stop)


class ServerSelectionTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.is_file(), "Отсутствует CLI выбора лимита сервера")
        self.starter = importlib.import_module("start_coop_server")
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.game = self.root / "Игра с пробелами; $(touch injected)"
        (self.game / "bin" / "dedicated").mkdir(parents=True)
        (self.game / "addons").mkdir()
        self.engine = self.game / "bin" / "dedicated" / "xrEngine.exe"
        self.engine.write_bytes(b"fixture, never executed")
        (self.game / "fsgame_s.ltx").write_bytes(b"fixture")
        (self.game / "addons" / "coop.addon").write_bytes(b"fixture")
        self.wine = self.root / "Wine с пробелом"
        self.wine.write_bytes(b"fixture, never executed")
        self.wine.chmod(0o700)
        self.prefix = self.root / "Отдельный prefix"
        self.prefix.mkdir()
        (self.prefix / "drive_c").mkdir()
        (self.prefix / "dosdevices").mkdir()
        (self.prefix / "system.reg").write_bytes(b"fixture")
        (self.prefix / "user.reg").write_bytes(b"fixture")

    def cli(self, *args, answers=()):
        output, errors = io.StringIO(), io.StringIO()
        with (
            contextlib.redirect_stdout(output),
            contextlib.redirect_stderr(errors),
            mock.patch.object(self.starter.sys, "platform", "linux"),
            mock.patch.object(self.starter.shutil, "which", return_value=str(self.wine)),
            mock.patch("builtins.input", side_effect=answers),
        ):
            try:
                code = self.starter.main(["--game", str(self.game), *args])
            except SystemExit as error:
                code = error.code
        return code, output.getvalue(), errors.getvalue()

    def plan(self, players=5, **kwargs):
        return self.starter.build_launch_plan(
            self.game, players, platform="linux", wine=str(self.wine), **kwargs
        )

    def test_selected_limits_reach_single_start_argument(self):
        expected = {
            1: "server(coop_l01_escape/coop/hname=ShadowCoop/maxplayers=1/public=0/minplayers=1/portsv=5495) client(localhost)",
            5: "server(coop_l01_escape/coop/hname=ShadowCoop/maxplayers=5/public=0/minplayers=1/portsv=5495) client(localhost)",
            8: "server(coop_l01_escape/coop/hname=ShadowCoop/maxplayers=8/public=0/minplayers=1/portsv=5495) client(localhost)",
        }
        for players, start in expected.items():
            with self.subTest(players=players):
                code, output, errors = self.cli("--players", str(players), "--dry-run")
                self.assertEqual(code, 0, errors)
                plan = json.loads(output)
                self.assertEqual(plan["argv"], [
                    str(self.wine), str(self.engine), "-i", "-noprefetch", "-nointro",
                    "-fsltx", "..\\fsgame_s.ltx", "-use_all_spawn", "-addon=coop.addon",
                    "-start", start,
                ])
                self.assertEqual(plan["cwd"], str(self.game / "bin"))
                self.assertEqual(plan["players"], players)
                self.assertTrue(plan.get("launch_gate_open"))
                self.assertIsNone(plan["launch_allowed"])
                self.assertIsNone(plan["launch_block_reason"])
                self.assertEqual(plan["installation_check"], "required_before_launch")

    def test_explicit_profile_is_carried_in_plan_without_changing_argv(self):
        profile = self.root / "profile.json"
        plan = self.starter.build_launch_plan(self.game, 5, platform="win32", profile=profile)
        self.assertEqual(plan.profile, profile)
        self.assertEqual(plan.argv[-1], "server(coop_l01_escape/coop/hname=ShadowCoop/maxplayers=5/public=0/minplayers=1/portsv=5495) client(localhost)")

    def test_windows_plan_uses_native_executable_without_wine(self):
        plan = self.starter.build_launch_plan(self.game, 8, platform="win32")
        self.assertEqual(plan.argv[0], str(self.engine))
        self.assertEqual(plan.argv[1:5], ("-i", "-noprefetch", "-nointro", "-fsltx"))
        self.assertEqual(plan.cwd, self.game / "bin")
        self.assertEqual(plan.env_overrides, {})

    def test_invalid_cli_values_never_prepare_a_process(self):
        for value in ("0", "9", "five", "5.0", "5/public=1", "5;touch injected"):
            with self.subTest(value=value), mock.patch.object(subprocess, "run") as run:
                code, output, errors = self.cli("--players", value, "--dry-run")
                self.assertNotEqual(code, 0)
                self.assertEqual(output, "")
                self.assertIn("1", errors)
                self.assertIn("8", errors)
                run.assert_not_called()

    def test_core_rejects_values_outside_integer_contract(self):
        for value in (0, 9, "5", 5.0, True):
            with self.subTest(value=value), self.assertRaises(self.starter.LaunchError):
                self.plan(value)

    def test_prompt_accepts_choice_or_defaults_to_five(self):
        for answer, expected in (("1", 1), ("8", 8), ("", 5), ("  ", 5)):
            with self.subTest(answer=answer):
                code, output, errors = self.cli("--dry-run", answers=[answer])
                self.assertEqual(code, 0, errors)
                self.assertEqual(json.loads(output)["players"], expected)

    def test_invalid_prompt_has_clear_failure_without_retry_or_launch(self):
        code, output, errors = self.cli("--dry-run", answers=["9"])
        self.assertNotEqual(code, 0)
        self.assertEqual(output, "")
        self.assertIn("1", errors)
        self.assertIn("8", errors)

    def test_eof_does_not_silently_choose_default(self):
        code, output, errors = self.cli("--dry-run", answers=[EOFError])
        self.assertNotEqual(code, 0)
        self.assertEqual(output, "")
        self.assertIn("--players", errors)

    def test_missing_required_game_files_are_reported(self):
        for relative in ("bin/dedicated/xrEngine.exe", "fsgame_s.ltx", "addons/coop.addon"):
            with self.subTest(relative=relative):
                path = self.game / relative
                original = path.read_bytes()
                path.unlink()
                try:
                    code, output, errors = self.cli("--players", "5", "--dry-run")
                    self.assertNotEqual(code, 0)
                    self.assertEqual(output, "")
                    self.assertIn(path.name, errors)
                finally:
                    path.write_bytes(original)

    def test_dry_run_has_no_process_file_or_environment_side_effects(self):
        before_files = {p.relative_to(self.root): p.read_bytes()
                        for p in self.root.rglob("*") if p.is_file()}
        before_directories = {p.relative_to(self.root)
                              for p in self.root.rglob("*") if p.is_dir()}
        before_environment = dict(os.environ)
        with mock.patch.object(subprocess, "run") as run:
            code, output, errors = self.cli(
                "--players", "5", "--dry-run", "--wine-prefix", str(self.prefix)
            )
            self.assertEqual(code, 0, errors)
            run.assert_not_called()
        self.assertEqual(dict(os.environ), before_environment)
        self.assertEqual({p.relative_to(self.root): p.read_bytes()
                          for p in self.root.rglob("*") if p.is_file()}, before_files)
        self.assertEqual({p.relative_to(self.root)
                          for p in self.root.rglob("*") if p.is_dir()}, before_directories)
        plan = json.loads(output)
        self.assertEqual(plan["environment"], {
            "inherit": True, "overrides": {"WINEPREFIX": str(self.prefix)}
        })
        self.assertNotIn("PATH", output)

    def test_dry_run_does_not_require_or_create_a_wine_prefix(self):
        code, output, errors = self.cli("--players", "5", "--dry-run")
        self.assertEqual(code, 0, errors)
        self.assertEqual(json.loads(output)["environment"]["overrides"], {})
        absent = self.root / "missing prefix"
        code, _, errors = self.cli(
            "--players", "5", "--dry-run", "--wine-prefix", str(absent)
        )
        self.assertNotEqual(code, 0)
        self.assertIn("prefix", errors)
        self.assertFalse(absent.exists())

    def test_explicit_wine_path_is_one_argument(self):
        code, output, errors = self.cli(
            "--players", "5", "--dry-run", "--wine", str(self.wine)
        )
        self.assertEqual(code, 0, errors)
        self.assertEqual(json.loads(output)["argv"][:2], [str(self.wine), str(self.engine)])

    def test_missing_wine_is_reported_without_fallback_prefix(self):
        with mock.patch.object(self.starter.shutil, "which", return_value=None):
            with self.assertRaisesRegex(self.starter.LaunchError, "[Ww]ine"):
                self.starter.resolve_wine(None)
        code, _, errors = self.cli(
            "--players", "5", "--dry-run", "--wine", str(self.root / "missing-wine")
        )
        self.assertNotEqual(code, 0)
        self.assertIn("Wine", errors)

    def test_nosound_is_opt_in(self):
        self.assertNotIn("-nosound", self.plan().argv)
        code, output, errors = self.cli("--players", "5", "--dry-run", "--nosound")
        self.assertEqual(code, 0, errors)
        self.assertIn("-nosound", json.loads(output)["argv"])

    def test_real_cli_launch_is_blocked_while_lobby_data_is_unverified(self):
        with (
            mock.patch.object(self.starter, "LOBBY_DATA_VERIFIED", False),
            mock.patch.object(subprocess, "run") as run,
        ):
            code, output, errors = self.cli(
                "--players", "5", "--wine-prefix", str(self.prefix)
            )
            self.assertNotEqual(code, 0)
            self.assertEqual(output, "")
            self.assertIn("lobby data", errors)
            self.assertIn("не проверен", errors)
            run.assert_not_called()

    def test_launch_boundary_also_enforces_the_lobby_gate(self):
        with (
            mock.patch.object(self.starter, "LOBBY_DATA_VERIFIED", False),
            mock.patch.object(subprocess, "run") as run,
        ):
            with self.assertRaisesRegex(self.starter.LaunchError, "lobby data"):
                self.starter.launch(self.plan(wine_prefix=self.prefix))
            run.assert_not_called()

    def test_real_cli_reports_known_blocker_before_prompt_or_setup_checks(self):
        self.engine.unlink()
        for args in ((), ("--players", "5")):
            with (
                self.subTest(args=args),
                mock.patch.object(self.starter, "LOBBY_DATA_VERIFIED", False),
                mock.patch.object(subprocess, "run") as run,
            ):
                code, output, errors = self.cli(*args, answers=[EOFError])
                self.assertNotEqual(code, 0)
                self.assertEqual(output, "")
                self.assertIn("lobby data", errors)
                self.assertNotIn("Количество игроков", errors)
                run.assert_not_called()

    def test_closed_gate_dry_run_reports_closed_without_claiming_installation_readiness(self):
        with mock.patch.object(self.starter, "LOBBY_DATA_VERIFIED", False):
            code, output, errors = self.cli("--players", "5", "--dry-run")
        self.assertEqual(code, 0, errors)
        plan = json.loads(output)
        self.assertFalse(plan.get("launch_gate_open", True))
        self.assertFalse(plan["launch_allowed"])
        self.assertIn("lobby data", plan["launch_block_reason"])
        self.assertEqual(plan["installation_check"], "required_before_launch")

    def test_default_main_launches_only_after_real_fixture_checks(self):
        install_patch_fixture(self, self.starter, self.game)
        args = ["--game", str(self.game), "--players", "5"]
        if sys.platform.startswith("linux"):
            args += ["--wine", str(self.wine), "--wine-prefix", str(self.prefix)]
        output, errors = io.StringIO(), io.StringIO()
        with (
            contextlib.redirect_stdout(output),
            contextlib.redirect_stderr(errors),
            mock.patch.object(subprocess, "run", return_value=subprocess.CompletedProcess([], 7)) as run,
        ):
            code = self.starter.main(args)
        self.assertEqual(code, 7, errors.getvalue())
        self.assertEqual(output.getvalue(), "Ёмкость режима 8; выбранный лимит сессии 5\n")
        self.assertEqual(errors.getvalue(), "")
        self.assertIn("maxplayers=5/public=0", run.call_args.args[0][-1])
        self.assertFalse(run.call_args.kwargs["shell"])

    def test_default_main_rejects_unknown_profile_before_process(self):
        install_patch_fixture(self, self.starter, self.game)
        (self.game / "bin" / "xrGame.dll").write_bytes(b"unknown DLL")
        args = ["--game", str(self.game), "--players", "5"]
        if sys.platform.startswith("linux"):
            args += ["--wine", str(self.wine), "--wine-prefix", str(self.prefix)]
        output, errors = io.StringIO(), io.StringIO()
        with (
            contextlib.redirect_stdout(output),
            contextlib.redirect_stderr(errors),
            mock.patch.object(subprocess, "run") as run,
        ):
            code = self.starter.main(args)
            run.assert_not_called()
        self.assertEqual(code, 1)
        self.assertIn("SHA256", errors.getvalue())
        self.assertEqual(output.getvalue(), "")

    def test_future_linux_launch_requires_existing_explicit_prefix(self):
        empty = self.root / "empty prefix"
        empty.mkdir()
        with mock.patch.object(self.starter, "LOBBY_DATA_VERIFIED", True):
            for plan in (self.plan(), self.plan(wine_prefix=self.root / "absent"),
                         self.plan(wine_prefix=empty)):
                with self.subTest(plan=plan), mock.patch.object(subprocess, "run") as run:
                    with self.assertRaisesRegex(self.starter.LaunchError, "prefix"):
                        self.starter.launch(plan)
                    run.assert_not_called()
        self.assertFalse((self.root / "absent").exists())

    def test_future_linux_launch_refuses_default_user_prefix(self):
        home = self.root / "home"
        home.mkdir()
        default = home / ".wine"
        default.symlink_to(self.prefix, target_is_directory=True)
        with (
            mock.patch.object(self.starter, "LOBBY_DATA_VERIFIED", True),
            mock.patch.object(self.starter.Path, "home", return_value=home),
            mock.patch.object(subprocess, "run") as run,
        ):
            with self.assertRaisesRegex(self.starter.LaunchError, "~/.wine"):
                self.starter.launch(self.plan(wine_prefix=self.prefix))
            run.assert_not_called()

    def test_future_launch_keeps_paths_literal_uses_copied_environment_and_returns_status(self):
        install_patch_fixture(self, self.starter, self.game)
        plan = self.plan(wine_prefix=self.prefix)
        before_environment = dict(os.environ)
        output = io.StringIO()
        with (
            contextlib.redirect_stdout(output),
            mock.patch.object(self.starter, "LOBBY_DATA_VERIFIED", True),
            mock.patch.object(subprocess, "run", return_value=subprocess.CompletedProcess([], 7)) as run,
        ):
            self.assertEqual(self.starter.launch(plan), 7)
        args, kwargs = run.call_args
        self.assertEqual(args, (list(plan.argv),))
        self.assertEqual(kwargs["cwd"], plan.cwd)
        self.assertIs(kwargs["shell"], False)
        self.assertEqual(kwargs["env"]["WINEPREFIX"], str(self.prefix))
        self.assertIsNot(kwargs["env"], os.environ)
        self.assertEqual(dict(os.environ), before_environment)
        self.assertFalse((self.root / "injected").exists())
        self.assertEqual(output.getvalue(), "Ёмкость режима 8; выбранный лимит сессии 5\n")

    def test_future_native_launch_does_not_require_wine_prefix(self):
        install_patch_fixture(self, self.starter, self.game)
        plan = self.starter.build_launch_plan(self.game, 1, platform="win32")
        with (
            contextlib.redirect_stdout(io.StringIO()),
            mock.patch.object(self.starter, "LOBBY_DATA_VERIFIED", True),
            mock.patch.object(subprocess, "run", return_value=subprocess.CompletedProcess([], 0)),
        ):
            self.assertEqual(self.starter.launch(plan), 0)

    def encoded_cli(self, *args):
        environment = os.environ.copy()
        environment["PYTHONIOENCODING"] = "ascii"
        return subprocess.run(
            [sys.executable, "-B", str(SCRIPT), "--game", str(self.game), *args],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment, timeout=10,
            check=False,
        )

    def test_cli_dry_run_emits_utf8_json_under_ascii_stdio(self):
        result = self.encoded_cli("--players", "5", "--dry-run", "--wine", str(self.wine))
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))
        output = result.stdout.decode("utf-8")
        plan = json.loads(output)
        self.assertEqual(plan["cwd"], str(self.game / "bin"))
        self.assertEqual(plan["argv"][:2], [str(self.wine), str(self.engine)])
        self.assertEqual(plan["players"], 5)
        self.assertTrue(plan.get("launch_gate_open"))
        self.assertIsNone(plan["launch_allowed"])
        self.assertIsNone(plan["launch_block_reason"])
        self.assertEqual(plan["installation_check"], "required_before_launch")

    def test_cli_help_emits_utf8_under_ascii_stdio(self):
        result = self.encoded_cli("--help")
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))
        self.assertIn("Экспериментальный выбор 1–8 игроков", result.stdout.decode("utf-8"))
        self.assertEqual(result.stderr, b"")

    def test_import_does_not_change_stdio_encoding(self):
        environment = os.environ.copy()
        environment["PYTHONIOENCODING"] = "ascii"
        program = (
            "import sys; sys.path.insert(0, sys.argv[1]); "
            "before = (sys.stdout.encoding, sys.stderr.encoding); "
            "import start_coop_server; "
            "assert (sys.stdout.encoding, sys.stderr.encoding) == before; "
            "print('import leaves stdio unchanged')"
        )
        result = subprocess.run(
            [sys.executable, "-B", "-c", program, str(TOOLS)], stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, env=environment, timeout=10, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))
        self.assertEqual(result.stdout, b"import leaves stdio unchanged\n")


class PatchReadinessTests(unittest.TestCase):
    def setUp(self):
        self.starter = importlib.import_module("start_coop_server")
        self.assertTrue(hasattr(self.starter, "check_patch_installation"),
                        "Отсутствует проверка установленного комплекта")
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.game = Path(self.directory.name)
        (self.game / "bin" / "dedicated").mkdir(parents=True)
        (self.game / "addons").mkdir()
        self.addon = self.game / "addons" / "coop.addon"
        install_patch_fixture(self, self.starter, self.game)

    def check(self):
        self.starter.check_patch_installation(self.game)

    def repo_profile(self, payload=FIXTURE_DB):
        profile = {
            "schema_version": 1, "capacity": 8, "addon_version": "8.1",
            "engine": {"size": 7915520,
                       "original_sha256": "ef430b5f39628dcd03a4dd6e44b114559549660dd06d3f3218296d1eee1c462e",
                       "patched_sha256": "de8e7b892203abc0e7a667b1a56ad0844140f02a82461e8432edc6a3150f2860"},
            "patch_db": {"name": "zzz_soc_coop_fixes.db", "size": len(payload),
                         "sha256": hashlib.sha256(payload).hexdigest()},
        }
        path = self.game / "coop_player_limit_profile.json"
        path.write_text(json.dumps(profile), encoding="utf-8")
        write_addon(self.addon, [("gamedata.db0", b"base0"), ("icon.webp", b"icon"),
                                 ("gamedata.db1", b"base1"), ("zzz_soc_coop_fixes.db", payload)])
        return profile, path

    def test_generated_profile_accepts_large_db_with_bounded_streaming_reads(self):
        payload = b"verified DB" * 150000
        self.repo_profile(payload)
        with mock.patch.object(self.starter, "EXPECTED_ENGINE_SIZE", len(FIXTURE_DLL), create=True):
            real_open = Path.open
            class Reader:
                def __init__(self, stream): self.stream = stream
                def __getattr__(self, name): return getattr(self.stream, name)
                def read(self, size=-1):
                    self.assert_bound(size)
                    return self.stream.read(size)
                @staticmethod
                def assert_bound(size):
                    if not 0 <= size <= 256 * 1024: raise AssertionError(f"unbounded read {size}")
                def __enter__(self): return self
                def __exit__(self, *args): self.stream.close()
            def checked_open(path, *args, **kwargs):
                stream = real_open(path, *args, **kwargs)
                return Reader(stream) if path == self.addon else stream
            with mock.patch.object(Path, "open", checked_open):
                self.check()

    def test_generated_profile_rejects_unknown_engine_schema_and_db_fingerprint(self):
        profile, path = self.repo_profile()
        changes = (("capacity", 4), ("schema_version", True), ("addon_version", "9"),
                   ("engine", dict(profile["engine"], patched_sha256="0" * 64)),
                   ("patch_db", dict(profile["patch_db"], size=True)),
                   ("patch_db", dict(profile["patch_db"], name="../evil.db")),
                   ("patch_db", dict(profile["patch_db"], sha256="0" * 64)))
        for key, value in changes:
            with self.subTest(key=key, value=value):
                path.write_text(json.dumps(dict(profile, **{key: value})), encoding="utf-8")
                with mock.patch.object(self.starter, "EXPECTED_ENGINE_SIZE", len(FIXTURE_DLL), create=True):
                    with self.assertRaises(self.starter.LaunchError): self.check()

    def test_explicit_missing_or_invalid_profile_never_falls_back(self):
        missing = self.game / "missing.json"
        with self.assertRaises(self.starter.LaunchError):
            self.starter.check_patch_installation(self.game, profile=missing)
        missing.write_text("not JSON", encoding="utf-8")
        with self.assertRaises(self.starter.LaunchError):
            self.starter.check_patch_installation(self.game, profile=missing)

    def test_generated_profile_still_rejects_db_order_and_casefold_duplicates(self):
        self.repo_profile()
        for entries in (("gamedata.db1", "gamedata.db0", "zzz_soc_coop_fixes.db"),
                        ("gamedata.db0", "gamedata.db1", "zzz_soc_coop_fixes.db", "GAMEDATA.DB0")):
            write_addon(self.addon, [(name, FIXTURE_DB) for name in entries])
            with mock.patch.object(self.starter, "EXPECTED_ENGINE_SIZE", len(FIXTURE_DLL), create=True):
                with self.assertRaises(self.starter.LaunchError): self.check()

    def test_known_profile_passes_and_does_not_change_files_or_empty_runtime_dirs(self):
        (self.game / "gamedata" / "levels").mkdir(parents=True)
        before = {p.relative_to(self.game): p.read_bytes() if p.is_file() else None
                  for p in self.game.rglob("*")}
        self.check()
        self.assertEqual({p.relative_to(self.game): p.read_bytes() if p.is_file() else None
                          for p in self.game.rglob("*")}, before)
        dedicated = self.game / "bin" / "dedicated" / "xrGame.dll"
        dedicated.write_bytes(FIXTURE_DLL)
        self.check()

    def test_missing_or_wrong_main_dll_is_rejected(self):
        dll = self.game / "bin" / "xrGame.dll"
        for payload in (None, b"wrong DLL"):
            with self.subTest(payload=payload):
                dll.unlink(missing_ok=True)
                if payload is not None:
                    dll.write_bytes(payload)
                with self.assertRaisesRegex(self.starter.LaunchError, "xrGame.dll"):
                    self.check()

    def test_optional_dedicated_dll_must_match_when_present(self):
        dll = self.game / "bin" / "dedicated" / "xrGame.dll"
        dll.write_bytes(b"unpatched dedicated DLL")
        with self.assertRaisesRegex(self.starter.LaunchError, "xrGame.dll"):
            self.check()

    def test_missing_patch_member_is_rejected(self):
        write_addon(self.addon, [("gamedata.db0", b"base")])
        with self.assertRaisesRegex(self.starter.LaunchError, PATCH_NAME):
            self.check()

    def test_wrong_patch_size_is_rejected(self):
        write_addon(self.addon, [(PATCH_NAME, FIXTURE_DB + b"extra")])
        with self.assertRaisesRegex(self.starter.LaunchError, "размер"):
            self.check()

    def test_wrong_patch_hash_is_rejected(self):
        write_addon(self.addon, [(PATCH_NAME, b"x" * len(FIXTURE_DB))])
        with self.assertRaisesRegex(self.starter.LaunchError, "SHA256"):
            self.check()

    def test_duplicate_db_names_are_rejected_including_base_members(self):
        for name, payload in ((PATCH_NAME, FIXTURE_DB), ("gamedata.db0", b"base")):
            with self.subTest(name=name):
                write_addon(self.addon, [(PATCH_NAME, FIXTURE_DB), (name, payload), (name, payload)])
                with self.assertRaisesRegex(self.starter.LaunchError, "[Пп]овтор"):
                    self.check()

    def test_unexpected_db_names_and_noncanonical_paths_are_rejected(self):
        for name in ("other.db", "gamedata.db2", "dir/gamedata.db0", "./gamedata.db0", "GAMEDATA.DB0"):
            with self.subTest(name=name):
                write_addon(self.addon, [(PATCH_NAME, FIXTURE_DB), (name, b"unknown")])
                with self.assertRaisesRegex(self.starter.LaunchError, "DB"):
                    self.check()

    def test_patch_must_be_a_regular_tar_member(self):
        with tarfile.open(self.addon, "w") as archive:
            target = tarfile.TarInfo(PATCH_NAME)
            target.type = tarfile.SYMTYPE
            target.linkname = "gamedata.db0"
            archive.addfile(target)
        with self.assertRaises(self.starter.LaunchError):
            self.check()

    def test_invalid_tar_is_reported_as_launch_error(self):
        self.addon.write_bytes(b"not a tar")
        with self.assertRaisesRegex(self.starter.LaunchError, "coop.addon"):
            self.check()

    def test_loose_config_and_level_overrides_are_rejected(self):
        for relative in ("gamedata/configs/mp/cooperative_game.ltx", "gamedata/levels/l01_escape/level.game"):
            with self.subTest(relative=relative):
                loose = self.game / relative
                loose.parent.mkdir(parents=True, exist_ok=True)
                loose.write_bytes(b"override")
                try:
                    with self.assertRaisesRegex(self.starter.LaunchError, "[Ll]oose"):
                        self.check()
                finally:
                    loose.unlink()

    def test_review_requires_complete_canonical_db_sequence(self):
        entries = {"gamedata.db0": b"base0", "gamedata.db1": b"base1", PATCH_NAME: FIXTURE_DB}
        orders = (
            [PATCH_NAME, "gamedata.db0", "gamedata.db1"],
            ["gamedata.db1", "gamedata.db0", PATCH_NAME],
            ["gamedata.db0", PATCH_NAME],
            [PATCH_NAME],
        )
        for names in orders:
            with self.subTest(names=names):
                write_addon(self.addon, [(name, entries[name]) for name in names])
                with self.assertRaisesRegex(self.starter.LaunchError, "[Пп]орядок"):
                    self.check()
        write_addon(self.addon, [(name, entries[name]) for name in ("gamedata.db0", "gamedata.db1", PATCH_NAME)])
        self.check()

    def test_review_casefold_config_paths_are_rejected(self):
        for relative in ("gamedata/configs/mp/Cooperative_Game.ltx",
                         "GameData/Configs/MP/cooperative_game.ltx",
                         "GAMEDATA/CONFIGS/MP/COOPERATIVE_GAME.LTX"):
            with self.subTest(relative=relative):
                loose = self.game / relative
                loose.parent.mkdir(parents=True, exist_ok=True)
                loose.write_bytes(b"override")
                try:
                    with self.assertRaisesRegex(self.starter.LaunchError, "[Ll]oose"):
                        self.check()
                finally:
                    loose.unlink()

    def test_review_casefold_level_paths_are_rejected(self):
        for relative in ("gamedata/levels/l01_escape/Level.Game", "GameData/Levels/L01_ESCAPE/LEVEL.GAME"):
            with self.subTest(relative=relative):
                loose = self.game / relative
                loose.parent.mkdir(parents=True, exist_ok=True)
                loose.write_bytes(b"override")
                try:
                    with self.assertRaisesRegex(self.starter.LaunchError, "[Ll]oose"):
                        self.check()
                finally:
                    loose.unlink()

    def test_review_casefold_config_search_follows_symlink_directories(self):
        external = self.game / "external-configs"
        (external / "MP").mkdir(parents=True)
        (external / "MP" / "Cooperative_Game.ltx").write_bytes(b"override")
        (self.game / "gamedata").mkdir()
        (self.game / "gamedata" / "configs").symlink_to(external, target_is_directory=True)
        with self.assertRaisesRegex(self.starter.LaunchError, "[Ll]oose"):
            self.check()

    def test_review_casefold_level_search_follows_map_symlink(self):
        external = self.game / "external-map"
        external.mkdir()
        (external / "Level.Game").write_bytes(b"override")
        levels = self.game / "gamedata" / "levels"
        levels.mkdir(parents=True)
        (levels / "l01_escape").symlink_to(external, target_is_directory=True)
        with self.assertRaisesRegex(self.starter.LaunchError, "[Ll]oose"):
            self.check()

    def test_review_casefold_level_search_follows_levels_symlink(self):
        external = self.game / "external-levels"
        (external / "L01_ESCAPE").mkdir(parents=True)
        (external / "L01_ESCAPE" / "Level.Game").write_bytes(b"override")
        (self.game / "GameData").mkdir()
        (self.game / "GameData" / "Levels").symlink_to(external, target_is_directory=True)
        with self.assertRaisesRegex(self.starter.LaunchError, "[Ll]oose"):
            self.check()

    def test_review_empty_casefold_runtime_dirs_are_allowed(self):
        (self.game / "GameData" / "Levels" / "L01_ESCAPE").mkdir(parents=True)
        (self.game / "GameData" / "Configs" / "MP").mkdir(parents=True)
        self.check()

    def test_loose_ui_xml_is_rejected_with_casefold_paths(self):
        for relative in ("gamedata/configs/ui/coop_lobby_wnd.xml",
                         "GameData/Configs/UI/COOP_LOBBY_WND.XML"):
            with self.subTest(relative=relative):
                loose = self.game / relative
                loose.parent.mkdir(parents=True, exist_ok=True)
                loose.write_bytes(b"UI override")
                try:
                    with self.assertRaisesRegex(self.starter.LaunchError, "[Ll]oose"):
                        self.check()
                finally:
                    loose.unlink()

    def test_loose_ui_xml_is_rejected_through_symlink_directory(self):
        external = self.game / "external-ui"
        external.mkdir()
        (external / "Coop_Lobby_Wnd.xml").write_bytes(b"UI override")
        configs = self.game / "gamedata" / "configs"
        configs.mkdir(parents=True)
        (configs / "ui").symlink_to(external, target_is_directory=True)
        with self.assertRaisesRegex(self.starter.LaunchError, "[Ll]oose"):
            self.check()

    def test_future_launch_checks_profile_before_process_or_capacity_message(self):
        (self.game / "bin" / "xrGame.dll").write_bytes(b"unrecognized DLL")
        plan = self.starter.build_launch_plan(self.game, 5, platform="win32")
        output = io.StringIO()
        with (
            mock.patch.object(self.starter, "LOBBY_DATA_VERIFIED", True),
            mock.patch.object(subprocess, "run") as run,
            contextlib.redirect_stdout(output),
        ):
            with self.assertRaises(self.starter.LaunchError):
                self.starter.launch(plan)
            run.assert_not_called()
        self.assertEqual(output.getvalue(), "")

    def test_tar_metadata_is_skipped_by_seek_and_target_read_is_bounded(self):
        # Sparse tar >4 GiB: место занимает только header/маленький target.
        large_size = 4 * 1024 ** 3
        metadata = tarfile.TarInfo("metadata.bin")
        metadata.size = large_size
        target = tarfile.TarInfo(PATCH_NAME)
        target.size = len(FIXTURE_DB)
        with self.addon.open("wb") as output:
            for name in ("gamedata.db0", "gamedata.db1"):
                base = tarfile.TarInfo(name)
                output.write(base.tobuf(format=tarfile.USTAR_FORMAT))
            output.write(metadata.tobuf(format=tarfile.USTAR_FORMAT))
            output.seek(output.tell() + large_size)
            output.write(target.tobuf(format=tarfile.USTAR_FORMAT))
            output.write(FIXTURE_DB)
            output.write(b"\0" * ((-len(FIXTURE_DB)) % 512 + 1024))
        real_open = Path.open
        reads, seeks = [], []

        class AuditedReader:
            def __init__(self, source):
                self.source = source

            def __getattr__(self, name):
                return getattr(self.source, name)

            def read(self, count=-1):
                if not 0 <= count < 1024 ** 2:
                    raise AssertionError(f"Неограниченное чтение tar: {count}")
                reads.append(count)
                return self.source.read(count)

            def seek(self, offset, whence=0):
                seeks.append((offset, whence))
                return self.source.seek(offset, whence)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.source.close()

        def audited_open(path, *args, **kwargs):
            source = real_open(path, *args, **kwargs)
            return AuditedReader(source) if path == self.addon else source

        with (
            mock.patch.object(Path, "open", audited_open),
            mock.patch.object(Path, "read_bytes", side_effect=AssertionError("read_bytes запрещён")),
        ):
            self.check()
        self.assertLess(sum(reads), 64 * 1024)
        self.assertTrue(any(offset >= large_size for offset, _ in seeks))


if __name__ == "__main__":
    unittest.main()
