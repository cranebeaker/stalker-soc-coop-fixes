"""End-to-end test of installer\\install.ps1 (v1.5) on a synthetic >4 GiB add-on made of sparse files.
usage: python run_inst_test.py <repo> <original xrCore.dll> <work dir> <folder with install_xrcore_patch.ps1/.bat>
The work dir is deleted first; the add-on is a sparse file, so the test needs almost no disk space."""
import os
import shutil
import struct
import subprocess
import sys

repo, orig_dll, work, applier = sys.argv[1:5]
rel = os.path.join(work, "release")
game = os.path.join(work, "game")
shutil.rmtree(work, ignore_errors=True)
for d in (os.path.join(rel, "installer"), os.path.join(rel, "cutscenes"), os.path.join(rel, "xrcore_4gb"), os.path.join(game, "addons"), os.path.join(game, "bin"), os.path.join(game, "patches")):
    os.makedirs(d)
# release layout
shutil.copy(os.path.join(repo, "installer", "install.ps1"), os.path.join(rel, "installer", "install.ps1"))
open(os.path.join(rel, "installer", "install.bat"), "w").write('@echo off\r\npowershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" -Db "%~dp0..\\zzz_soc_coop_fixes.db" %*\r\n')
for name, size in (("zzz_soc_coop_fixes.db", 64 * 1024 * 1024 + 123), ("cutscenes\\zz_soc_cutscenes.db", 70 * 1024 * 1024 + 7),
                   ("cutscenes\\zz_soc_cutscenes_voice_rus.db", 10 * 1024 * 1024), ("cutscenes\\zz_soc_cutscenes_voice_eng.db", 10 * 1024 * 1024 + 1)):
    with open(os.path.join(rel, name), "wb") as f:
        f.write(os.urandom(4096)); f.truncate(size)
for fn in ("install_xrcore_patch.ps1", "install_xrcore_patch.bat"):
    shutil.copy(os.path.join(applier, fn), os.path.join(rel, "xrcore_4gb", fn))
shutil.copy(orig_dll, os.path.join(game, "bin", "xrCore.dll"))
open(os.path.join(game, "fsgame.ltx"), "w").write("; test\r\n")


def tar_hdr(name, size):
    h = bytearray(512)
    h[0:len(name)] = name.encode()
    h[100:108] = b"0000644\0"; h[108:116] = b"0000000\0"; h[116:124] = b"0000000\0"
    h[124:136] = (oct(size)[2:].rjust(11, "0") + "\0").encode()
    h[136:148] = b"00000000000\0"
    h[156:157] = b"0"
    h[148:156] = b"        "
    h[148:156] = (oct(sum(h))[2:].rjust(6, "0") + "\0 ").encode()
    return bytes(h)


addon = os.path.join(game, "addons", "coop.addon")
open(addon, "wb").close()
subprocess.run(["fsutil", "sparse", "setflag", addon], check=True, capture_output=True)
with open(addon, "r+b") as f:
    for name, size in (("gamedata.db0", 2140000000), ("gamedata.db1", 2140000000), ("icon.webp", 5000), ("metadata.json", 300)):
        f.write(tar_hdr(name, size))
        f.seek(((size + 511) // 512) * 512, 1)
    f.write(b"\0" * 1024)
    f.truncate(f.tell() + (-f.tell()) % 10240)
base_size = os.path.getsize(addon)
print("synthetic add-on: %.3f GiB (limit 4 GiB = 4294967296): %d bytes" % (base_size / 2**30, base_size))


def members(p):
    out = []
    with open(p, "rb") as f:
        pos = 0
        size_total = os.path.getsize(p)
        while pos + 512 <= size_total:
            f.seek(pos); h = f.read(512)
            if h == b"\0" * 512:
                break
            out.append((h[:100].split(b"\0")[0].decode(), int(h[124:135].decode().strip("\0 ") or "0", 8), pos))
            pos += 512 + ((out[-1][1] + 511) // 512) * 512
    return out


def run(*args):
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", os.path.join(rel, "installer", "install.ps1"),
                        "-Db", os.path.join(rel, "zzz_soc_coop_fixes.db"), "-Addon", addon] + list(args), capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, r.stdout + r.stderr


def sha(p):
    import hashlib
    return hashlib.sha256(open(p, "rb").read()).hexdigest()[:16]


ok = True


def check(name, cond, info=""):
    global ok
    print(("PASS " if cond else "FAIL ") + name + ((" : " + str(info)) if info != "" else ""))
    ok = ok and bool(cond)


dll = os.path.join(game, "bin", "xrCore.dll")
dll_orig = sha(dll)
# 1. over the limit with an unpatched engine and -NoEnginePatch: refused, nothing changed
rc, out = run("-NoEnginePatch")
check("over 4 GiB, engine not patched, -NoEnginePatch: refused", rc != 0 and "NOT INSTALLED" in out, "rc=%d" % rc)
check("   the add-on was not touched", os.path.getsize(addon) == base_size and [m[0] for m in members(addon)] == ["gamedata.db0", "gamedata.db1", "icon.webp", "metadata.json"])
check("   xrCore.dll untouched", sha(dll) == dll_orig)
# 2. default: patches the engine, installs fixes + movies, voice
rc, out = run("-Voice", "eng")
names = [m[0] for m in members(addon)]
check("default install succeeds", rc == 0, "rc=%d" % rc)
if rc != 0:
    print(out[-1500:])
check("   members", names == ["gamedata.db0", "gamedata.db1", "icon.webp", "metadata.json", "zzz_soc_coop_fixes.db", "zz_soc_cutscenes.db"], names)
check("   add-on is over 4 GiB", os.path.getsize(addon) > 4294967296, os.path.getsize(addon))
check("   the engine was patched automatically", sha(dll) != dll_orig and os.path.exists(dll + ".orig") and sha(dll + ".orig") == dll_orig)
check("   English movie sound in patches\\", os.path.exists(os.path.join(game, "patches", "zz_soc_cutscenes_voice_eng.db")) and not os.path.exists(os.path.join(game, "patches", "zz_soc_cutscenes_voice_rus.db")))
m = {x[0]: x for x in members(addon)}
with open(addon, "rb") as f:
    for name, src in (("zzz_soc_coop_fixes.db", os.path.join(rel, "zzz_soc_coop_fixes.db")), ("zz_soc_cutscenes.db", os.path.join(rel, "cutscenes", "zz_soc_cutscenes.db"))):
        f.seek(m[name][2] + 512)
        a = f.read(m[name][1]); b = open(src, "rb").read()
        check("   member %s is byte identical (%d bytes, starts at %d)" % (name, len(b), m[name][2]), a == b)
size1 = os.path.getsize(addon)
# 3. reinstall with the other language: same add-on size and members, voice file switched
rc, out = run("-Voice", "rus")
check("reinstall (-Voice rus) succeeds", rc == 0)
check("   same members and size", [x[0] for x in members(addon)] == names and os.path.getsize(addon) == size1)
check("   Russian sound now", os.path.exists(os.path.join(game, "patches", "zz_soc_cutscenes_voice_rus.db")) and not os.path.exists(os.path.join(game, "patches", "zz_soc_cutscenes_voice_eng.db")))
# 4. -NoCutscenes
rc, out = run("-NoCutscenes")
check("-NoCutscenes: only the fixes", rc == 0 and [x[0] for x in members(addon)][-1] == "zzz_soc_coop_fixes.db" and "zz_soc_cutscenes.db" not in [x[0] for x in members(addon)])
# 5. uninstall
rc, out = run("-Uninstall")
check("uninstall removes the patch files", rc == 0 and [x[0] for x in members(addon)] == ["gamedata.db0", "gamedata.db1", "icon.webp", "metadata.json"], os.path.getsize(addon))
check("   and the movie sound files", not any(os.path.exists(os.path.join(game, "patches", n)) for n in ("zz_soc_cutscenes_voice_rus.db", "zz_soc_cutscenes_voice_eng.db")))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
