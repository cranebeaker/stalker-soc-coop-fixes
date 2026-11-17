#!/usr/bin/env python
"""One-command release of the Shadow of COOP fix patch (nothing is published, everything stays on disk).

  python tools\\release.py <version> [--skip=a,b|none] [--levels all|l1,l2,..] [--out DIR] [--dry-run]
                           [--owner NAME] [--parallel N] [--no-boot] [--no-installer-test] [--soak SEC] [--min-free-gb 10]

Steps (each prints one line; a summary table and release_report.txt/json close the run):
  1 conflicts   tools\\check_conflicts.py. Only the documented expected conflicts (EXPECTED_CONFLICTS below) or byte-identical copies pass,
                anything else fails the release: two patches ship the same file and the last one silently wins.
  2 escapes     tools\\check_lua_escapes.py. Findings in shipped gamedata of non-skipped patches must be in KNOWN_ESCAPES (original-code baseline).
  3 build       build.py -> <out>\\stage\\gamedata + zzz_soc_coop_fixes.db, then the db is read back (entry count / bytes vs the stage).
  3b budget   the db must fit under 4 GiB together with coop.addon (32-bit tar offsets); else FAIL (a real run stops; a --dry-run only WARNs,
                lists the biggest patches and goes on packaging, so the zip and README can still be inspected).
  4 boot        every level in --levels (default all 18) through tools\\stalker_xrmpe\\run_coop.ps1 with the finished compressed db as -DbFile
                (dedicated server + 1 client, boot + spawn + short soak).  The Bar only comes alive when reached from Cordon: it runs through
                tools\\release_boot_travel.lua (qa_lib.travel, listen mode).  Before every launch: wait while more than 6 xrEngine.exe run and
                while less than --min-free-gb GB of disk is free.  Lane copies (addons\\qalane<N>.addon) are used by run_coop automatically.
  5 package     <out>\\SoC_COOP_fixes_v<version>\\  README.txt (version/date filled), zzz_soc_coop_fixes.db, installer\\install.bat + install.ps1,
                and SoC_COOP_fixes_v<version>.zip next to it.
  6 installer   the packaged installer is run against a tiny synthetic coop.addon in a temp folder (never the real one): install, same
                fingerprint twice, uninstall.

--dry-run: steps 1, 2, 3, 5 and 6 run for real into --out (cheap, about a minute); step 4 only PRINTS the commands it would run and no game is
           started.  The report says DRY-RUN, so a dry-run zip is never mistaken for a release that was boot-checked.
--skip     patch folders left out of the release, same meaning as build.py (default: the v1.3 list, DEFAULT_SKIP).  --skip=none skips nothing.
Exit code 0 only if every executed step passed.
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
GAMES = os.path.dirname(REPO)
# the test harness ships in this repo (tools\stalker_xrmpe); an older checkout kept it next to the repo
QA_TOOLS = os.path.join(HERE, "stalker_xrmpe")
if not os.path.isdir(QA_TOOLS):
    QA_TOOLS = os.path.join(GAMES, "tools", "stalker_xrmpe")
RUN_COOP = os.path.join(QA_TOOLS, "run_coop.ps1")
GAME_DIR = os.environ.get("XRMPE_GAME", r"C:\X-Ray Multiplayer Extension\game")

# patches left out of the release by default (unfinished work), as in stalker.md section 3
DEFAULT_SKIP = ["soc_levels", "weapon_upgrades", "npc_attachments", "arrival_facing", "inventory_carry"]

ALL_LEVELS = ["coop_l01_escape", "coop_l02_garbage", "coop_l03_agroprom", "coop_l03_agroprom_underground", "coop_l04_darkvalley",
              "coop_l04_x18", "coop_l05_bar", "coop_l06_rostok", "coop_l07_military", "coop_l08_yantar", "coop_l08_x16", "coop_l09_radar",
              "coop_l09_x10", "coop_l10_pripyat", "coop_l11_stancia_1", "coop_l11_stancia_2", "coop_l11_control_monolith", "coop_l11_sarcofag"]
# levels that only come alive when reached from Cordon through the guide vote: level -> guide destination
ROUTE_LEVELS = {"coop_l05_bar": "bar"}   # release_boot_travel.lua travels to "bar" by default; run_coop -File takes one -Cfg only, so other destinations need their own hook copy
ROUTE_SOAK = 330   # seconds: vote + level load + 20 s soak on the target level


def expected_conflict(rel, owners):
    """True when this shared file is one of the documented expected conflicts (stalker.md section 3)."""
    rel = rel.lower().replace("/", "\\")
    if rel == r"configs\gameplay\dialogs_coop_l01_escape.xml":      # quest_dialogs is built on cordon's copy
        return owners == ["cordon", "quest_dialogs"]
    if rel == r"configs\gameplay\npc_profile_addon.xml":            # freedom_duty is a superset
        return owners == ["cordon_technician", "freedom_duty"]
    if re.fullmatch(r"configs\\ui\\coop_scn_[a-z0-9_]+\.xml", rel):  # cutscenes_core stubs replaced by the packages
        return len(owners) == 2 and owners[0] == "cutscenes_core" and owners[1].startswith("cutscenes_pkg_")
    return False


# check_lua_escapes.py findings that exist in the shipped code on purpose / came with the original SoC scripts.
# (patch, file name, distinctive text that must appear in the offending line, whitespace ignored).  Anything new fails the release.
KNOWN_ESCAPES = [
    ("campfires", "gulag_general.script", '"\scripts\\\\"'),                              # original SoC line
    ("cnpp_shake", "xr_effects.dscript", 'monsters\effects\polter_spark'),                 # twice, unchanged since v1.3
    ("stash_loot", "stash_loot.script", '[%w_%-.\]+)%p*'),                                  # original SoC pattern
]


class Report:
    def __init__(self):
        self.rows = []     # (step, status, seconds, detail)
        self.notes = []    # lines at the end of the report: what a WARN means and what to do about it
        self.t0 = time.time()

    def add(self, step, status, secs, detail="", quiet=False):
        self.rows.append({"step": step, "status": status, "seconds": round(secs, 1), "detail": detail})
        if not quiet:
            print("[%-9s] %-7s %6.1fs  %s" % (step, status, secs, detail), flush=True)

    def failed(self):
        return [r for r in self.rows if r["status"] in ("FAIL",)]

    def warned(self):
        return [r for r in self.rows if r["status"] == "WARN"]


def run(cmd, cwd=None, timeout=None, env=None):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, timeout=timeout, env=env)
    out = (p.stdout or b"").decode("utf-8", "replace") + (p.stderr or b"").decode("utf-8", "replace")
    return p.returncode, out


def run_logged(cmd, log_path, timeout):
    """Like run(), but the output goes into log_path while the command runs (run_coop's own run.log only appears after it got a slot lease,
    so a queued boot check used to leave an empty folder)."""
    with open(log_path, "wb") as lf:
        p = subprocess.Popen(cmd, stdout=lf, stderr=subprocess.STDOUT)
        try:
            p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            p.kill()
            raise
    with open(log_path, "rb") as f:
        return p.returncode, f.read().decode("utf-8", "replace")


def set_status(rdir, text):
    try:
        with open(os.path.join(rdir, "STATUS.txt"), "w", encoding="utf-8") as f:
            f.write("%s  %s\n" % (time.strftime("%H:%M:%S"), text))
    except OSError:
        pass


def py(*args, **kw):
    return run([sys.executable, "-I"] + list(args), **kw)


# ---------------------------------------------------------------------------------------------------------- 1 and 2 offline checks
def step_conflicts(skip, rep):
    t = time.time()
    rc, out = py(os.path.join(HERE, "check_conflicts.py"), *skip)
    bad, notes = [], []
    for line in out.splitlines():
        m = re.match(r"^(\S+)\s+(.+?)(\s+\(identical\))?\s*$", line)
        if not m or "files shipped by more than one patch" in line:
            continue
        rel, owners = m.group(1), [o.strip() for o in m.group(2).split(",")]
        if m.group(3):
            notes.append(rel + " (identical)")
        elif expected_conflict(rel, owners):
            notes.append(rel)
        else:
            bad.append("%s: %s" % (rel, ", ".join(owners)))
    if rc != 0:
        rep.add("conflicts", "FAIL", time.time() - t, "check_conflicts.py exit %d: %s" % (rc, out.strip()[-200:]))
        return False
    if bad:
        rep.add("conflicts", "FAIL", time.time() - t, "UNEXPECTED: " + " | ".join(bad))
        return False
    rep.add("conflicts", "PASS", time.time() - t, "%d shared files, all expected or identical" % len(notes))
    return True


def step_escapes(skip, rep):
    t = time.time()
    rc, out = py(os.path.join(HERE, "check_lua_escapes.py"))
    found, ignored_known, ignored_scope = [], 0, 0
    for line in out.splitlines():
        m = re.match(r"^(.+?):(\d+): (.*)$", line)
        if not m:
            continue
        rel, text = m.group(1).replace("/", "\\"), m.group(3)
        parts = rel.split("\\")
        if len(parts) < 3 or parts[1].lower() != "gamedata" or parts[0] in skip:
            ignored_scope += 1      # tests, wip folders and skipped patches are not shipped
            continue
        key = re.sub(r"\s+", "", text)
        if any(parts[0] == p and parts[-1] == f and re.sub(r"\s+", "", k) in key for p, f, k in KNOWN_ESCAPES):
            ignored_known += 1
            continue
        found.append("%s:%s" % (rel, m.group(2)))
    if rc != 0:
        rep.add("escapes", "FAIL", time.time() - t, "check_lua_escapes.py exit %d" % rc)
        return False
    if found:
        rep.add("escapes", "FAIL", time.time() - t, "NEW suspicious Lua string(s): " + " | ".join(found))
        return False
    rep.add("escapes", "PASS", time.time() - t, "no new findings (%d known original-code lines, %d outside the shipped files)" % (ignored_known, ignored_scope))
    return True


# ---------------------------------------------------------------------------------------------------------- 3 build
def step_build(skip, out_dir, rep, dry=False, version=None, player_limit=None):
    t = time.time()
    stage = os.path.join(out_dir, "stage")
    db = os.path.join(out_dir, "zzz_soc_coop_fixes.db")
    shutil.rmtree(stage, ignore_errors=True)
    if os.path.exists(db):
        os.remove(db)
    os.makedirs(stage, exist_ok=True)
    args = [os.path.join(REPO, "build.py"), db, "--skip=" + ",".join(skip) if skip else "--skip=", "--stage=" + stage, "--no-budget-check"]
    if player_limit == 8:
        profile = os.path.join(out_dir, "coop_player_limit_profile.json")
        if os.path.exists(profile):
            os.remove(profile)
        args.extend(["--player-limit", "8"])
    rc, out = py(*args, cwd=REPO)   # step_budget below does the 4 GiB check
    if rc != 0 or not os.path.exists(db):
        rep.add("build", "FAIL", time.time() - t, "build.py exit %d: %s" % (rc, out.strip()[-300:]))
        return None
    # read the db back and compare with the stage folder
    sys.path.insert(0, os.path.join(REPO, "tools"))
    import xdb  # noqa: E402
    n_stage, b_stage = 0, 0
    for dp, _, fs in os.walk(os.path.join(stage, "gamedata")):
        for f in fs:
            sz = os.path.getsize(os.path.join(dp, f))
            if sz > 0:                      # empty files look like directories in the index
                n_stage += 1
                b_stage += sz
    with open(db, "rb") as f:
        ents = xdb.index(f, 0, os.path.getsize(db))
    files = [e for e in ents if e[1] > 0]
    n_db, b_db = len(files), sum(e[1] for e in files)
    if n_db != n_stage or b_db != b_stage or n_db < 100:
        rep.add("build", "FAIL", time.time() - t, "db holds %d files / %d bytes, stage %d / %d" % (n_db, b_db, n_stage, b_stage))
        return None
    rep.add("build", "PASS", time.time() - t, "%d files, db %.1f MB, skipped: %s" % (n_db, os.path.getsize(db) / 2**20, ",".join(skip) or "none"))
    if not step_budget(db, rep, dry, skip, version):
        return None
    return stage, db


def previous_release_db(version):
    """Newest earlier release db we can find (Downloads\\SoC_COOP_fixes_v<older>\\zzz_soc_coop_fixes.db), or None.  Returns (label, path)."""
    def key(v):
        return [int(x) for x in re.findall(r"\d+", v)]
    best = None
    base = os.path.join(os.path.expanduser("~"), "Downloads")
    try:
        names = os.listdir(base)
    except OSError:
        return None
    for n in names:
        m = re.fullmatch(r"SoC_COOP_fixes_v(\d+(?:\.\d+){1,2})", n)
        db = os.path.join(base, n, "zzz_soc_coop_fixes.db")
        if m and os.path.exists(db) and key(m.group(1)) < key(version) and (best is None or key(m.group(1)) > key(best[0])):
            best = (m.group(1), db)
    return best


def patch_sizes(skip, version=None):
    """({patch: bytes}, label).  Bytes of the files that are NEW or different in size since the previous release db (label 'new since vX'), or of the
    whole gamedata when no previous release is found (label 'total')."""
    prev, label = {}, "total"
    pr = previous_release_db(version) if version else None
    if pr:
        try:
            sys.path.insert(0, os.path.join(REPO, "tools"))
            import xdb  # noqa: E402
            with open(pr[1], "rb") as f:
                prev = {e[0].lower().replace("/", "\\"): e[1] for e in xdb.index(f, 0, os.path.getsize(pr[1])) if e[1] > 0}
            label = "new since v" + pr[0]
        except Exception:  # noqa: BLE001
            prev, label = {}, "total"
    out = {}
    pdir = os.path.join(REPO, "patches")
    for p in sorted(os.listdir(pdir)):
        g = os.path.join(pdir, p, "gamedata")
        if p in skip or not os.path.isdir(g):
            continue
        n = 0
        for dp, _, fs in os.walk(g):
            for f in fs:
                sz = os.path.getsize(os.path.join(dp, f))
                rel = os.path.relpath(os.path.join(dp, f), g).lower()
                if label == "total" or prev.get(rel) != sz:
                    n += sz
        out[p] = n
    return out, label


def step_budget(db, rep, dry=False, skip=(), version=None):
    """coop.addon is a tar read with 32-bit offsets: base data + the patch db must stay below 4 GiB (4294967296 bytes), otherwise the
    engine fails with 'Cannot map addon file ... Not enough memory resources' at level load (seen 2026-10-20 with a 92 MB db) and the
    installer would produce a broken addon on every player's PC.  Budget = 4 GiB - end of the base entries - tar end blocks."""
    t = time.time()
    addon = os.path.join(GAME_DIR, "addons", "coop.addon")
    if not os.path.exists(addon):
        rep.add("budget", "SKIP", time.time() - t, "coop.addon not found, 4 GiB budget not checked")
        return True
    sys.path.insert(0, QA_TOOLS)
    try:
        import xdb as xdb_game  # noqa: E402  (tools/stalker_xrmpe/xdb.py: tar_members)
        members = xdb_game.tar_members(addon)
    except Exception as e:  # noqa: BLE001
        rep.add("budget", "SKIP", time.time() - t, "could not read coop.addon: %r" % e)
        return True
    base_names = ("gamedata.db0", "gamedata.db1", "icon.webp", "metadata.json")
    base_end = max(off + ((size + 511) // 512) * 512 for name, (off, size) in members.items() if name in base_names)
    sys.path.insert(0, os.path.join(REPO, "tools"))
    import budget  # noqa: E402  (tools/budget.py: the same arithmetic as build.py and the installer)
    limit = budget.room(base_end)                   # tar header + end-of-archive record + 4 MB margin below 4 GiB, for the db AS WRITTEN (compressed)
    size = os.path.getsize(db)
    detail = "db %.1f MB (compressed, as shipped), headroom %.1f MB (room %.1f MB under 4 GiB minus 4 MB margin; base data ends at %.3f GB)" % (
        size / 2**20, (limit - size) / 2**20, limit / 2**20, base_end / 1e9)
    if size > limit:
        over = (size - limit) / 2**20
        sizes, label = patch_sizes(skip, version)
        top = sorted(sizes.items(), key=lambda kv: -kv[1])
        pick, got = [], 0
        for k, v in top:                       # smallest set of the biggest patches that covers the overshoot
            if got >= over * 2**20 or v <= 0:
                break
            pick.append(k)
            got += v
        hint = ("cut at least %.0f MB. Biggest patches (%s): %s. Example: --skip=%s (or shrink assets: all.spawn 41 MB, *.ogm 12 MB)"
                % (over, label, ", ".join("%s %.0f MB" % (k, v / 2**20) for k, v in top[:6]), ",".join(list(skip) + pick)))
        if dry:
            rep.add("budget", "WARN", time.time() - t, "DB TOO BIG: " + detail)
            rep.notes.append("budget: this tree does not fit in coop.addon (%s). A REAL release run stops here; this dry run went on packaging so the "
                             "zip and README could be checked. To get a releasable build: %s" % (detail, hint))
            return True
        rep.add("budget", "FAIL", time.time() - t, "DB TOO BIG: " + detail + ". " + hint)
        return False
    rep.add("budget", "PASS", time.time() - t, detail)
    return True


# ---------------------------------------------------------------------------------------------------------- 4 boot checks
def engine_count():
    rc, out = run(["tasklist", "/FI", "IMAGENAME eq xrEngine.exe", "/FO", "CSV", "/NH"])
    return sum(1 for l in out.splitlines() if l.lower().startswith('"xrengine.exe"'))


def free_gb(path):
    return shutil.disk_usage(path).free / 2**30


def free_ram_gb():
    """Free physical RAM in GB (ctypes, no extra packages); None when it cannot be read."""
    try:
        import ctypes

        class MS(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong), ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]
        m = MS()
        m.dwLength = ctypes.sizeof(MS)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return m.ullAvailPhys / 2**30
    except Exception:  # noqa: BLE001
        return None


_launch_lock = threading.Lock()
MIN_FREE_RAM_GB = 1.5   # below this the dedicated server dies with "Not enough memory resources" (seen at 0.5 GB free); --min-free-ram-gb overrides


def wait_to_launch(min_free_gb, log, max_engines=6, max_wait=3600):
    """The two hard rules before every game launch: at most 6 running xrEngine.exe, and at least min_free_gb free disk."""
    t0 = time.time()
    with _launch_lock:
        while True:
            n, fr = engine_count(), free_gb(GAME_DIR if os.path.isdir(GAME_DIR) else REPO)
            ram = free_ram_gb()
            if n <= max_engines and fr >= min_free_gb and (ram is None or ram >= MIN_FREE_RAM_GB):
                return True
            if time.time() - t0 > max_wait:
                log("gave up waiting: %d xrEngine.exe running, %.1f GB free" % (n, fr))
                return False
            if int(time.time() - t0) % 60 < 15:
                log("waiting to launch: %d xrEngine.exe running (max %d), %.1f GB disk free (min %.0f), %s GB RAM free (min %.0f)" % (n, max_engines, fr, min_free_gb, "?" if ram is None else "%.1f" % ram, MIN_FREE_RAM_GB))
            time.sleep(15)


RELEASE_DB = None   # the finished (compressed) release db: boot checks append IT to the lane addon (run_coop -DbFile), exactly what install.ps1 ships


def boot_command(level, stage, owner, result_dir, soak):
    # -DbFile = the real compressed db as a tar member (what players get). The raw stage as -ExtraDir would be ~84 MB raw and cannot even boot (4 GiB).
    src = ["-DbFile", RELEASE_DB] if RELEASE_DB else ["-ExtraDir", os.path.join(stage, "gamedata")]
    ps = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", RUN_COOP, "-Map", "coop_l01_escape" if level in ROUTE_LEVELS else level,
          "-Owner", owner, "-Clients", "1"] + src + ["-CompareTimeout", "10", "-ResultDir", result_dir,
          "-SlotWait", "1800", "-BusyWait", "900"]
    if level in ROUTE_LEVELS:
        ps += ["-Mode", "listen", "-SoakSeconds", str(max(soak, ROUTE_SOAK)), "-Cfg", "no_respawn=1",
               "-Hooks", os.path.join(HERE, "release_boot_travel.lua")]
    else:
        # one listen game (1 engine) instead of dedicated + client (2 engines): each xrEngine maps the 4 GB addon and counts against the
        # Windows commit limit, and a level that boots as a listen host boots the same data as a dedicated server
        ps += ["-Mode", "listen", "-SoakSeconds", str(soak)]
    return ps


def judge_boot(level, rc, out):
    """OK = spawned, no crash, no failed assert (and for the route levels: arrived + alife online).  The compare verdict is informational:
    the harness reports 'A sees player id ... that no client reports' noise after respawns, which is not a boot problem."""
    lines = out.splitlines()
    failure = [l for l in lines if "FAILURE:" in l]
    spawned = [l for l in lines if re.search(r"all \d+ clients spawned", l)]
    assert_fail = [l for l in lines if re.search(r"assert \w: FAIL ", l)]
    result = next((l for l in lines if "RESULT:" in l), "")
    if rc == 2:
        return "BUSY", "owner's own game is running"
    if rc == 3:
        return "FAIL", "setup error: " + " ".join(l for l in lines if "SETUP ERROR" in l or "BUILD FAILED" in l)[:200]
    if failure:
        return "FAIL", failure[-1].split("]", 1)[-1].strip()[:200]
    if not spawned:
        return "FAIL", "no client spawned: " + (result.split("]", 1)[-1].strip() or "no RESULT line")[:160]
    if assert_fail:
        return "FAIL", assert_fail[0].split("]", 1)[-1].strip()[:200]
    if level in ROUTE_LEVELS:
        want = "RB route arrived on " + level
        if not any(want in l and "PASS" in l for l in lines):
            return "FAIL", "route check line missing: " + want
    m = re.search(r"all \d+ clients spawned after (\d+) s", spawned[0])
    return "PASS", ("spawned after %s s" % m.group(1)) + ("" if "RESULT: PASS" in result else " (compare: informational mismatch)")


def infra_failure(rdir):
    """True when the run's engine logs show a machine problem (out of memory / cannot map the addon / GPU device removed under load) and not a
    content problem.  Such a boot is retried once."""
    for dp, _, fs in os.walk(rdir):
        for f in fs:
            if f.lower().startswith("xray_") and f.lower().endswith(".log"):
                try:
                    txt = open(os.path.join(dp, f), "rb").read().decode("cp1251", "replace")
                except OSError:
                    continue
                low = txt.lower()
                if ("Not enough memory resources" in txt or "Cannot map addon file" in txt or "not enough storage" in low
                        or "Arguments     : Out of memory. Memory request" in txt
                        or "gpu device instance has been suspended" in low or "device removed" in low or "dxgi_error_device" in low):
                    return True
    return False


def boot_one(level, idx, stage, out_dir, owner, soak, min_free, dry, rep_lock, log):
    rdir = os.path.join(out_dir, "boot", level)
    shutil.rmtree(rdir, ignore_errors=True)
    os.makedirs(rdir, exist_ok=True)
    cmd = boot_command(level, stage, "%sw%d" % (owner, idx), rdir, soak)
    if dry:
        return level, "PLANNED", 0.0, " ".join('"%s"' % c if " " in c else c for c in cmd)
    t = time.time()
    for attempt in range(3):
        set_status(rdir, "waiting for the launch rules (at most 6 xrEngine.exe, 10 GB disk, RAM); attempt %d" % (attempt + 1))
        if not wait_to_launch(min_free, lambda m: log("%s: %s" % (level, m))):
            set_status(rdir, "gave up waiting for the launch rules")
            return level, "FAIL", time.time() - t, "could not launch: engine count / disk rule"
        time.sleep(1)
        set_status(rdir, "run_coop.ps1 started (queued for a slot lease until run.log appears; live output: release_stdout.log)")
        try:
            rc, out = run_logged(cmd, os.path.join(rdir, "release_stdout.log"), 3600)
        except subprocess.TimeoutExpired:
            set_status(rdir, "TIMED OUT after 3600 s")
            return level, "FAIL", time.time() - t, "run_coop.ps1 timed out after 3600 s"
        status, detail = judge_boot(level, rc, out)
        set_status(rdir, "finished: %s %s" % (status, detail))
        if status == "FAIL" and attempt < 1 and infra_failure(rdir):
            log("%s: the game died for lack of memory (not a content failure), waiting and retrying (%d/1)" % (level, attempt + 1))
            time.sleep(90)
            continue
        if status != "BUSY":
            break
        log("%s: BUSY (owner's own game), retry in 60 s" % level)
        time.sleep(60)
    return level, status, time.time() - t, detail


def step_boot(levels, stage, out_dir, owner, soak, min_free, parallel, dry, rep):
    t0 = time.time()
    results = []
    log = lambda m: print("  boot  " + m, flush=True)
    with ThreadPoolExecutor(max_workers=max(1, parallel)) as ex:
        futs = []
        for i, lv in enumerate(levels):
            futs.append(ex.submit(boot_one, lv, i, stage, out_dir, owner, soak, min_free, dry, None, log))
            if not dry:
                time.sleep(2)
        for fu in futs:
            lv, status, secs, detail = fu.result()
            results.append((lv, status, secs, detail))
            rep.add("boot", status if status != "PLANNED" else "PLAN", secs, "%-30s %s" % (lv, detail), quiet=(status == "PLANNED"))
    bad = [r for r in results if r[1] == "FAIL"]
    return not bad, results


# ---------------------------------------------------------------------------------------------------------- 5 package
def read_text(path):
    with open(path, "rb") as f:
        return f.read().decode("utf-8-sig")


def patch_names(skip):
    pdir = os.path.join(REPO, "patches")
    return ["- " + p for p in sorted(os.listdir(pdir)) if p not in skip and os.path.isdir(os.path.join(pdir, p, "gamedata"))]


def filter_changes(text, skip):
    """A change line may start with an owner tag: '- @marked_one,cordon: text'.  The tag is removed; the line is dropped when EVERY patch named in
    it is in --skip (so a README never promises a fix that is not in the db).  A group heading left without lines is dropped too."""
    out = []
    for ln in text.split("\n"):
        m = re.match(r"^- @([a-z0-9_,]+): (.*)$", ln)
        if m:
            owners = m.group(1).split(",")
            if all(o in skip for o in owners):
                continue
            ln = "- " + m.group(2)
        out.append(ln)
    res, i = [], 0
    while i < len(out):          # drop headings (a non-empty line without '- ') that now have no bullet before the next blank line
        ln = out[i]
        if ln and not ln.startswith("- ") and i + 1 < len(out) and i > 0 and out[i - 1] == "":
            j = i + 1
            if j >= len(out) or out[j] == "":
                i += 2
                continue
        res.append(ln)
        i += 1
    return "\n".join(res)


def written_changes(version):
    """(en, ru) from installer\\changes_<version>.en.txt / .ru.txt, or None.  Those are the player-facing change lists written by the release
    owner (same style as the v1.3 README: 'New in v1.3', grouped, one plain-language line per change)."""
    en_f = os.path.join(REPO, "installer", "changes_%s.en.txt" % version)
    ru_f = os.path.join(REPO, "installer", "changes_%s.ru.txt" % version)
    if os.path.exists(en_f) and os.path.exists(ru_f):
        return read_text(en_f).strip(), read_text(ru_f).strip()
    return None



def make_readme(version, skip):
    tpl = read_text(os.path.join(REPO, "installer", "README.template.txt"))
    date = datetime.date.today().strftime("%d.%m.%Y")
    wc = written_changes(version)
    if wc:
        en, ru = filter_changes(wc[0], skip), filter_changes(wc[1], skip)
        how = "changes_%s.en/ru.txt" % version
    else:
        # stop-gap only: the release report carries a WARN row, the owner should write installer\\changes_<version>.en.txt and .ru.txt
        names = "\n".join(patch_names(skip))
        en = "Included in v%s\n\nFixes (internal patch names):\n%s" % (version, names)
        ru = "Входит в v%s\n\nИсправления (внутренние названия):\n%s" % (version, names)
        how = "AUTO list of patch folder names (write installer\\changes_%s.en.txt and .ru.txt)" % version
    text = tpl.replace("{VERSION}", version).replace("{DATE}", date).replace("{CHANGES_EN}", en).replace("{CHANGES_RU}", ru)
    for bad in ("\u2014", "\u2013"):
        if bad in text:
            raise SystemExit("README contains a dash character that is not allowed (em/en dash)")
    return text.replace("\r\n", "\n").replace("\n", "\r\n"), how


INSTALL_BAT = ("@echo off\r\n"
               "rem Installs zzz_soc_coop_fixes.db (next to the installer folder) into coop.addon, the same way on every PC (see install.ps1).\r\n"
               "powershell -NoProfile -ExecutionPolicy Bypass -File \"%~dp0install.ps1\" -Db \"%~dp0..\\zzz_soc_coop_fixes.db\" %*\r\n"
               "pause\r\n")


def step_package(version, db, skip, out_dir, rep, dry, player_limit=None):
    t = time.time()
    extra = []
    if player_limit == 8:
        try:
            sys.path.insert(0, HERE)
            from start_coop_server import load_profile, _file_sha256
            from pathlib import Path
            profile = Path(db).with_name("coop_player_limit_profile.json")
            parsed = load_profile(profile)
            if parsed["patch_db"]["size"] != os.path.getsize(db) or parsed["patch_db"]["sha256"] != _file_sha256(Path(db)):
                raise ValueError("built DB size/SHA256 does not match capacity profile")
        except (OSError, ValueError) as error:
            rep.add("package", "FAIL", time.time() - t, str(error))
            return None
        extra = [
            (str(profile), "coop_player_limit_profile.json"),
            (os.path.join(REPO, "installer", "player_limit.ps1"), "installer/player_limit.ps1"),
            (os.path.join(REPO, "installer", "start_server_1_8.ps1"), "installer/start_server_1_8.ps1"),
            (os.path.join(REPO, "installer", "start_server_1_8.bat"), "Start-Server-1-8.bat"),
            (os.path.join(HERE, "start_coop_server.py"), "tools/start_coop_server.py"),
            (os.path.join(HERE, "patch_coop_player_limit.py"), "tools/patch_coop_player_limit.py"),
            (os.path.join(REPO, "docs", "PLAYER_LIMIT_8.en.md"), "PLAYER_LIMIT_8.en.md"),
            (os.path.join(REPO, "docs", "PLAYER_LIMIT_8.ru.md"), "PLAYER_LIMIT_8.ru.md"),
        ]
    name = "SoC_COOP_fixes_v" + version + ("_players8" if player_limit == 8 else "")
    folder = os.path.join(out_dir, name)
    shutil.rmtree(folder, ignore_errors=True)
    os.makedirs(os.path.join(folder, "installer"))
    readme, how = make_readme(version, skip)
    if player_limit == 8:
        readme = ("OPT-IN capacity 8 / ОПЦИОНАЛЬНЫЙ РЕЖИМ 8\n"
                  "Read PLAYER_LIMIT_8.en.md / PLAYER_LIMIT_8.ru.md before installing.\n"
                  "Exact addon 8.1 x86 DLL only; all players need this same package.\n"
                  "Install patches local DLLs and keeps verified originals; no DLL is shipped.\n"
                  "Host: Start-Server-1-8.bat (PowerShell) or tools/start_coop_server.py (Python 3.10+).\n\n" + readme)
    with open(os.path.join(folder, "README.txt"), "wb") as f:
        f.write(b"\xef\xbb\xbf" + readme.encode("utf-8")) if False else f.write(readme.encode("utf-8"))
    shutil.copyfile(db, os.path.join(folder, "zzz_soc_coop_fixes.db"))
    shutil.copyfile(os.path.join(REPO, "installer", "install.ps1"), os.path.join(folder, "installer", "install.ps1"))
    with open(os.path.join(folder, "installer", "install.bat"), "wb") as f:
        f.write(INSTALL_BAT.encode("ascii"))
    inventory = ["README.txt", "zzz_soc_coop_fixes.db", "installer/install.bat", "installer/install.ps1"]
    for source, relative in extra:
        destination = os.path.join(folder, *relative.split("/"))
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        shutil.copyfile(source, destination)
        inventory.append(relative)
    zpath = os.path.join(out_dir, name + ".zip")
    if os.path.exists(zpath):
        os.remove(zpath)
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for rel in inventory:
            z.write(os.path.join(folder, rel), rel.replace(os.sep, "/"))
    with zipfile.ZipFile(zpath) as z:
        bad = z.testzip()
        names = sorted(z.namelist())
    if bad or names != sorted(inventory):
        rep.add("package", "FAIL", time.time() - t, "zip check failed: %s %s" % (bad, names))
        return None
    rep.add("package", "PASS", time.time() - t, "%s (%.1f MB), README change list: %s" % (os.path.basename(zpath), os.path.getsize(zpath) / 2**20, how))
    if how.startswith("AUTO"):
        rep.add("readme", "WARN", 0, "README change list is only the patch folder names: " + how)
        rep.notes.append("readme: no written change list for v%s. Write installer\\changes_%s.en.txt and .ru.txt (see changes_1.4.*.txt for the style), "
                         "then re-run; do not publish this README." % (version, version))
    return folder, zpath


# ---------------------------------------------------------------------------------------------------------- 6 installer self-test
def tar_header(name, size):
    h = bytearray(512)
    h[0:len(name)] = name.encode("ascii")
    h[100:108] = b"0000644\0"
    h[108:116] = b"0000000\0"
    h[116:124] = b"0000000\0"
    h[124:136] = ("%011o" % size).encode("ascii") + b"\0"
    h[136:148] = b"00000000000\0"
    h[156:157] = b"0"
    h[148:156] = b" " * 8
    h[148:156] = ("%06o" % sum(h)).encode("ascii") + b"\0 "
    return bytes(h)


def synthetic_addon(path):
    with open(path, "wb") as f:
        for n in ("gamedata.db0", "gamedata.db1", "icon.webp", "metadata.json"):
            data = (n * 50).encode("ascii")
            f.write(tar_header(n, len(data)) + data + b"\0" * ((512 - len(data) % 512) % 512))
        f.write(b"\0" * 10240)


def sparse_addon(path, big):
    """Synthetic addon whose gamedata.db1 claims `big` bytes: a sparse file (no real disk use), so the 4 GiB check can be tested."""
    open(path, "wb").close()
    subprocess.run(["fsutil", "sparse", "setflag", path], capture_output=True)
    with open(path, "r+b") as f:
        for n in ("gamedata.db0", "gamedata.db1", "icon.webp", "metadata.json"):
            size = big if n == "gamedata.db1" else 1000
            f.write(tar_header(n, size))
            if n == "gamedata.db1":
                f.seek(((size + 511) // 512) * 512, 1)
            else:
                f.write(b"x" * 1000 + b"\0" * 24)
        f.write(b"\0" * 10240)


def installer_limit_test(folder):
    """install.ps1 must refuse (rc != 0, 'NOT INSTALLED', addon byte-identical) when the result passes 4 GiB, and install just below it.
    Returns (ok, detail)."""
    tmp = tempfile.mkdtemp(prefix="relinst4g_")
    try:
        ps1 = os.path.join(folder, "installer", "install.ps1")
        db = os.path.join(folder, "zzz_soc_coop_fixes.db")
        dbs = os.path.getsize(db)
        out = {}
        for label, big in (("over", 2**32 - 2 * 2**20), ("under", 2**32 - dbs - 3 * 2**20)):
            addon = os.path.join(tmp, label + ".addon")
            sparse_addon(addon, big)
            before = os.path.getsize(addon)
            h0 = hashlib.sha256()
            with open(addon, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 24), b""):
                    h0.update(chunk)
            rc, o = run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps1, "-Addon", addon, "-Db", db], timeout=600)
            after = os.path.getsize(addon)
            out[label] = (rc, o, before, after, h0.hexdigest())
            if label == "over":
                h1 = hashlib.sha256()
                with open(addon, "rb") as f:
                    for chunk in iter(lambda: f.read(1 << 24), b""):
                        h1.update(chunk)
                out[label] += (h1.hexdigest(),)
            os.remove(addon)
        rc, o, before, after, h0, h1 = out["over"]
        over_ok = rc != 0 and "NOT INSTALLED" in o and "НЕ УСТАНОВЛЕНО" in o and before == after and h0 == h1
        rc2, o2, b2, a2, _ = out["under"]
        under_ok = rc2 == 0 and a2 <= 2**32 and "Installed" in o2
        return over_ok and under_ok, "4 GiB guard: over-limit refused rc=%d unchanged=%s, just-under installs rc=%d final %d bytes" % (rc, h0 == h1, rc2, a2)
    except Exception as e:  # noqa: BLE001
        return False, "4 GiB guard test error %r" % (e,)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def step_installer(folder, rep, player_limit=None):
    t = time.time()
    if player_limit == 8:
        env = os.environ.copy()
        ps = env.get("COOP_PWSH") or shutil.which("powershell") or shutil.which("pwsh")
        dll = env.get("COOP_TEST_DLL")
        if not dll:
            for relative in ("bin/xrGame.dll.cap8-original", "bin/xrGame.dll"):
                candidate = os.path.join(GAME_DIR, relative)
                if os.path.isfile(candidate):
                    dll = candidate
                    break
        if not ps or not dll or not os.path.isfile(dll):
            rep.add("installer", "FAIL", time.time() - t, "capacity 8 self-test requires PowerShell (COOP_PWSH) and original supported COOP_TEST_DLL; no game is executed")
            return False
        env.update(COOP_PWSH=ps, COOP_TEST_DLL=dll, COOP_INSTALLER_ROOT=folder)
        rc, output = py("-m", "unittest", "discover", "-s", os.path.join(REPO, "tests"), "-p", "test_coop_player_installer.py", "-v", env=env, timeout=600)
        # Required runtime/DLL prerequisites were checked above. Directory
        # symlink creation can legitimately be unavailable to a Windows user.
        ok = rc == 0
        rep.add("installer", "PASS" if ok else "FAIL", time.time() - t, "capacity 8 synthetic addon + official local DLL, backups/idempotence/refusal/rollback; " + output[-1000:])
        return ok
    import tarfile
    tmp = tempfile.mkdtemp(prefix="relinst_")
    try:
        addon = os.path.join(tmp, "coop.addon")
        synthetic_addon(addon)
        size_base = os.path.getsize(addon)
        ps1 = os.path.join(folder, "installer", "install.ps1")
        db = os.path.join(folder, "zzz_soc_coop_fixes.db")
        base = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps1, "-Addon", addon]
        rc1, o1 = run(base + ["-Db", db], timeout=300)
        sha1 = hashlib.sha256(open(addon, "rb").read()).hexdigest()
        with tarfile.open(addon) as tf:
            m = {x.name: x for x in tf.getmembers()}.get("zzz_soc_coop_fixes.db")
            member_ok = m is not None and m.size == os.path.getsize(db) and m.mtime == 0 and m.uid == 0
        rc2, o2 = run(base + ["-Db", db], timeout=300)     # install over the installed entry: same bytes, so the same fingerprint on every PC
        sha2 = hashlib.sha256(open(addon, "rb").read()).hexdigest()
        rc3, o3 = run(base + ["-Uninstall"], timeout=300)
        with tarfile.open(addon) as tf:
            gone = "zzz_soc_coop_fixes.db" not in tf.getnames()
            kept = sum(1 for n in tf.getnames() if n in ("gamedata.db0", "gamedata.db1", "icon.webp", "metadata.json"))
        ok = rc1 == 0 and rc2 == 0 and rc3 == 0 and member_ok and sha1 == sha2 and gone and kept == 4
        lim_ok, lim_detail = installer_limit_test(folder)
        ok = ok and lim_ok
        rep.add("installer", "PASS" if ok else "FAIL", time.time() - t,
                "synthetic addon (%d bytes): install rc=%d, tar member size/mtime/uid ok=%s, reinstall same sha=%s, uninstall rc=%d removed=%s, base entries kept=%d/4; %s"
                % (size_base, rc1, member_ok, sha1 == sha2, rc3, gone, kept, lim_detail))
        if not ok:
            print((o1 + o2 + o3)[-600:])
        return ok
    except Exception as e:  # noqa: BLE001
        rep.add("installer", "FAIL", time.time() - t, repr(e))
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("version", help="for example 1.4")
    ap.add_argument("--skip", default=None, help="patch folders to leave out (default: %s); 'none' = skip nothing" % ",".join(DEFAULT_SKIP))
    ap.add_argument("--levels", default="all", help="all | comma list (coop_l01_escape,...)")
    ap.add_argument("--out", default=None, help="output folder (default: build\\release_v<version> in the repo)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--owner", default="rel", help="slot owner prefix for the boot checks (default rel)")
    ap.add_argument("--parallel", type=int, default=2, help="boot checks in parallel (default 2)")
    ap.add_argument("--soak", type=int, default=10)
    ap.add_argument("--min-free-gb", type=float, default=10.0)
    ap.add_argument("--min-free-ram-gb", type=float, default=MIN_FREE_RAM_GB, help="wait before each launch until this much RAM is free (default %.1f)" % MIN_FREE_RAM_GB)
    ap.add_argument("--no-boot", action="store_true", help="skip step 4 entirely")
    ap.add_argument("--no-installer-test", action="store_true")
    ap.add_argument("--player-limit", type=int, choices=[8], help="opt-in capacity 8 package; standard release is unchanged")
    a = ap.parse_args()
    globals()["MIN_FREE_RAM_GB"] = a.min_free_ram_gb

    if not re.fullmatch(r"\d+(\.\d+){1,2}[A-Za-z0-9_-]*", a.version):
        print("version looks wrong: %r (expected like 1.4)" % a.version)
        return 2
    skip = DEFAULT_SKIP if a.skip is None else ([] if a.skip.strip().lower() in ("none", "") else [s.strip() for s in a.skip.split(",") if s.strip()])
    pdir = os.path.join(REPO, "patches")
    # Historical defaults can outlive a retired patch folder (soc_levels).
    # Explicit user input still gets typo validation; absent defaults skip nothing.
    unknown = [s for s in skip if not os.path.isdir(os.path.join(pdir, s))] if a.skip is not None else []
    if unknown:
        print("unknown patch folder(s) in --skip: %s" % ", ".join(unknown))
        return 2
    if a.levels.strip().lower() == "all":
        levels = list(ALL_LEVELS)
    else:
        levels = [l.strip() for l in a.levels.split(",") if l.strip()]
        bad = [l for l in levels if l not in ALL_LEVELS]
        if bad:
            print("unknown level(s): %s (known: %s)" % (", ".join(bad), ", ".join(ALL_LEVELS)))
            return 2
    out_dir = os.path.abspath(a.out or os.path.join(REPO, "build", "release_v" + a.version + ("_players8" if a.player_limit == 8 else "")))
    os.makedirs(out_dir, exist_ok=True)
    if free_gb(out_dir) < 1:
        print("less than 1 GB free in %s: stopping" % out_dir)
        return 2
    mode = "DRY-RUN" if a.dry_run else "REAL"
    print("release v%s (%s) -> %s\nskip: %s\nlevels: %d%s\n" % (a.version, mode, out_dir, ",".join(skip) or "none", len(levels),
                                                             "" if not (a.no_boot or a.dry_run) else (" (boot: " + ("plan only" if a.dry_run else "skipped") + ")")), flush=True)
    rep = Report()
    ok = step_conflicts(skip, rep)
    ok = step_escapes(skip, rep) and ok
    if not ok:
        rep.add("stop", "FAIL", 0, "offline checks failed; not building a release from this tree")
        finish(rep, a, out_dir, mode, skip, levels, None)
        return 1
    built = step_build(skip, out_dir, rep, a.dry_run, a.version, player_limit=a.player_limit)
    if built is None:
        finish(rep, a, out_dir, mode, skip, levels, None)
        return 1
    stage, db = built
    global RELEASE_DB
    RELEASE_DB = db
    boot_ok = True
    boot_results = []
    if a.no_boot:
        rep.add("boot", "SKIP", 0, "--no-boot")
    else:
        if not a.dry_run and free_gb(GAME_DIR if os.path.isdir(GAME_DIR) else out_dir) < a.min_free_gb:
            print("note: less than %.0f GB free; each launch will wait for space (rule: keep %.0f GB free)" % (a.min_free_gb, a.min_free_gb), flush=True)
        boot_ok, boot_results = step_boot(levels, stage, out_dir, a.owner, a.soak, a.min_free_gb, a.parallel, a.dry_run, rep)
    pk = step_package(a.version, db, skip, out_dir, rep, a.dry_run, player_limit=a.player_limit)
    inst_ok = True
    if pk is not None and not a.no_installer_test:
        inst_ok = step_installer(pk[0], rep, player_limit=a.player_limit)
    elif pk is None:
        inst_ok = False
    finish(rep, a, out_dir, mode, skip, levels, pk)
    return 0 if (boot_ok and pk is not None and inst_ok) else 1


def finish(rep, a, out_dir, mode, skip, levels, pk):
    total = time.time() - rep.t0
    lines = ["Release v%s (%s), %s, total %.0f s" % (a.version, mode, datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), total),
             "skipped patches: " + (",".join(skip) or "none"), "levels: %d" % len(levels), ""]
    lines.append("%-10s %-7s %8s  %s" % ("step", "status", "seconds", "detail"))
    for r in rep.rows:
        d = r["detail"]
        if r["step"] == "boot" and r["status"] == "PLAN":
            d = d.split(" powershell ")[0] + "  (command not run in a dry run; see below)"
        lines.append("%-10s %-7s %8.1f  %s" % (r["step"], r["status"], r["seconds"], d))
    failed = rep.failed()
    warned = rep.warned()
    verdict = "FAILED (%d step(s))" % len(failed) if failed else ("OK (dry-run: no game was started, not boot-checked)" if mode == "DRY-RUN" else "OK")
    if warned and not failed:
        verdict += " with %d WARNING(S), see the notes below" % len(warned)
    plans = [r for r in rep.rows if r["step"] == "boot" and r["status"] == "PLAN"]
    if plans:
        lines += ["", "Boot commands that a real run executes (one per level):"] + ["  " + r["detail"] for r in plans[:1]] + ["  ... same for the other %d level(s), -Map / -Owner / -ResultDir differ" % (len(plans) - 1)]
    if rep.notes:
        lines += [""] + ["NOTE: " + n for n in rep.notes]
    lines += ["", "RELEASE %s" % verdict]
    if pk:
        lines.append("folder: " + pk[0])
        lines.append("zip:    " + pk[1])
    text = "\n".join(lines)
    print("\n" + text)
    with open(os.path.join(out_dir, "release_report.txt"), "w", encoding="utf-8") as f:
        f.write(text + "\n")
    with open(os.path.join(out_dir, "release_report.json"), "w", encoding="utf-8") as f:
        json.dump({"version": a.version, "mode": mode, "skip": skip, "levels": levels, "rows": rep.rows, "verdict": verdict}, f, indent=1)


if __name__ == "__main__":
    sys.exit(main())
