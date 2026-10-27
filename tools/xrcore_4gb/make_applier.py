"""Make install_xrcore_patch.ps1 (+ .bat): a standalone, Python-free installer of the >4 GiB patch.
It contains only the BYTE CHANGES (a diff between the original and the patched xrCore.dll), never xrMPE's file itself:
the patch is applied to the player's own xrCore.dll after checking its SHA-256, and undone from a backup copy.

usage: python make_applier.py <original xrCore.dll> <patched xrCore.dll> <out dir>
"""
import base64
import hashlib
import os
import sys

orig_p, patched_p, out_dir = sys.argv[1:4]
a = open(orig_p, "rb").read()
b = open(patched_p, "rb").read()
assert len(b) > len(a)
sha = lambda d: hashlib.sha256(d).hexdigest().upper()

hunks = []
i = 0
while i < len(a):
    if a[i] != b[i]:
        j = i
        gap = 0
        while j < len(a) and (a[j] != b[j] or gap < 4):
            gap = 0 if a[j] != b[j] else gap + 1
            j += 1
        j -= gap
        hunks.append((i, b[i:j]))
        i = j + gap
    else:
        i += 1
tail = b[len(a):]
# sanity: applying the hunks + tail reproduces the patched file exactly
t = bytearray(a)
for off, data in hunks:
    t[off:off + len(data)] = data
t += tail
assert bytes(t) == b

lines = []
for off, data in hunks:
    lines.append('    @(%d, "%s")' % (off, data.hex()))
hunk_txt = ",\r\n".join(lines)
tail_b64 = base64.b64encode(tail).decode()
tail_lines = "\r\n".join('    "%s"' % tail_b64[k:k + 100] + (" +" if k + 100 < len(tail_b64) else "") for k in range(0, len(tail_b64), 100))

ps = r'''# xrMPE xrCore.dll patch: lets the game load add-ons (.addon files) larger than 4 GiB.
# Русский: патч xrCore.dll для xrMPE, чтобы игра могла загружать аддоны (.addon) больше 4 ГиБ.
#
# What it does / Что делает: the engine is 32-bit and kept a few file offsets of the add-on loader in 32 bits (the 64-bit parts were
# already there). This patch fixes those places and adds the 64-bit handling for the video / streaming reader. It changes ONLY
# game\bin\xrCore.dll (a backup is kept as xrCore.dll.orig). Everyone who plays or hosts must apply it (host, clients, dedicated server).
# Патч меняет ТОЛЬКО game\bin\xrCore.dll (копия оригинала: xrCore.dll.orig). Ставить нужно всем: хосту, клиентам, выделенному серверу.
#
# Usage / Запуск:
#   install_xrcore_patch.bat                  apply the patch / применить патч
#   install_xrcore_patch.bat -Uninstall       restore the original xrCore.dll / вернуть оригинальный xrCore.dll
#   install_xrcore_patch.bat -Game "D:\X-Ray Multiplayer Extension\game"
# If the xrMPE launcher updates the game it can put the original xrCore.dll back: run this again.
# Если лаунчер xrMPE обновит игру, он может вернуть оригинальный xrCore.dll: запустите патч снова.
param(
    [string]$Game = "",
    [switch]$Uninstall,
    [switch]$Check
)
$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

# The xrCore.dll of xrMPE 0.9 this patch was made for, and the file it produces.
$OrigSha = "@@ORIGSHA@@"
$PatchedSha = "@@PATCHEDSHA@@"
$OrigLen = @@ORIGLEN@@
# v1.5.0 of the patch (crashed while loading a level on a real add-on): replaced by this version, the original is taken from xrCore.dll.orig
$OldPatchedSha = @("343C16D09FDC395DC19EE6BC5B3DCC31217B9BEBDFB100D7577AB626B29B7AAC")
# byte changes inside the original file: (offset, new bytes as hex)
$Hunks = @(
@@HUNKS@@
)
# bytes appended at the end of the file: the code section .xpat and the data section .xpad
$TailB64 = (
@@TAIL@@
)

function Get-Sha([string]$p) { return (Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash.ToUpper() }

# Accepts game\bin\xrCore.dll, the bin folder, the game folder or the install folder; returns the xrCore.dll path or $null.
function Resolve-Dll([string]$p) {
    if (-not $p) { return $null }
    $p = $p.Trim().Trim('"').Trim()
    if (-not (Test-Path -LiteralPath $p)) { return $null }
    if (Test-Path -LiteralPath $p -PathType Leaf) { return (Resolve-Path -LiteralPath $p).Path }
    foreach ($rel in @("xrCore.dll", "bin\xrCore.dll", "game\bin\xrCore.dll", "X-Ray Multiplayer Extension\game\bin\xrCore.dll")) {
        $c = Join-Path $p $rel
        if (Test-Path -LiteralPath $c -PathType Leaf) { return (Resolve-Path -LiteralPath $c).Path }
    }
    return $null
}

function Find-Dll {
    $Here = Split-Path -Parent $MyInvocation.ScriptName
    $roots = @($Here, (Join-Path $Here ".."))
    foreach ($d in [System.IO.DriveInfo]::GetDrives()) {
        if ($d.DriveType -ne 'Fixed' -or -not $d.IsReady) { continue }
        foreach ($sub in @("", "Games\", "Program Files\", "Program Files (x86)\")) {
            $roots += ($d.RootDirectory.FullName + $sub + "X-Ray Multiplayer Extension")
        }
    }
    foreach ($r in $roots) { $f = Resolve-Dll $r; if ($f) { return $f } }
    Write-Host "xrCore.dll not found automatically. / xrCore.dll не найден автоматически."
    Write-Host "Paste the game folder (the one with bin, addons, patches). / Вставьте путь к папке игры (где лежат bin, addons, patches)."
    $p = Read-Host "Path / Путь"
    $f = Resolve-Dll $p
    if (-not $f) { throw "xrCore.dll not found at: $p / xrCore.dll не найден по пути: $p" }
    return $f
}

if ($Game -eq "") { $dll = Find-Dll }
else {
    $dll = Resolve-Dll $Game
    if (-not $dll) { throw "xrCore.dll not found at: $Game / xrCore.dll не найден по пути: $Game" }
}
$backup = "$dll.orig"
Write-Host "xrCore.dll: $dll"
$sha = Get-Sha $dll

if ($Check) {
    if ($sha -eq $PatchedSha) { Write-Host "PATCHED: the >4 GiB patch is installed. / ПАТЧ УСТАНОВЛЕН." }
    elseif ($sha -eq $OrigSha) { Write-Host "NOT patched (original xrCore.dll of xrMPE 0.9). / НЕ пропатчен (оригинальный xrCore.dll)." }
    elseif ($OldPatchedSha -contains $sha) { Write-Host "OLD patch (v1.5.0) installed, run this again to update it. / Установлен СТАРЫЙ патч (v1.5.0), запустите установку снова для обновления." }
    else { Write-Host "Unknown xrCore.dll (SHA-256 $sha). / Неизвестная версия xrCore.dll." }
    return
}

if ($Uninstall) {
    if ($sha -eq $OrigSha) { Write-Host "Already the original xrCore.dll. / Уже оригинальный xrCore.dll."; return }
    if (-not (Test-Path -LiteralPath $backup) -or (Get-Sha $backup) -ne $OrigSha) {
        throw "No valid backup (xrCore.dll.orig) next to xrCore.dll. Let the xrMPE launcher repair the game files. / Нет копии xrCore.dll.orig. Пусть лаунчер xrMPE восстановит файлы игры."
    }
    try { Copy-Item -LiteralPath $backup -Destination $dll -Force }
    catch { throw "Cannot write xrCore.dll. Close the game, the dedicated server and the launcher. / Не удалось записать xrCore.dll. Закройте игру, сервер и лаунчер." }
    Write-Host "Original xrCore.dll restored. / Оригинальный xrCore.dll восстановлен."
    return
}

if ($sha -eq $PatchedSha) { Write-Host "Already patched. Nothing to do. / Уже пропатчено. Ничего делать не нужно."; return }
if ($OldPatchedSha -contains $sha) {
    if (-not (Test-Path -LiteralPath $backup) -or (Get-Sha $backup) -ne $OrigSha) {
        throw "Old patch found but no valid backup (xrCore.dll.orig). Let the xrMPE launcher repair the game files, then run this again. / Найден старый патч, но нет копии xrCore.dll.orig. Пусть лаунчер xrMPE восстановит файлы игры и запустите снова."
    }
    Write-Host "Updating the earlier version of the patch (v1.5.0 could close the game while a level loads). / Обновляю прежнюю версию патча (v1.5.0 мог закрывать игру при загрузке уровня)." -ForegroundColor Yellow
    try { Copy-Item -LiteralPath $backup -Destination $dll -Force }
    catch { throw "Cannot write xrCore.dll. Close the game, the dedicated server and the launcher. / Не удалось записать xrCore.dll. Закройте игру, сервер и лаунчер." }
    $sha = $OrigSha
}
if ($sha -ne $OrigSha) {
    Write-Host ""
    Write-Host "NOT PATCHED: this xrCore.dll is not the one the patch was made for (xrMPE 0.9, SHA-256 $OrigSha)." -ForegroundColor Red
    Write-Host "Yours has SHA-256 $sha. Update the game with the xrMPE launcher and try again, or ask for a new patch." -ForegroundColor Red
    Write-Host "НЕ ПРОПАТЧЕНО: этот xrCore.dll не тот, для которого сделан патч (xrMPE 0.9, SHA-256 $OrigSha)." -ForegroundColor Red
    Write-Host "У вас SHA-256 $sha. Обновите игру лаунчером xrMPE и повторите, либо попросите новый патч." -ForegroundColor Red
    throw "unknown xrCore.dll / неизвестный xrCore.dll"
}

$bytes = [System.IO.File]::ReadAllBytes($dll)
if ($bytes.Length -ne $OrigLen) { throw "unexpected size of xrCore.dll / неожиданный размер xrCore.dll" }
foreach ($h in $Hunks) {
    $hex = [string]$h[1]
    for ($i = 0; $i -lt $hex.Length / 2; $i++) { $bytes[[int]$h[0] + $i] = [Convert]::ToByte($hex.Substring($i * 2, 2), 16) }
}
$tail = [Convert]::FromBase64String($TailB64)
$new = New-Object byte[] ($bytes.Length + $tail.Length)
[Array]::Copy($bytes, 0, $new, 0, $bytes.Length)
[Array]::Copy($tail, 0, $new, $bytes.Length, $tail.Length)

$tmp = "$dll.new"
[System.IO.File]::WriteAllBytes($tmp, $new)
if ((Get-Sha $tmp) -ne $PatchedSha) { Remove-Item -LiteralPath $tmp -Force; throw "internal check failed (patched file differs from the expected one) / внутренняя проверка не прошла" }

if (-not (Test-Path -LiteralPath $backup)) { Copy-Item -LiteralPath $dll -Destination $backup }
try { Copy-Item -LiteralPath $tmp -Destination $dll -Force }
catch {
    Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
    Write-Host "Cannot write xrCore.dll. Close the game, the dedicated server (black window) and the xrMPE launcher, then run again." -ForegroundColor Red
    Write-Host "Не удалось записать xrCore.dll. Закройте игру, выделенный сервер (чёрное окно) и лаунчер xrMPE, затем запустите снова." -ForegroundColor Red
    throw
}
Remove-Item -LiteralPath $tmp -Force
Write-Host ""
Write-Host "Patched. The game can now load add-ons larger than 4 GiB. Original kept as xrCore.dll.orig." -ForegroundColor Green
Write-Host "Готово. Игра теперь может загружать аддоны больше 4 ГиБ. Оригинал сохранён как xrCore.dll.orig." -ForegroundColor Green
'''
ps = (ps.replace("@@ORIGSHA@@", sha(a)).replace("@@PATCHEDSHA@@", sha(b)).replace("@@ORIGLEN@@", str(len(a)))
        .replace("@@HUNKS@@", hunk_txt).replace("@@TAIL@@", tail_lines))
assert "\u2014" not in ps
os.makedirs(out_dir, exist_ok=True)
open(os.path.join(out_dir, "install_xrcore_patch.ps1"), "wb").write(b"\xef\xbb\xbf" + ps.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8"))
bat = ('@echo off\r\nrem Applies the >4 GiB patch to xrMPE\'s xrCore.dll (see install_xrcore_patch.ps1).\r\n'
       'powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_xrcore_patch.ps1" %*\r\npause\r\n')
open(os.path.join(out_dir, "install_xrcore_patch.bat"), "wb").write(bat.encode("ascii"))
print("hunks:", len(hunks), "tail bytes:", len(tail), "orig", sha(a)[:16], "patched", sha(b)[:16])
