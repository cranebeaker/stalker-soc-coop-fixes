"""Release default compatibility and opt-in packaging, without publishing or booting."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("coop_release", REPO / "tools/release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)

class ReleasePlayerLimitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / "zzz_soc_coop_fixes.db"; self.db.write_bytes(b"synthetic DB")
        self.profile = self.root / "coop_player_limit_profile.json"
        self.profile.write_text(json.dumps({"schema_version": 1, "capacity": 8, "addon_version": "8.1",
            "engine": {"size": 7915520,
                "original_sha256": "ef430b5f39628dcd03a4dd6e44b114559549660dd06d3f3218296d1eee1c462e",
                "patched_sha256": "de8e7b892203abc0e7a667b1a56ad0844140f02a82461e8432edc6a3150f2860"},
            "patch_db": {"name": self.db.name, "size": self.db.stat().st_size,
                         "sha256": hashlib.sha256(self.db.read_bytes()).hexdigest()}}))

    def package(self, **kwargs):
        return release.step_package("1.4.7", str(self.db), [], str(self.root), release.Report(), True, **kwargs)

    def test_default_zip_has_exact_legacy_inventory_even_with_stale_profile_near_db(self):
        folder, archive = self.package()
        self.assertEqual(Path(folder).name, "SoC_COOP_fixes_v1.4.7")
        with zipfile.ZipFile(archive) as z:
            self.assertEqual(sorted(z.namelist()), ["README.txt", "installer/install.bat", "installer/install.ps1", "zzz_soc_coop_fixes.db"])

    def test_opt_in_zip_contains_profile_patcher_selector_and_bilingual_instructions(self):
        folder, archive = self.package(player_limit=8)
        self.assertEqual(Path(folder).name, "SoC_COOP_fixes_v1.4.7_players8")
        with zipfile.ZipFile(archive) as z:
            self.assertEqual(sorted(z.namelist()), sorted([
                "README.txt", "zzz_soc_coop_fixes.db", "coop_player_limit_profile.json",
                "installer/install.bat", "installer/install.ps1", "installer/player_limit.ps1",
                "Start-Server-1-8.bat", "installer/start_server_1_8.ps1",
                "tools/start_coop_server.py", "tools/patch_coop_player_limit.py",
                "PLAYER_LIMIT_8.en.md", "PLAYER_LIMIT_8.ru.md"]))
            self.assertEqual(z.read(self.profile.name), self.profile.read_bytes())
            self.assertIn("capacity 8", z.read("README.txt").decode("utf-8"))
            self.assertFalse(any(n.lower().endswith(".dll") for n in z.namelist()))

    def test_opt_in_missing_or_mismatched_profile_refuses_packaging(self):
        self.profile.unlink()
        self.assertIsNone(self.package(player_limit=8))
        self.setUp()
        self.db.write_bytes(b"different DB")
        self.assertIsNone(self.package(player_limit=8))

    def test_build_forwards_opt_in_only_and_rejects_stale_profile_on_failed_build(self):
        for limit, expected in ((None, False), (8, True)):
            with self.subTest(limit=limit), mock.patch.object(release, "py", return_value=(1, "stop before build")) as run:
                self.assertIsNone(release.step_build([], str(self.root), release.Report(), player_limit=limit))
                arguments = run.call_args.args
                self.assertEqual("--player-limit" in arguments, expected)
                if expected:
                    self.assertEqual(arguments[arguments.index("--player-limit") + 1], "8")
                    self.assertFalse(self.profile.exists())

    def test_cli_accepts_historical_missing_default_skip_but_rejects_explicit_unknown(self):
        import contextlib, io, sys
        with mock.patch.object(release, "DEFAULT_SKIP", ["retired_default_patch"]):
            for extra, expected in (([], 1), (["--skip=retired_default_patch"], 2)):
                with mock.patch.object(sys, "argv", ["release.py","1.4.7","--out",str(self.root),*extra]), \
                     mock.patch.object(release,"step_conflicts",return_value=False), \
                     mock.patch.object(release,"step_escapes",return_value=True), \
                     contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(release.main(),expected)
