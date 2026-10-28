"""PowerShell/.NET installer contracts; no game or Wine is executed.

Set COOP_TEST_DLL to an unmodified supported xrGame.dll for the full fixture.
Set COOP_PWSH when PowerShell is outside PATH. Proprietary DLL bytes stay local.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
INSTALLER_ROOT = Path(os.environ.get("COOP_INSTALLER_ROOT", str(REPO)))
LIBRARY = INSTALLER_ROOT / "installer/player_limit.ps1"
PWSH = os.environ.get("COOP_PWSH") or shutil.which("pwsh") or shutil.which("powershell")
DLL = Path(os.environ.get("COOP_TEST_DLL", "/nonexistent/COOP_TEST_DLL"))
ORIGINAL = "ef430b5f39628dcd03a4dd6e44b114559549660dd06d3f3218296d1eee1c462e"
PATCHED = "de8e7b892203abc0e7a667b1a56ad0844140f02a82461e8432edc6a3150f2860"

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def quote(value):
    return "'" + str(value).replace("'", "''") + "'"

class PlayerInstallerSourceTests(unittest.TestCase):
    def test_installer_library_exists(self):
        self.assertTrue(LIBRARY.is_file(), "opt-in installer library is missing")

@unittest.skipUnless(PWSH and DLL.is_file(), "requires PowerShell and COOP_TEST_DLL fixture")
class PlayerInstallerTests(unittest.TestCase):
    def setUp(self):
        self.assertEqual(digest(DLL), ORIGINAL, "COOP_TEST_DLL must be the supported ORIGINAL DLL")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.game = self.root / "Game with spaces"
        (self.game / "bin/dedicated").mkdir(parents=True)
        (self.game / "addons").mkdir()
        self.dll = self.game / "bin/xrGame.dll"
        shutil.copyfile(DLL, self.dll)
        self.addon = self.game / "addons/coop.addon"
        self.make_addon()
        self.before_addon = self.addon.read_bytes()
        self.db = self.root / "zzz_soc_coop_fixes.db"
        self.db.write_bytes(b"small synthetic tested DB" * 100)
        self.profile = self.root / "coop_player_limit_profile.json"
        self.profile.write_text(json.dumps({"schema_version": 1, "capacity": 8, "addon_version": "8.1",
            "engine": {"size": 7915520, "original_sha256": ORIGINAL, "patched_sha256": PATCHED},
            "patch_db": {"name": self.db.name, "size": self.db.stat().st_size, "sha256": digest(self.db)}}), encoding="utf-8")

    def make_addon(self, extra=()):
        with tarfile.open(self.addon, "w", format=tarfile.USTAR_FORMAT) as archive:
            for name, value in [("gamedata.db0", b"base0"), ("metadata.json", b"{}"),
                                ("gamedata.db1", b"base1"), ("icon.webp", b"icon"), *extra]:
                member = tarfile.TarInfo(name)
                member.size = len(value)
                archive.addfile(member, io.BytesIO(value))

    def ps(self, command, ok=True):
        result = subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-Command",
            "$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.Encoding]::UTF8; . " + quote(LIBRARY) + "; " + command],
            text=True, encoding="utf-8", stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
        if ok: self.assertEqual(result.returncode, 0, result.stdout)
        else: self.assertNotEqual(result.returncode, 0, result.stdout)
        return result.stdout

    def install(self, prefix="", ok=True):
        return self.ps(prefix + "Install-CoopPlayerLimit -GamePath " + quote(self.game)
                       + " -Db " + quote(self.db) + " -ProfilePath " + quote(self.profile), ok=ok)

    def test_powershell_output_decodes_cyrillic_as_utf8(self):
        message = 'Сервер: ёмкость 8; резервная копия'
        self.assertIn(message, self.ps("Write-Output '" + message + "'"))

    def test_install_patches_four_bytes_preserves_backup_and_is_idempotent(self):
        dedicated = self.game / "bin/dedicated/xrGame.dll"
        shutil.copyfile(DLL, dedicated)
        self.install()
        self.assertEqual(digest(self.dll), PATCHED)
        self.assertEqual(digest(dedicated), PATCHED)
        before, after = DLL.read_bytes(), self.dll.read_bytes()
        self.assertEqual([i for i, (a, b) in enumerate(zip(before, after)) if a != b],
                         [0x2BE436, 0x2BE43F, 0x2F1A72, 0x2F1A7B])
        self.assertEqual((self.dll.with_name("xrGame.dll.cap8-original")).read_bytes(), before)
        self.assertEqual(self.addon.with_name("coop.addon.cap8-original").read_bytes(), self.before_addon)
        addon_hash = digest(self.addon)
        self.install()
        self.assertEqual(digest(self.addon), addon_hash)
        self.assertEqual(digest(self.dll), PATCHED)
        self.assertEqual((self.game / self.profile.name).read_bytes(), self.profile.read_bytes())
        self.ps("Test-CoopPlayerInstallation -GamePath " + quote(self.game))

    def test_unknown_dll_db_or_backup_refuses_without_changing_addon(self):
        for kind in ("dll", "dedicated", "db", "backup"):
            with self.subTest(kind=kind):
                self.setUp()
                target = {"dll": self.dll, "dedicated": self.game / "bin/dedicated/xrGame.dll",
                          "db": self.db, "backup": self.dll.with_name("xrGame.dll.cap8-original")}[kind]
                target.write_bytes(b"unknown bytes")
                self.install(ok=False)
                self.assertEqual(self.addon.read_bytes(), self.before_addon)
                self.assertFalse((self.game / self.profile.name).exists())

    def test_patched_dll_without_backup_refuses(self):
        self.install()
        self.dll.with_name("xrGame.dll.cap8-original").unlink()
        before = self.addon.read_bytes()
        self.install(ok=False)
        self.assertEqual(self.addon.read_bytes(), before)

    def test_failure_after_addon_publication_rolls_back_original_bytes(self):
        report = self.install(prefix="function Publish-CoopFile($Source,$Destination,$Rollback) { if ($Destination -like '*.dll') { throw 'injected DLL publish failure' }; [IO.File]::Replace($Source,$Destination,$Rollback) }; ", ok=False)
        self.assertIn("ROLLBACK COMPLETE", report)
        self.assertEqual(self.addon.read_bytes(), self.before_addon)
        self.assertEqual(digest(self.dll), ORIGINAL)
        self.assertFalse((self.game / self.profile.name).exists())

    def test_packaged_entrypoint_installs_and_uninstall_restores_whole_original(self):
        for uninstall in (False, True):
            command = [PWSH, "-NoProfile", "-File", str(INSTALLER_ROOT / "installer/install.ps1"),
                       "-Addon", str(self.addon), "-Db", str(self.db)]
            if uninstall: command.append("-Uninstall")
            result = subprocess.run(command, text=True, encoding="utf-8", stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertEqual(digest(self.dll), ORIGINAL if uninstall else PATCHED)
        self.assertEqual(self.addon.read_bytes(), self.before_addon)
        self.assertFalse((self.game / self.profile.name).exists())

    def test_native_selector_verifies_before_printing_single_session_argument(self):
        self.install()
        (self.game / "bin/dedicated/xrEngine.exe").write_bytes(b"never execute")
        (self.game / "fsgame_s.ltx").write_bytes(b"test")
        def selector(players, ok):
            r = subprocess.run([PWSH,"-NoProfile","-File",str(INSTALLER_ROOT / "installer/start_server_1_8.ps1"),
                "-GamePath",str(self.game),"-Players",players,"-DryRun"],
                text=True, encoding="utf-8", stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
            self.assertEqual(r.returncode == 0, ok, r.stdout)
            return r.stdout
        for players in ("1","5","8"):
            plan = json.loads(selector(players, True))
            self.assertEqual(plan["players"], int(players))
            self.assertEqual(plan["argv"][-1], f"server(coop_l01_escape/coop/hname=ShadowCoop/maxplayers={players}/public=0/minplayers=1/portsv=5495) client(localhost)")
        for players in ("0","9","5/public=1","5; exit 0"):
            selector(players, False)
        self.dll.write_bytes(b"unknown")
        selector("5", False)

    def test_installer_rejects_invalid_profiles_before_any_mutation(self):
        original=json.loads(self.profile.read_text(encoding="utf-8"))
        for value in (dict(original, capacity=4), dict(original, schema_version=True),
                      dict(original, engine=dict(original["engine"], patched_sha256="0"*64)),
                      dict(original, patch_db=dict(original["patch_db"], size=True))):
            self.profile.write_text(json.dumps(value), encoding="utf-8")
            self.install(ok=False)
            self.assertEqual(self.addon.read_bytes(),self.before_addon)
            self.assertEqual(digest(self.dll),ORIGINAL)

    def test_casefold_duplicate_db_refused_and_standard_db_upgrade_allowed(self):
        for extra in (("GAMEDATA.DB0",b"unknown"),("zzz_soc_coop_fixes.db",b"old"),("gamedata.db0",b"duplicate")):
            if extra[0] == "zzz_soc_coop_fixes.db":
                self.make_addon([extra])
                self.install()
                self.assertEqual(digest(self.dll),PATCHED)
                continue
            self.make_addon([extra]); before=self.addon.read_bytes()
            self.install(ok=False)
            self.assertEqual(self.addon.read_bytes(),before)

    def test_symlinked_loose_levels_refuse_when_symlinks_are_available(self):
        external=self.root/'external-map'; external.mkdir(); (external/'Level.Game').write_bytes(b'override')
        levels=self.game/'GameData/Levels'; levels.mkdir(parents=True)
        try:
            (levels/'L01_ESCAPE').symlink_to(external,target_is_directory=True)
        except (OSError,NotImplementedError) as error:
            self.skipTest(f"OS does not permit directory symlinks: {error}")
        self.install(ok=False)

    def test_entrypoint_refuses_alternate_addon_without_touching_either_file(self):
        selected=self.addon.with_name('copy-for-testing.addon')
        selected.write_bytes(self.before_addon)
        for flags in ([],['-Uninstall']):
            result=subprocess.run([PWSH,'-NoProfile','-File',str(INSTALLER_ROOT/'installer/install.ps1'),
                '-Addon',str(selected),'-Db',str(self.db),*flags],text=True,encoding="utf-8",
                stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=120)
            self.assertNotEqual(result.returncode,0,result.stdout)
            self.assertEqual(self.addon.read_bytes(),self.before_addon)
            self.assertEqual(selected.read_bytes(),self.before_addon)
            self.assertEqual(digest(self.dll),ORIGINAL)

    def test_over_4gib_tar_refuses_before_backups_or_publication(self):
        # Sparse file: exercises 64-bit offset/rounding without allocating 4 GiB.
        with self.addon.open("wb") as f:
            for name,size in (("gamedata.db0",2**32-5120),("gamedata.db1",1),("metadata.json",2),("icon.webp",1)):
                header=tarfile.TarInfo(name); header.size=size
                f.write(header.tobuf(format=tarfile.USTAR_FORMAT))
                f.seek(((size+511)//512)*512,1)
            f.write(b"\0"*1024)
        length=self.addon.stat().st_size
        output=self.install(ok=False)
        self.assertIn("4 GiB",output)
        self.assertEqual(self.addon.stat().st_size,length)
        self.assertFalse(self.addon.with_name("coop.addon.cap8-original").exists())
        self.assertEqual(digest(self.dll),ORIGINAL)

    def test_incompatible_addon_backup_refuses_even_with_same_concatenated_payloads(self):
        self.install()
        with tarfile.open(self.addon, "w", format=tarfile.USTAR_FORMAT) as archive:
            for name,value in (("gamedata.db0",b"base0{"),("metadata.json",b"}"),
                               ("gamedata.db1",b"base1"),("icon.webp",b"icon")):
                m=tarfile.TarInfo(name); m.size=len(value); archive.addfile(m,io.BytesIO(value))
        before=self.addon.read_bytes()
        self.install(ok=False)
        self.assertEqual(self.addon.read_bytes(),before)

    def test_uninstall_refuses_changed_addon_without_discarding_new_data(self):
        self.install()
        with tarfile.open(self.addon, "w", format=tarfile.USTAR_FORMAT) as archive:
            for name,value in (("gamedata.db0",b"new base update"),("metadata.json",b"{}"),
                               ("gamedata.db1",b"base1"),("icon.webp",b"icon"),
                               (self.db.name,self.db.read_bytes())):
                m=tarfile.TarInfo(name); m.size=len(value); archive.addfile(m,io.BytesIO(value))
        before=self.addon.read_bytes()
        self.ps("Restore-CoopPlayerLimit -GamePath "+quote(self.game),ok=False)
        self.assertEqual(self.addon.read_bytes(),before)
        self.assertEqual(digest(self.dll),PATCHED)
        self.assertTrue((self.game/self.profile.name).is_file())

    def test_uninstall_marker_failure_rolls_back_published_addon_and_dll(self):
        self.install()
        before=self.addon.read_bytes(); profile=(self.game/self.profile.name).read_bytes()
        output=self.ps("function Remove-CoopFile($Target,$Rollback) { throw 'injected marker removal failure' }; Restore-CoopPlayerLimit -GamePath "+quote(self.game),ok=False)
        self.assertIn('ROLLBACK COMPLETE',output)
        self.assertEqual(self.addon.read_bytes(),before)
        self.assertEqual(digest(self.dll),PATCHED)
        self.assertEqual((self.game/self.profile.name).read_bytes(),profile)

    def test_unknown_extra_db_and_casefold_loose_overrides_refuse(self):
        self.make_addon([("another_mod.db", b"mod")])
        before = self.addon.read_bytes()
        self.install(ok=False)
        self.assertEqual(self.addon.read_bytes(), before)
        self.make_addon()
        loose = self.game / "GameData/Configs/UI/COOP_LOBBY_WND.XML"
        loose.parent.mkdir(parents=True)
        loose.write_bytes(b"override")
        self.install(ok=False)
        self.assertEqual(digest(self.dll), ORIGINAL)

    def test_default_installer_keeps_legacy_behavior_without_profile(self):
        legacy = self.root / "legacy"; legacy.mkdir()
        db = legacy / self.db.name; shutil.copyfile(self.db, db)
        result = subprocess.run([PWSH, "-NoProfile", "-File", str(INSTALLER_ROOT / "installer/install.ps1"),
                                 "-Addon", str(self.addon), "-Db", str(db)],
                                text=True, encoding="utf-8", stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(digest(self.dll), ORIGINAL)
        with tarfile.open(self.addon) as archive:
            self.assertEqual(archive.extractfile(self.db.name).read(), self.db.read_bytes())

    def test_legacy_install_and_uninstall_refuse_installed_capacity8_before_mutation(self):
        self.install()
        before=self.addon.read_bytes()
        legacy=self.root/'legacy-package'; legacy.mkdir()
        shutil.copyfile(INSTALLER_ROOT/'installer/install.ps1',legacy/'install.ps1')
        shutil.copyfile(self.db,legacy/self.db.name)
        for args in ([],['-Uninstall']):
            result=subprocess.run([PWSH,'-NoProfile','-File',str(legacy/'install.ps1'),
                '-Addon',str(self.addon),'-Db',str(legacy/self.db.name),*args],
                text=True,encoding="utf-8",stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=120)
            self.assertNotEqual(result.returncode,0,result.stdout)
            self.assertEqual(self.addon.read_bytes(),before)
            self.assertEqual(digest(self.dll),PATCHED)
        (self.game/self.profile.name).unlink()
        result=subprocess.run([PWSH,'-NoProfile','-File',str(legacy/'install.ps1'),
            '-Addon',str(self.addon),'-Db',str(legacy/self.db.name)],
            text=True,encoding="utf-8",stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=120)
        self.assertNotEqual(result.returncode,0,result.stdout)
        self.assertEqual(self.addon.read_bytes(),before)
