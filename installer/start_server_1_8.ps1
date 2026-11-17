# Native Windows host selector. All readonly profile/DLL/DB/loose guards are
# shared with the installer; this script never edits saved host settings.
param([string]$GamePath = '', [string]$Players = '', [switch]$DryRun)
$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}
try {
    . (Join-Path $PSScriptRoot 'player_limit.ps1')
    if (-not $GamePath) { $GamePath = Read-Host 'Game folder / Каталог game' }
    $GamePath = [IO.Path]::GetFullPath($GamePath.Trim().Trim('"'))
    if (-not $Players) {
        $Players = Read-Host 'Session players 1-8, Enter = 5 / Лимит сессии 1-8, Enter = 5'
        if (-not $Players) { $Players = '5' }
    }
    if ($Players -cnotmatch '^[1-8]$') { throw 'Players must be a whole number 1-8 / Нужно целое число 1-8' }
    foreach ($rel in @('bin/dedicated/xrEngine.exe', 'fsgame_s.ltx', 'addons/coop.addon')) {
        if (-not [IO.File]::Exists((Join-Path $GamePath $rel))) { throw "Missing game file: $rel" }
    }
    Test-CoopPlayerInstallation -GamePath $GamePath
    $exe = Join-Path $GamePath 'bin/dedicated/xrEngine.exe'
    $cwd = Join-Path $GamePath 'bin'
    # One quoted native argument, no cmd.exe or string evaluation.
    $session = "server(coop_l01_escape/coop/hname=ShadowCoop/maxplayers=$Players/public=0/minplayers=1/portsv=5495) client(localhost)"
    $engineArgs = @('-i','-noprefetch','-nointro','-fsltx','..\fsgame_s.ltx','-use_all_spawn','-addon=coop.addon','-start',$session)
    if ($DryRun) {
        [PSCustomObject]@{ cwd=$cwd; argv=@($exe)+$engineArgs; capacity=8; players=[int]$Players; installation_verified=$true } | ConvertTo-Json -Depth 4
        exit 0
    }
    if ($env:OS -ne 'Windows_NT') { throw 'Native Windows only; Linux/Wine hosts use tools/start_coop_server.py with an explicit Wine prefix' }
    Write-Host "Capacity 8; session limit $Players / Режим 8; лимит сессии $Players"
    Push-Location -LiteralPath $cwd
    try { & $exe @engineArgs; $result = $LASTEXITCODE } finally { Pop-Location }
    exit $result
} catch { Write-Error $_; exit 1 }
