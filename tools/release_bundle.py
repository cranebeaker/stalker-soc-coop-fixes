"""Build the v1.5 release: the fix patch and the cut-scene movies inside coop.addon (needs the patched xrCore.dll) and a stand-alone 4 GiB patch.

  python tools\\release_bundle.py <version> --xrcore-orig <original xrCore.dll of xrMPE 0.9> [--db zzz_soc_coop_fixes.db] [--cutscenes cutscene_pack\\out] [--out build\\bundle_v<version>]

Writes <out>\\SoC_COOP_fixes_v<version>.zip      installer + zzz_soc_coop_fixes.db + cutscenes\\ (movies and both sound languages) + xrcore_4gb\\
       <out>\\SoC_COOP_4GB_patch.zip              only install_xrcore_patch.bat/.ps1 + README (nothing of xrMPE's file is inside, only the byte changes)
Needs python 3 with capstone, keystone-engine, pefile (see tools\\xrcore_4gb\\README.md).  Nothing is published.
"""
import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
TOOL = os.path.join(HERE, "xrcore_4gb")


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest().upper()


def read_changes(version_changes, lang):
    p = os.path.join(REPO, "installer", "changes_%s.%s.txt" % (version_changes, lang))
    t = open(p, encoding="utf-8-sig").read().replace("\r\n", "\n").strip().split("\n")
    return [re.sub(r"^- @[\w,]+: ", "- ", l) for l in t[1:] if l.strip()]


README_EN = """Shadow of COOP: unofficial fix patch v{ver}
==========================================

What is new in {ver}
- The original cut-scene movies are inside coop.addon now. Before, every player had to install a separate movie pack and players without it saw a
  short fallback; now everybody sees the same movies.
- For that the add-on is larger than 4 GiB, which the 32-bit game engine could not load. This release carries a fix for one engine file
  (game\\bin\\xrCore.dll), made with the OK of the xrMPE team. install.bat applies it for you (a copy of the original is kept as xrCore.dll.orig).
  The same fix is also published on its own as SoC_COOP_4GB_patch.zip for anyone who just wants bigger add-ons.
- The movie SOUND stays a personal choice (Russian or English): install.bat copies the sound file of your language into game\\patches.
  It does not change the add-on, so players may differ. The language is taken from voice_language of your coop_settings.ltx ([client] section:
  auto, rus or eng), else from the launcher language. To force one: install.bat -Voice rus  or  install.bat -Voice eng.
- Everything of v1.4.3 is in (the list is below).

Install (every player, the host and a dedicated server PC, all the same way)
1. Close the game, the dedicated server and the xrMPE launcher.
2. Unzip this archive anywhere.
3. Double-click installer\\install.bat. It finds the X-Ray Multiplayer Extension folder (or asks for the path), patches xrCore.dll when needed,
   writes the fixes and the movies into coop.addon and copies your movie sound language.
4. The last line shows the add-on fingerprint. It must be the same for every player, otherwise the server says "Different Versions".
   (Same options for everybody: do not mix -NoCutscenes with the default install.)
An older fix patch (1.4.x) is replaced by running install.bat again. The Full HD movies are optional and per player, see below.

Options of install.bat: -Addon "D:\\...\\coop.addon", -Voice auto|rus|eng|none, -NoCutscenes (fixes only, as before 1.5, add-on stays below 4 GiB),
-NoEnginePatch (never touch xrCore.dll; refuses when the add-on would pass 4 GiB), -Uninstall.
Uninstall: installer\\install.bat -Uninstall removes the fixes and the movies. The engine patch is separate: xrcore_4gb\\install_xrcore_patch.bat -Uninstall.

Full HD movies (optional, 1.4 GB, per player): the pack from the v1.4.3 release (SoC_COOP_cutscene_pack.zip, movies by neatodev, Nexus mod 1098) still works
next to this version. Run its install_cutscenes.bat; it needs no engine patch because the files stay in game\\patches.

If something goes wrong
- The game closes right after the start: this PC has no patched xrCore.dll. Run xrcore_4gb\\install_xrcore_patch.bat (or install.bat again).
- A launcher update can put the original xrCore.dll back: run xrcore_4gb\\install_xrcore_patch.bat -Check, and the patch again if needed.
- "Different Versions": compare the fingerprints, everybody must run the same install.bat with the same options.
- Limits of the engine fix: one database inside the add-on must be smaller than 2 GiB. Details: xrcore_4gb\\README.txt.

Credits: the movies and sounds are from S.T.A.L.K.E.R.: Shadow of Chernobyl by GSC Game World. The 4 GiB fix was made with the permission of the xrMPE team.

Changes (the same as in 1.4.3)
{changes_en}
"""

README_RU = """Shadow of COOP: неофициальный патч исправлений v{ver}
===================================================

Что нового в {ver}
- Оригинальные ролики кат-сцен теперь лежат внутри coop.addon. Раньше каждому игроку нужно было ставить отдельный пакет роликов, а у кого его не было,
  показывалась короткая заставка; теперь все видят одни и те же ролики.
- Из-за этого аддон больше 4 ГиБ, а 32-битный движок игры такое загрузить не мог. В релизе есть исправление одного файла движка
  (game\\bin\\xrCore.dll), сделанное с разрешения команды xrMPE. install.bat ставит его сам (копия оригинала сохраняется как xrCore.dll.orig).
  Это же исправление выложено отдельно как SoC_COOP_4GB_patch.zip для тех, кому нужны просто большие аддоны.
- ЗВУК роликов остаётся личным выбором (русский или английский): install.bat копирует файл звука вашего языка в game\\patches. На аддон это не влияет,
  поэтому у игроков он может отличаться. Язык берётся из voice_language в вашем coop_settings.ltx (раздел [client]: auto, rus или eng),
  иначе из языка лаунчера. Выбрать вручную: install.bat -Voice rus  или  install.bat -Voice eng.
- Всё из v1.4.3 включено (список ниже).

Установка (каждому игроку, хосту и ПК с выделенным сервером, одинаково)
1. Закройте игру, выделенный сервер и лаунчер xrMPE.
2. Распакуйте архив в любую папку.
3. Запустите installer\\install.bat двойным щелчком. Он найдёт папку X-Ray Multiplayer Extension (или спросит путь), при необходимости пропатчит xrCore.dll,
   запишет исправления и ролики в coop.addon и скопирует звук ваших роликов.
4. В последней строке будет отпечаток аддона. Он должен совпадать у всех игроков, иначе сервер скажет "Different Versions".
   (У всех одинаковые параметры: не смешивайте -NoCutscenes и обычную установку.)
Старый патч исправлений (1.4.x) заменяется повторным запуском install.bat. Ролики Full HD по желанию и у каждого свои, см. ниже.

Параметры install.bat: -Addon "D:\\...\\coop.addon", -Voice auto|rus|eng|none, -NoCutscenes (только исправления, как до 1.5, аддон остаётся меньше 4 ГиБ),
-NoEnginePatch (не трогать xrCore.dll; откажется, если аддон станет больше 4 ГиБ), -Uninstall.
Удаление: installer\\install.bat -Uninstall убирает исправления и ролики. Патч движка отдельно: xrcore_4gb\\install_xrcore_patch.bat -Uninstall.

Ролики Full HD (по желанию, 1,4 ГБ, у каждого свои): пакет из релиза v1.4.3 (SoC_COOP_cutscene_pack.zip, ролики neatodev, Nexus мод 1098) работает вместе с этой версией.
Запустите его install_cutscenes.bat; патч движка ему не нужен, файлы остаются в game\\patches.

Если что-то не так
- Игра закрывается сразу после запуска: на этом ПК нет пропатченного xrCore.dll. Запустите xrcore_4gb\\install_xrcore_patch.bat (или снова install.bat).
- Обновление лаунчера может вернуть оригинальный xrCore.dll: xrcore_4gb\\install_xrcore_patch.bat -Check, при необходимости патч снова.
- "Different Versions": сравните отпечатки, у всех должен быть один и тот же install.bat с теми же параметрами.
- Ограничение исправления движка: одна база внутри аддона должна быть меньше 2 ГиБ. Подробности: xrcore_4gb\\README.txt.

Авторы: ролики и звуки из S.T.A.L.K.E.R.: Тень Чернобыля (GSC Game World). Исправление для 4 ГиБ сделано с разрешения команды xrMPE.

Изменения (те же, что в 1.4.3)
{changes_ru}
"""

PATCH_README = """xrMPE: add-ons larger than 4 GiB (xrCore.dll patch)
===================================================

The game engine of xrMPE is 32-bit and could not load a .addon file larger than 4 GiB (it crashed at start). This patch fixes the engine file
game\\bin\\xrCore.dll so that it can. It was made with the OK of the xrMPE team. It changes nothing else.

1. Close the game, the dedicated server (black window) and the xrMPE launcher.
2. Double-click install_xrcore_patch.bat. It finds X-Ray Multiplayer Extension (or asks for the path).
It checks that your xrCore.dll is the xrMPE 0.9 file (SHA-256), keeps a copy as xrCore.dll.orig, applies the changes and checks the result.
install_xrcore_patch.bat -Check shows the state, install_xrcore_patch.bat -Uninstall restores the original.

Everybody who plays or hosts with such an add-on needs it (host, clients, dedicated server); an unpatched engine closes at start.
A launcher update can restore the original xrCore.dll: run the patch again.
The zip contains only the byte changes, not xrMPE's file. Limits: one database inside the add-on must be smaller than 2 GiB; plain files stored
directly in the add-on above 4 GiB are not supported; add-ons below 4 GiB work exactly as before.
Technical description: https://github.com/cranebeaker/stalker-soc-coop-fixes/tree/main/tools/xrcore_4gb

---

Патч xrMPE: аддоны больше 4 ГиБ (xrCore.dll)
============================================

Движок xrMPE 32-битный и не мог загрузить файл .addon больше 4 ГиБ (игра падала при запуске). Патч исправляет файл движка game\\bin\\xrCore.dll, чтобы мог.
Сделан с разрешения команды xrMPE. Больше ничего не меняет.

1. Закройте игру, выделенный сервер (чёрное окно) и лаунчер xrMPE.
2. Запустите install_xrcore_patch.bat двойным щелчком. Он найдёт X-Ray Multiplayer Extension (или спросит путь).
Он проверяет, что ваш xrCore.dll это файл xrMPE 0.9 (SHA-256), сохраняет копию xrCore.dll.orig, применяет изменения и проверяет результат.
install_xrcore_patch.bat -Check показывает состояние, install_xrcore_patch.bat -Uninstall возвращает оригинал.

Нужен всем, кто играет или хостит с таким аддоном (хост, клиенты, выделенный сервер); без патча игра при запуске закрывается.
Обновление лаунчера может вернуть оригинальный xrCore.dll: запустите патч снова.
В архиве только изменения байтов, самого файла xrMPE нет. Ограничения: одна база внутри аддона меньше 2 ГиБ; обычные файлы, лежащие прямо в аддоне выше 4 ГиБ,
не поддерживаются; аддоны меньше 4 ГиБ работают как раньше.
Техническое описание: https://github.com/cranebeaker/stalker-soc-coop-fixes/tree/main/tools/xrcore_4gb
"""


def crlf(t):
    return b"\xef\xbb\xbf" + t.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("version")
    ap.add_argument("--xrcore-orig", required=True)
    ap.add_argument("--db", default=os.path.join(REPO, "build", "release_v1.4.3", "zzz_soc_coop_fixes.db"))
    ap.add_argument("--cutscenes", default=os.path.join(REPO, "cutscene_pack", "out"))
    ap.add_argument("--changes", default="1.4.3", help="version of installer\\changes_<v>.en/ru.txt used for the change list")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    out = a.out or os.path.join(REPO, "build", "bundle_v" + a.version)
    work = os.path.join(out, "_work")
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(work)
    for p in (a.xrcore_orig, a.db) + tuple(os.path.join(a.cutscenes, n) for n in ("zz_soc_cutscenes.db", "zz_soc_cutscenes_voice_rus.db", "zz_soc_cutscenes_voice_eng.db")):
        if not os.path.isfile(p):
            raise SystemExit("missing: " + p)
    # the engine patch: build the patched DLL (never shipped), make the stand-alone installer from the byte changes
    patched = os.path.join(work, "xrCore.patched.dll")
    subprocess.run([sys.executable, os.path.join(TOOL, "build_patch.py"), a.xrcore_orig, patched], check=True, capture_output=True)
    app = os.path.join(work, "applier")
    r = subprocess.run([sys.executable, os.path.join(TOOL, "make_applier.py"), a.xrcore_orig, patched, app], check=True, capture_output=True, text=True)
    print(r.stdout.strip())
    # stage the full release
    name = "SoC_COOP_fixes_v" + a.version
    stage = os.path.join(out, name)
    for d in ("installer", "cutscenes", "xrcore_4gb"):
        os.makedirs(os.path.join(stage, d))
    shutil.copyfile(a.db, os.path.join(stage, "zzz_soc_coop_fixes.db"))
    for n in ("zz_soc_cutscenes.db", "zz_soc_cutscenes_voice_rus.db", "zz_soc_cutscenes_voice_eng.db"):
        shutil.copyfile(os.path.join(a.cutscenes, n), os.path.join(stage, "cutscenes", n))
    shutil.copyfile(os.path.join(REPO, "installer", "install.ps1"), os.path.join(stage, "installer", "install.ps1"))
    open(os.path.join(stage, "installer", "install.bat"), "wb").write(
        ("@echo off\r\nrem Installs the fix patch and the cut-scene movies into coop.addon, the same way on every PC (see install.ps1).\r\n"
         "powershell -NoProfile -ExecutionPolicy Bypass -File \"%~dp0install.ps1\" -Db \"%~dp0..\\zzz_soc_coop_fixes.db\" %*\r\npause\r\n").encode("ascii"))
    for fn in ("install_xrcore_patch.ps1", "install_xrcore_patch.bat"):
        shutil.copyfile(os.path.join(app, fn), os.path.join(stage, "xrcore_4gb", fn))
    short = open(os.path.join(TOOL, "README.md"), encoding="utf-8").read()
    open(os.path.join(stage, "xrcore_4gb", "README.txt"), "wb").write(crlf(PATCH_README))
    en = "\n".join(read_changes(a.changes, "en"))
    ru = "\n".join(read_changes(a.changes, "ru"))
    readme = README_EN.format(ver=a.version, changes_en=en) + "\n\n" + README_RU.format(ver=a.version, changes_ru=ru)
    open(os.path.join(stage, "README.txt"), "wb").write(crlf(readme))
    # the stand-alone patch zip
    pstage = os.path.join(out, "SoC_COOP_4GB_patch")
    os.makedirs(pstage)
    for fn in ("install_xrcore_patch.ps1", "install_xrcore_patch.bat"):
        shutil.copyfile(os.path.join(app, fn), os.path.join(pstage, fn))
    open(os.path.join(pstage, "README.txt"), "wb").write(crlf(PATCH_README))
    # checks: no personal data (the local user name and every word of the environment variable SOC_FORBIDDEN_WORDS, comma separated:
    # put your own names there, never in this file), no em/en dashes
    forbidden = set()
    for w in [os.environ.get("USERNAME", ""), os.path.basename(os.path.expanduser("~"))] + os.environ.get("SOC_FORBIDDEN_WORDS", "").split(","):
        if len(w.strip()) >= 3:
            forbidden.add(w.strip().lower().encode())
    bad = []
    for root in (stage, pstage):
        for dp, dn, fns in os.walk(root):
            for fn in fns:
                p = os.path.join(dp, fn)
                if os.path.getsize(p) > 5 * 1024 * 1024:
                    continue
                b = open(p, "rb").read()
                low = b.lower()
                for w in forbidden:
                    if w in low:
                        bad.append((p, w))
                if fn.lower().endswith((".txt", ".ps1", ".bat")) and (("\u2014".encode() in b) or ("\u2013".encode() in b)):
                    bad.append((p, "dash"))
    if bad:
        raise SystemExit("REFUSING: " + repr(bad))
    zips = []
    for folder, zname in ((stage, name + ".zip"), (pstage, "SoC_COOP_4GB_patch.zip")):
        zp = os.path.join(out, zname)
        base = os.path.basename(folder)
        with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            for dp, dn, fns in sorted(os.walk(folder)):
                for fn in sorted(fns):
                    p = os.path.join(dp, fn)
                    z.write(p, os.path.join(base, os.path.relpath(p, folder)).replace("\\", "/"))
        zips.append(zp)
        print("%s  %.1f MB" % (zp, os.path.getsize(zp) / 2**20))
    shutil.rmtree(work)
    print("bundle OK")


if __name__ == "__main__":
    main()
