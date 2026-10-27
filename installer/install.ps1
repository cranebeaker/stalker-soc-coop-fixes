# Shadow of COOP fix patch installer.
# Writes the patch files into coop.addon byte-for-byte the same way on every PC, so host and clients get the same
# addon checksum. (Dragging the file in with 7-Zip stores your user id and the file date, which makes every player's
# coop.addon different and the server reports "Different Versions".)
#
# Since v1.5 the original movies of the cut-scenes (zz_soc_cutscenes.db) go into coop.addon too, so the add-on is larger than 4 GiB.
# The 32-bit engine can only load that with the patched xrCore.dll (folder xrcore_4gb); this installer applies it when needed.
# The movie SOUND stays a personal choice: the sound file of your language is copied to game\patches (see -Voice).
#
# Usage: install.bat (zip layout: zzz_soc_coop_fixes.db and cutscenes\ next to the installer folder).
#        install.bat -Addon "D:\...\coop.addon"      install.bat -Voice rus|eng|none      install.bat -NoCutscenes
#        install.bat -NoEnginePatch (never touch xrCore.dll; refuses when the add-on would pass 4 GiB)      install.bat -Uninstall
param(
    [string]$Addon = "",
    [string]$Db = "",
    [string]$Voice = "auto",
    [switch]$NoCutscenes,
    [switch]$NoEnginePatch,
    [switch]$Uninstall
)
$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
$PatchName = "zzz_soc_coop_fixes.db"
$MoviesName = "zz_soc_cutscenes.db"
$VoiceNames = @{ rus = "zz_soc_cutscenes_voice_rus.db"; eng = "zz_soc_cutscenes_voice_eng.db" }
$BaseNames = @("gamedata.db0", "gamedata.db1", "icon.webp", "metadata.json")
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path

# Accepts the coop.addon file itself, its addons folder, the game folder or the install folder (even a nested
# "X-Ray Multiplayer Extension\X-Ray Multiplayer Extension"); returns the coop.addon file path or $null.
function Resolve-AddonPath([string]$p) {
    if (-not $p) { return $null }
    $p = $p.Trim().Trim('"').Trim()
    if (-not (Test-Path -LiteralPath $p)) { return $null }
    if (Test-Path -LiteralPath $p -PathType Leaf) { return (Resolve-Path -LiteralPath $p).Path }
    foreach ($rel in @("coop.addon", "addons\coop.addon", "game\addons\coop.addon",
                       "X-Ray Multiplayer Extension\game\addons\coop.addon")) {
        $c = Join-Path $p $rel
        if (Test-Path -LiteralPath $c -PathType Leaf) { return (Resolve-Path -LiteralPath $c).Path }
    }
    return $null
}

function Find-Addon {
    $roots = @($Here, (Join-Path $Here ".."))
    foreach ($d in [System.IO.DriveInfo]::GetDrives()) {
        if ($d.DriveType -ne 'Fixed' -or -not $d.IsReady) { continue }
        foreach ($sub in @("", "Games\", "Program Files\", "Program Files (x86)\")) {
            $roots += ($d.RootDirectory.FullName + $sub + "X-Ray Multiplayer Extension")
        }
    }
    foreach ($r in $roots) { $f = Resolve-AddonPath $r; if ($f) { return $f } }
    Write-Host "coop.addon not found automatically. / coop.addon не найден автоматически."
    Write-Host "You can paste the coop.addon file or its folder. / Можно вставить путь к файлу coop.addon или к его папке."
    $p = Read-Host "Path / Путь"
    $f = Resolve-AddonPath $p
    if (-not $f) { throw "coop.addon not found at: $p / coop.addon не найден по пути: $p" }
    return $f
}

function Read-Octal([byte[]]$h, [int]$off, [int]$len) {
    $s = [System.Text.Encoding]::ASCII.GetString($h, $off, $len).Trim([char]0, ' ')
    if ($s -eq "") { return [long]0 }
    return [Convert]::ToInt64($s, 8)
}

function Write-Field([byte[]]$h, [int]$off, [string]$s) {
    $b = [System.Text.Encoding]::ASCII.GetBytes($s)
    [Array]::Copy($b, 0, $h, $off, $b.Length)
}

# True when game\bin\xrCore.dll carries the 4 GiB patch (a section named .xpat, see xrcore_4gb\README.md).
function Test-EnginePatched([string]$game) {
    try {
        $p = Join-Path $game "bin\xrCore.dll"
        if (-not (Test-Path -LiteralPath $p)) { return $false }
        $f = [System.IO.File]::Open($p, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
        try { $b = New-Object byte[] 4096; [void]$f.Read($b, 0, 4096) } finally { $f.Close() }
        $pe = [BitConverter]::ToInt32($b, 0x3c)
        $n = [int][BitConverter]::ToUInt16($b, $pe + 6)
        $st = $pe + 24 + [int][BitConverter]::ToUInt16($b, $pe + 20)
        for ($i = 0; $i -lt $n; $i++) {
            if ([System.Text.Encoding]::ASCII.GetString($b, $st + 40 * $i, 8).TrimEnd([char]0) -eq ".xpat") { return $true }
        }
    } catch {}
    return $false
}

# movie sound language: coop_settings.ltx [client] voice_language, else the launcher language (config.json), else the Windows language
function Get-AutoVoice([string]$game) {
    try {
        $ltx = Join-Path $game "_appdata_\coop_settings.ltx"
        if (Test-Path -LiteralPath $ltx) {
            $in = $false
            foreach ($line in [System.IO.File]::ReadAllLines($ltx)) {
                $t = $line.Trim()
                if ($t -match '^\[(.+)\]') { $in = ($Matches[1].Trim().ToLower() -eq "client"); continue }
                if ($in -and $t -match '^voice_language\s*=\s*(\w+)') {
                    $v = $Matches[1].ToLower()
                    if ($v -eq "rus" -or $v -eq "eng") { return $v }
                }
            }
        }
    } catch {}
    try {
        $cfg = Join-Path (Split-Path -Parent $game) "config.json"
        if (Test-Path -LiteralPath $cfg) {
            $j = Get-Content -LiteralPath $cfg -Raw | ConvertFrom-Json
            if ($j.language) { if ($j.language.ToString().ToLower().StartsWith("ru")) { return "rus" } else { return "eng" } }
        }
    } catch {}
    try { if ((Get-Culture).TwoLetterISOLanguageName -eq "ru") { return "rus" } } catch {}
    return "eng"
}

if ($Addon -eq "") { $Addon = Find-Addon }
else {
    $f = Resolve-AddonPath $Addon
    if (-not $f) { throw "coop.addon not found at: $Addon / coop.addon не найден по пути: $Addon" }
    $Addon = $f
}
$GameDir = Split-Path -Parent (Split-Path -Parent $Addon)      # ...\game (coop.addon is in game\addons)

# the files written into the add-on, in this order: (member name, source file)
$Members = @()
if (-not $Uninstall) {
    if ($Db -eq "") { $Db = Join-Path $Here $PatchName }
    if (-not (Test-Path -LiteralPath $Db)) { throw "$PatchName not found next to install.bat / не найден рядом с install.bat" }
    $Members += , @($PatchName, $Db)
    if (-not $NoCutscenes) {
        $cut = Join-Path (Split-Path -Parent $Db) "cutscenes"
        $mv = Join-Path $cut $MoviesName
        if (Test-Path -LiteralPath $mv) { $Members += , @($MoviesName, $mv) }
        else { Write-Host "Cut-scene movies ($MoviesName) not found next to the patch, installing the fixes only. / Ролики ($MoviesName) не найдены, ставлю только исправления." -ForegroundColor Yellow }
    }
}
Write-Host "coop.addon: $Addon"

try {
    $fs = [System.IO.File]::Open($Addon, [System.IO.FileMode]::Open, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
} catch {
    Write-Host "Cannot open coop.addon for writing. Close the game AND the xrMPE launcher, then run install.bat again." -ForegroundColor Red
    Write-Host "Не удалось открыть coop.addon для записи. Закройте игру И лаунчер xrMPE, затем снова запустите install.bat." -ForegroundColor Red
    Write-Host "If it still fails, right-click install.bat > Run as administrator. / Если не помогает: ПКМ по install.bat > Запуск от имени администратора."
    throw
}
try {
    # Walk the tar headers. Keep the add-on's own entries; cut everything from the first extra entry on.
    $pos = [long]0
    $cut = [long]-1
    $h = New-Object byte[] 512
    while ($pos + 512 -le $fs.Length) {
        $fs.Position = $pos
        [void]$fs.Read($h, 0, 512)
        $allZero = $true
        foreach ($x in $h) { if ($x -ne 0) { $allZero = $false; break } }
        if ($allZero) { if ($cut -lt 0) { $cut = $pos }; break }
        $nameEnd = [Array]::IndexOf($h, [byte]0)
        if ($nameEnd -lt 0 -or $nameEnd -gt 100) { $nameEnd = 100 }
        $name = [System.Text.Encoding]::ASCII.GetString($h, 0, $nameEnd)
        $size = Read-Octal $h 124 12
        if ($BaseNames -contains $name) {
            if ($cut -ge 0) { throw "coop.addon has '$name' after an extra file; restore your coop.addon backup or re-download the add-on." }
        } elseif ($cut -lt 0) {
            $cut = $pos
            Write-Host "Removing old entry / Удаляю старый файл: $name"
        } else {
            Write-Host "Removing old entry / Удаляю старый файл: $name"
        }
        $pos += 512 + [long]([Math]::Ceiling($size / 512.0) * 512)
    }
    if ($cut -lt 0) { $cut = $pos }
    $seen = @()
    $fs.Position = 0
    $p2 = [long]0
    while ($p2 -lt $cut) {
        $fs.Position = $p2; [void]$fs.Read($h, 0, 512)
        $nameEnd = [Array]::IndexOf($h, [byte]0); if ($nameEnd -lt 0 -or $nameEnd -gt 100) { $nameEnd = 100 }
        $seen += [System.Text.Encoding]::ASCII.GetString($h, 0, $nameEnd)
        $p2 += 512 + [long]([Math]::Ceiling((Read-Octal $h 124 12) / 512.0) * 512)
    }
    foreach ($b in $BaseNames) { if ($seen -notcontains $b) { throw "This does not look like the Shadow of COOP coop.addon (missing $b)." } }

    if (-not $Uninstall) {
        # Size of the finished add-on. Above 4 GiB the 32-bit engine needs the patched xrCore.dll: apply it (or refuse) BEFORE touching coop.addon.
        $finalSize = $cut
        foreach ($m in $Members) {
            $len = (Get-Item -LiteralPath $m[1]).Length
            if ($len -ge 2147483648) { throw "$($m[0]) is 2 GiB or larger; the engine cannot load a member that big / $($m[0]) 2 ГиБ или больше, движок такой файл не загрузит" }
            $finalSize += 512 + [long]([Math]::Ceiling($len / 512.0) * 512)
        }
        $finalSize += 1024
        $finalSize = [long]([Math]::Ceiling($finalSize / 10240.0) * 10240)
        $limit4g = [long]4294967296
        if ($finalSize -gt $limit4g -and -not (Test-EnginePatched $GameDir)) {
            $patcher = Join-Path (Split-Path -Parent $Db) "xrcore_4gb\install_xrcore_patch.ps1"
            if (-not $NoEnginePatch -and (Test-Path -LiteralPath $patcher)) {
                Write-Host ""
                Write-Host "coop.addon will be larger than 4 GiB: patching the engine (game\bin\xrCore.dll, a backup is kept) first. / coop.addon будет больше 4 ГиБ: сначала патчу движок (game\bin\xrCore.dll, копия сохраняется)." -ForegroundColor Yellow
                $fs.Close()
                & $patcher -Game $GameDir
                $fs = [System.IO.File]::Open($Addon, [System.IO.FileMode]::Open, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
            }
            if (-not (Test-EnginePatched $GameDir)) {
                $over = [Math]::Round(($finalSize - $limit4g) / 1MB, 1)
                Write-Host ""
                Write-Host "NOT INSTALLED: coop.addon would be $finalSize bytes, $over MB over the 4 GiB limit of the 32-bit game engine, and game\bin\xrCore.dll is not patched (the game would not load)." -ForegroundColor Red
                Write-Host "Run xrcore_4gb\install_xrcore_patch.bat (close the game and the launcher first), or install with -NoCutscenes. If your coop.addon is bigger than the original, restore the original one." -ForegroundColor Red
                Write-Host "НЕ УСТАНОВЛЕНО: coop.addon стал бы $finalSize байт, это на $over МБ больше предела 4 ГиБ 32-битного движка, а game\bin\xrCore.dll не пропатчен (игра не загрузится)." -ForegroundColor Red
                Write-Host "Запустите xrcore_4gb\install_xrcore_patch.bat (сначала закройте игру и лаунчер) или установите с ключом -NoCutscenes. Если ваш coop.addon больше оригинального, восстановите оригинальный." -ForegroundColor Red
                throw "coop.addon would exceed 4 GiB / coop.addon превысил бы 4 ГиБ"
            }
        }
    }
    $fs.SetLength($cut)
    $fs.Position = $cut
    if (-not $Uninstall) {
        foreach ($m in $Members) {
            $name = $m[0]
            $len = (Get-Item -LiteralPath $m[1]).Length
            $hdr = New-Object byte[] 512
            Write-Field $hdr 0 $name
            Write-Field $hdr 100 "0000644`0"                                   # mode
            Write-Field $hdr 108 "0000000`0"                                   # uid
            Write-Field $hdr 116 "0000000`0"                                   # gid
            Write-Field $hdr 124 ([Convert]::ToString([long]$len, 8).PadLeft(11, '0') + "`0")
            Write-Field $hdr 136 "00000000000`0"                               # mtime 0: same on every PC
            Write-Field $hdr 156 "0"                                           # regular file
            for ($i = 148; $i -lt 156; $i++) { $hdr[$i] = 32 }
            $sum = 0; foreach ($x in $hdr) { $sum += $x }
            Write-Field $hdr 148 ([Convert]::ToString($sum, 8).PadLeft(6, '0') + "`0 ")
            $fs.Write($hdr, 0, 512)
            $src = [System.IO.File]::Open($m[1], [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::Read)
            try {
                $buf = New-Object byte[] 4194304
                while (($n = $src.Read($buf, 0, $buf.Length)) -gt 0) { $fs.Write($buf, 0, $n) }
            } finally { $src.Close() }
            $pad = (512 - ($len % 512)) % 512
            if ($pad -gt 0) { $fs.Write((New-Object byte[] $pad), 0, $pad) }
            Write-Host ("Added to coop.addon / Добавлено в coop.addon: {0} ({1:N1} MB)" -f $name, ($len / 1MB))
        }
    }
    # End of archive: two zero blocks, then pad to a whole 10240-byte record.
    $end = $fs.Position + 1024
    $end = [long]([Math]::Ceiling($end / 10240.0) * 10240)
    $zeros = New-Object byte[] ($end - $fs.Position)
    $fs.Write($zeros, 0, $zeros.Length)
    $fs.SetLength($end)
} finally {
    $fs.Close()
}

# The movies are inside the add-on now: drop the copy an older cut-scene pack put into game\patches (same files, would only double them).
$patches = Join-Path $GameDir "patches"
if (-not $Uninstall -and ($Members | Where-Object { $_[0] -eq $MoviesName })) {
    $old = Join-Path $patches $MoviesName
    if (Test-Path -LiteralPath $old) { Remove-Item -LiteralPath $old -Force; Write-Host "Removed the old copy of the movies from patches\ / Удалена старая копия роликов из patches\" }
}
# Movie sound: one language per player, a file in game\patches (it does not change the add-on, so players may differ).
if ($Uninstall) {
    foreach ($n in $VoiceNames.Values) {
        $f = Join-Path $patches $n
        if (Test-Path -LiteralPath $f) { Remove-Item -LiteralPath $f -Force; Write-Host "Removed / Удалено: patches\$n" }
    }
} elseif (-not $NoCutscenes -and ($Members | Where-Object { $_[0] -eq $MoviesName }) -and $Voice -ne "none") {
    $v = $Voice
    if ($v -eq "auto") { $v = Get-AutoVoice $GameDir }
    if (-not $VoiceNames.ContainsKey($v)) { throw "-Voice must be auto, rus, eng or none / -Voice: auto, rus, eng или none" }
    $vsrc = Join-Path (Join-Path (Split-Path -Parent $Db) "cutscenes") $VoiceNames[$v]
    if (Test-Path -LiteralPath $vsrc) {
        if (-not (Test-Path -LiteralPath $patches)) { New-Item -ItemType Directory -Force -Path $patches | Out-Null }
        foreach ($n in $VoiceNames.Values) { $f = Join-Path $patches $n; if (Test-Path -LiteralPath $f) { Remove-Item -LiteralPath $f -Force } }
        $dst = Join-Path $patches $VoiceNames[$v]
        Copy-Item -LiteralPath $vsrc -Destination ($dst + ".part") -Force
        Move-Item -LiteralPath ($dst + ".part") -Destination $dst -Force
        $label = @{ rus = "Russian / русский"; eng = "English / английский" }[$v]
        Write-Host "Movie sound / озвучка роликов: $label  (install.bat -Voice rus|eng to change, or set voice_language in coop_settings.ltx / сменить: -Voice rus|eng)"
    } else { Write-Host "Movie sound file $($VoiceNames[$v]) not found, the movies play without their sound. / Файл озвучки $($VoiceNames[$v]) не найден." -ForegroundColor Yellow }
}

$sha = (Get-FileHash -LiteralPath $Addon -Algorithm SHA256).Hash.Substring(0, 12)
if ($Uninstall) { Write-Host "Patch removed. / Патч удалён." }
else { Write-Host "Installed. / Установлено." }
Write-Host "Addon fingerprint (must be the same for every player) / Отпечаток (должен совпадать у всех): $sha"
