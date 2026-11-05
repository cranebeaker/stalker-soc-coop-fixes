# Opt-in capacity 8 library. Dot-sourcing defines functions only; no game is started.
# Windows PowerShell 5.1 / PowerShell 7, .NET only. Known xrMPE SoC addon 8.1 x86.
$script:CoopProfileName = 'coop_player_limit_profile.json'
$script:CoopPatchName = 'zzz_soc_coop_fixes.db'
$script:CoopOriginalHash = 'ef430b5f39628dcd03a4dd6e44b114559549660dd06d3f3218296d1eee1c462e'
$script:CoopPatchedHash = 'de8e7b892203abc0e7a667b1a56ad0844140f02a82461e8432edc6a3150f2860'
$script:CoopEngineSize = 7915520

function Get-CoopHash([string]$Path) {
    $s = [IO.File]::OpenRead($Path); $sha = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha.ComputeHash($s))).Replace('-', '').ToLowerInvariant() }
    finally { $sha.Dispose(); $s.Dispose() }
}

function Assert-CoopPlainPath([string]$Path) {
    # Reparse points include symlinks/junctions; reject them for mutable paths/backups.
    $p = [IO.Path]::GetFullPath($Path)
    while ($p) {
        if (Test-Path -LiteralPath $p) {
            $item = Get-Item -LiteralPath $p -Force
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw "Symlink/junction path refused: $p" }
        }
        $parent = [IO.Path]::GetDirectoryName($p)
        if ($parent -eq $p) { break }; $p = $parent
    }
}

function Read-CoopProfile([string]$Path) {
    if (-not [IO.File]::Exists($Path) -or (Get-Item -LiteralPath $Path).Length -gt 16384) { throw "Missing/oversized capacity profile: $Path" }
    $p = [IO.File]::ReadAllText($Path, [Text.Encoding]::UTF8) | ConvertFrom-Json
    if (($p.schema_version -isnot [int] -and $p.schema_version -isnot [long]) -or $p.schema_version -ne 1 -or
        ($p.capacity -isnot [int] -and $p.capacity -isnot [long]) -or $p.capacity -ne 8 -or $p.addon_version -cne '8.1' -or
        ($p.engine.size -isnot [int] -and $p.engine.size -isnot [long]) -or $p.engine.size -ne $script:CoopEngineSize -or
        $p.engine.original_sha256 -cne $script:CoopOriginalHash -or $p.engine.patched_sha256 -cne $script:CoopPatchedHash -or
        @($p.engine.PSObject.Properties).Count -ne 3) { throw 'Unsupported engine/capacity/addon profile' }
    if ($p.patch_db.name -cne $script:CoopPatchName -or
        ($p.patch_db.size -isnot [int] -and $p.patch_db.size -isnot [long]) -or
        $p.patch_db.size -le 0 -or $p.patch_db.size -ge 4294967296 -or
        $p.patch_db.sha256 -isnot [string] -or $p.patch_db.sha256 -cnotmatch '^[0-9a-f]{64}$') { throw 'Invalid patch_db profile' }
    return $p
}

function Get-CoopImage([string]$Path) {
    if (-not [IO.File]::Exists($Path) -or (Get-Item -LiteralPath $Path).Length -ne $script:CoopEngineSize) { throw "Unknown xrGame.dll size/missing: $Path" }
    $hash = Get-CoopHash $Path
    if ($hash -ceq $script:CoopOriginalHash) { $value = 4; $state = 'original' }
    elseif ($hash -ceq $script:CoopPatchedHash) { $value = 8; $state = 'patched' }
    else { throw "Unknown xrGame.dll SHA256: $Path ($hash)" }
    $data = [IO.File]::ReadAllBytes($Path) # Fixed known DLL: 7.6 MiB, never addon/DB.
    $sites = @(@(0x2BE435, 0x49, 0x14), @(0x2F1A71, 0xD0, 0x45))
    foreach ($site in $sites) {
        $sig = @(0x3C, $value, 0x76, 0x07, 0xC6, 0x86, $site[1], $site[2], 0, 0, $value)
        for ($i = 0; $i -lt $sig.Count; $i++) {
            if ($data[$site[0] + $i] -ne $sig[$i]) { throw "Unknown xrGame.dll signature at $($site[0]): $Path" }
        }
    }
    return [PSCustomObject]@{ State = $state; Bytes = $data; Hash = $hash }
}

function Get-CoopCaseDirs($Parents, [string]$Name) {
    foreach ($parent in $Parents) {
        foreach ($child in Get-ChildItem -LiteralPath $parent -Force) {
            if ($child.Name -ieq $Name -and $child.PSIsContainer) { $child.FullName }
        }
    }
}

function Assert-CoopNoLooseOverrides([string]$GamePath) {
    $roots = @(Get-CoopCaseDirs @($GamePath) 'gamedata')
    $configs = @(Get-CoopCaseDirs $roots 'configs')
    foreach ($rule in @(@('mp', 'cooperative_game.ltx'), @('ui', 'coop_lobby_wnd.xml'))) {
        foreach ($folder in @(Get-CoopCaseDirs $configs $rule[0])) {
            foreach ($file in Get-ChildItem -LiteralPath $folder -Force) {
                if ($file.Name -ieq $rule[1]) { throw "Loose override refused: $($file.FullName)" }
            }
        }
    }
    foreach ($levels in @(Get-CoopCaseDirs $roots 'levels')) {
        foreach ($level in Get-ChildItem -LiteralPath $levels -Force) {
            if (-not $level.PSIsContainer) { continue }
            foreach ($file in Get-ChildItem -LiteralPath $level.FullName -Force) {
                if ($file.Name -ieq 'level.game') { throw "Loose override refused: $($file.FullName)" }
            }
        }
    }
}

function Read-CoopOctal([byte[]]$Header, [int]$Offset, [int]$Length) {
    $s = [Text.Encoding]::ASCII.GetString($Header, $Offset, $Length).Trim([char]0, ' ')
    if (-not $s) { return [long]0 }
    if ($s -cnotmatch '^[0-7]+$') { throw 'Invalid tar octal field' }
    return [Convert]::ToInt64($s, 8)
}

function Get-CoopTar([string]$Path, [switch]$RequirePatch) {
    $stream = [IO.File]::OpenRead($Path)
    try {
        $entries = @(); $dbNames = @(); $seen = @{}; $pos = [long]0; $terminated = $false
        while ($pos + 512 -le $stream.Length) {
            $stream.Position = $pos; $h = New-Object byte[] 512
            if ($stream.Read($h, 0, 512) -ne 512) { throw 'Truncated tar header' }
            $nonzero = $false; foreach ($b in $h) { if ($b -ne 0) { $nonzero = $true; break } }
            if (-not $nonzero) {
                if ($stream.Length - $pos -lt 1024) { throw 'Missing tar end blocks' }
                $buf = New-Object byte[] 65536
                while (($n = $stream.Read($buf, 0, $buf.Length)) -gt 0) {
                    for ($i = 0; $i -lt $n; $i++) { if ($buf[$i] -ne 0) { throw 'Nonzero data after tar end' } }
                }
                $terminated = $true; break
            }
            $sum = 0; for ($i = 0; $i -lt 512; $i++) { if ($i -ge 148 -and $i -lt 156) { $sum += 32 } else { $sum += $h[$i] } }
            if ($sum -ne (Read-CoopOctal $h 148 8)) { throw 'Invalid tar checksum' }
            $name = [Text.Encoding]::ASCII.GetString($h, 0, 100).TrimEnd([char]0)
            $prefix = [Text.Encoding]::ASCII.GetString($h, 345, 155).TrimEnd([char]0)
            if ($prefix -or @('gamedata.db0','gamedata.db1','icon.webp','metadata.json',$script:CoopPatchName) -cnotcontains $name) {
                throw "Unknown addon entry/DB '$name'; restore original coop.addon before installing capacity 8"
            }
            if ($seen.ContainsKey($name)) { throw "Duplicate addon member: $name" }; $seen[$name] = $true
            if ($h[156] -ne 0 -and $h[156] -ne 48) { throw "Addon member must be a regular file: $name" }
            $size = Read-CoopOctal $h 124 12
            $end = $pos + 512 + [long]([Math]::Ceiling($size / 512.0) * 512)
            if ($end -gt $stream.Length) { throw "Truncated addon member: $name" }
            $entries += [PSCustomObject]@{ Name = $name; Offset = $pos; DataOffset = $pos + 512; Size = $size; RecordSize = $end - $pos }
            if ($name -match '\.db[0-9]*$') { $dbNames += $name }
            $pos = $end
        }
        if (-not $terminated) { throw 'Missing tar end blocks' }
        $expected = @('gamedata.db0','gamedata.db1')
        if ($RequirePatch -or $seen.ContainsKey($script:CoopPatchName)) { $expected += $script:CoopPatchName }
        if (($dbNames -join '|') -cne ($expected -join '|')) { throw 'Invalid addon DB order (expected db0, db1, fixes)' }
        foreach ($name in @('gamedata.db0','gamedata.db1','metadata.json','icon.webp')) {
            if (-not $seen.ContainsKey($name)) { throw "Missing addon base member: $name" }
        }
        return ,$entries
    } finally { $stream.Dispose() }
}

function Get-CoopRangeHash([string]$Path, $Entries) {
    $stream = [IO.File]::OpenRead($Path); $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $buf = New-Object byte[] 65536
        foreach ($entry in $Entries) {
            $stream.Position = $entry.DataOffset; $left = [long]$entry.Size
            while ($left -gt 0) {
                $n = $stream.Read($buf, 0, [int][Math]::Min($left, $buf.Length))
                if ($n -eq 0) { throw 'Truncated addon while hashing' }
                [void]$sha.TransformBlock($buf, 0, $n, $null, 0); $left -= $n
            }
        }
        [void]$sha.TransformFinalBlock((New-Object byte[] 0), 0, 0)
        return ([BitConverter]::ToString($sha.Hash)).Replace('-', '').ToLowerInvariant()
    } finally { $sha.Dispose(); $stream.Dispose() }
}

function Copy-CoopBytes($Source, $Destination, [long]$Length) {
    $buffer = New-Object byte[] 65536
    while ($Length -gt 0) {
        $n = $Source.Read($buffer, 0, [int][Math]::Min($Length, $buffer.Length))
        if ($n -eq 0) { throw 'Truncated file while staging' }
        $Destination.Write($buffer, 0, $n); $Length -= $n
    }
}

function Assert-CoopSameBase([string]$CurrentPath, $CurrentEntries, [string]$BackupPath, $BackupEntries) {
    # Hash raw records, preserving names, member boundaries, headers and padding.
    $current=@($CurrentEntries | Where-Object { $_.Name -cne $script:CoopPatchName } | ForEach-Object { [PSCustomObject]@{ DataOffset=$_.Offset; Size=$_.RecordSize } })
    $original=@($BackupEntries | Where-Object { $_.Name -cne $script:CoopPatchName } | ForEach-Object { [PSCustomObject]@{ DataOffset=$_.Offset; Size=$_.RecordSize } })
    if ((Get-CoopRangeHash $CurrentPath $current) -cne (Get-CoopRangeHash $BackupPath $original)) {
        throw 'Addon base changed since backup; current addon is preserved. Restore the intended original addon manually before continuing.'
    }
}

function New-CoopTarStage([string]$Addon, [string]$Db, [string]$Stage, $Entries) {
    $src = [IO.File]::OpenRead($Addon); $dst = [IO.File]::Create($Stage)
    try {
        foreach ($entry in $Entries) {
            if ($entry.Name -ceq $script:CoopPatchName) { continue }
            $src.Position = $entry.Offset; Copy-CoopBytes $src $dst $entry.RecordSize
        }
        $size = (Get-Item -LiteralPath $Db).Length
        $h = New-Object byte[] 512
        $fields = @(@(0,$script:CoopPatchName),@(100,"0000644`0"),@(108,"0000000`0"),@(116,"0000000`0"),
                    @(124,([Convert]::ToString([long]$size,8).PadLeft(11,'0')+"`0")),@(136,"00000000000`0"),@(156,'0'))
        foreach ($field in $fields) { $b = [Text.Encoding]::ASCII.GetBytes($field[1]); [Array]::Copy($b,0,$h,$field[0],$b.Length) }
        for ($i=148; $i -lt 156; $i++) { $h[$i]=32 }
        $sum=0; foreach ($b in $h) { $sum += $b }
        $b=[Text.Encoding]::ASCII.GetBytes([Convert]::ToString($sum,8).PadLeft(6,'0')+"`0 "); [Array]::Copy($b,0,$h,148,8)
        $dst.Write($h,0,512); $inputDb=[IO.File]::OpenRead($Db)
        try { Copy-CoopBytes $inputDb $dst $size } finally { $inputDb.Dispose() }
        $pad = [int]((512 - ($size % 512)) % 512)
        if ($pad) { $dst.Write((New-Object byte[] $pad),0,$pad) }
        $end=[long]([Math]::Ceiling(($dst.Position+1024)/10240.0)*10240)
        $dst.Write((New-Object byte[] ($end-$dst.Position)),0,[int]($end-$dst.Position))
        if ($dst.Length -gt 4294967296) { throw 'NOT INSTALLED: coop.addon would exceed 4 GiB' }
        $dst.Flush($true)
    } finally { $src.Dispose(); $dst.Dispose() }
}

function Test-CoopPlayerInstallation([string]$GamePath, [string]$ProfilePath = '') {
    if (-not $ProfilePath) { $ProfilePath = Join-Path $GamePath $script:CoopProfileName }
    $p = Read-CoopProfile $ProfilePath
    Assert-CoopNoLooseOverrides $GamePath
    foreach ($rel in @('bin/xrGame.dll','bin/dedicated/xrGame.dll')) {
        $path=Join-Path $GamePath $rel
        if ($rel -eq 'bin/xrGame.dll' -or (Test-Path -LiteralPath $path)) {
            if ((Get-CoopImage $path).State -ne 'patched') { throw "Capacity 8 DLL not installed: $path" }
        }
    }
    $addon=Join-Path $GamePath 'addons/coop.addon'; $entries=Get-CoopTar $addon -RequirePatch
    $patch=@($entries | Where-Object { $_.Name -ceq $script:CoopPatchName })
    if ($patch[0].Size -ne $p.patch_db.size -or (Get-CoopRangeHash $addon $patch) -cne $p.patch_db.sha256) { throw 'Installed patch DB size/SHA256 mismatch' }
}

function Publish-CoopFile([string]$Source, [string]$Destination, [string]$Rollback) {
    if ([IO.File]::Exists($Destination)) { [IO.File]::Replace($Source,$Destination,$Rollback) }
    else { [IO.File]::Move($Source,$Destination) }
}

function Remove-CoopFile([string]$Target, [string]$Rollback) {
    # Rename the marker inside the same transaction; only discard it after all
    # data/DLL/marker steps succeeded. Locked markers therefore trigger rollback.
    [IO.File]::Move($Target,$Rollback)
}

function Invoke-CoopPublications($Items) {
    $done=@()
    try {
        foreach ($item in $Items) {
            $old=[IO.File]::Exists($item.Target)
            $rollback=$item.Target+'.cap8-rollback-'+[Guid]::NewGuid().ToString('N')
            if ($item.Remove) { Remove-CoopFile $item.Target $rollback }
            else { Publish-CoopFile $item.Stage $item.Target $rollback }
            $done += [PSCustomObject]@{ Target=$item.Target; Rollback=$rollback; Existed=$old }
        }
    } catch {
        $failure=$_.Exception.Message; $errors=@()
        for ($i=$done.Count-1; $i -ge 0; $i--) {
            $item=$done[$i]
            try {
                if ($item.Existed) { [IO.File]::Replace($item.Rollback,$item.Target,[NullString]::Value) }
                else { [IO.File]::Delete($item.Target) }
            } catch { $errors += "$($item.Target): $($_.Exception.Message); recovery file $($item.Rollback)" }
        }
        if ($errors.Count) { throw "$failure; ROLLBACK INCOMPLETE: $($errors -join '; ')" }
        throw "$failure; ROLLBACK COMPLETE: previous published files restored"
    }
    foreach ($item in $done) {
        if ([IO.File]::Exists($item.Rollback)) {
            try { [IO.File]::Delete($item.Rollback) }
            catch { Write-Warning "Completed; temporary recovery file retained: $($item.Rollback): $($_.Exception.Message)" }
        }
    }
}

function Install-CoopPlayerLimit([string]$GamePath, [string]$Db, [string]$ProfilePath) {
    $GamePath=[IO.Path]::GetFullPath($GamePath)
    $p=Read-CoopProfile $ProfilePath
    if (-not [IO.File]::Exists($Db) -or (Get-Item -LiteralPath $Db).Length -ne $p.patch_db.size -or
        (Get-CoopHash $Db) -cne $p.patch_db.sha256) { throw 'Package DB size/SHA256 mismatch' }
    Assert-CoopPlainPath $GamePath; Assert-CoopNoLooseOverrides $GamePath
    $addon=Join-Path $GamePath 'addons/coop.addon'; Assert-CoopPlainPath $addon
    $entries=Get-CoopTar $addon
    $baseBytes=[long]0
    foreach ($entry in $entries) { if ($entry.Name -cne $script:CoopPatchName) { $baseBytes += $entry.RecordSize } }
    $finalSize=[long]([Math]::Ceiling(($baseBytes+512+[long]([Math]::Ceiling($p.patch_db.size/512.0)*512)+1024)/10240.0)*10240)
    if ($finalSize -gt 4294967296) { throw 'NOT INSTALLED: coop.addon would exceed 4 GiB / НЕ УСТАНОВЛЕНО: предел 4 ГиБ' }
    $sourceHash=Get-CoopHash $addon
    $dlls=@()
    foreach ($rel in @('bin/xrGame.dll','bin/dedicated/xrGame.dll')) {
        $path=Join-Path $GamePath $rel
        if ($rel -eq 'bin/xrGame.dll' -or (Test-Path -LiteralPath $path)) {
            Assert-CoopPlainPath $path; $image=Get-CoopImage $path; $backup=$path+'.cap8-original'
            Assert-CoopPlainPath $backup
            if (Test-Path -LiteralPath $backup) {
                if ((Get-CoopImage $backup).State -ne 'original') { throw "Incompatible DLL backup: $backup" }
            } elseif ($image.State -ne 'original') { throw "Patched DLL requires verified original backup: $backup" }
            $dlls += [PSCustomObject]@{ Path=$path; Backup=$backup; Image=$image }
        }
    }
    $backupAddon=$addon+'.cap8-original'; $backupHash=$backupAddon+'.sha256'
    Assert-CoopPlainPath $backupAddon; Assert-CoopPlainPath $backupHash
    if ((Test-Path -LiteralPath $backupAddon) -or (Test-Path -LiteralPath $backupHash)) {
        if (-not [IO.File]::Exists($backupAddon) -or -not [IO.File]::Exists($backupHash) -or
            ([IO.File]::ReadAllText($backupHash).Trim()) -cne (Get-CoopHash $backupAddon)) { throw "Incompatible/incomplete addon backup: $backupAddon" }
        $oldEntries=Get-CoopTar $backupAddon
        Assert-CoopSameBase $addon $entries $backupAddon $oldEntries
    } elseif (@($dlls | Where-Object { $_.Image.State -eq 'patched' }).Count) { throw 'Patched installation requires verified addon backup' }
    $targetProfile=Join-Path $GamePath $script:CoopProfileName; Assert-CoopPlainPath $targetProfile
    if (Test-Path -LiteralPath $targetProfile) { [void](Read-CoopProfile $targetProfile) }
    $items=@(); $stages=@()
    try {
        $stage=$addon+'.cap8-stage-'+[Guid]::NewGuid().ToString('N'); $stages += $stage
        New-CoopTarStage $addon $Db $stage $entries
        $newEntries=Get-CoopTar $stage -RequirePatch
        $patch=@($newEntries | Where-Object { $_.Name -ceq $script:CoopPatchName })
        if ($patch[0].Size -ne $p.patch_db.size -or (Get-CoopRangeHash $stage $patch) -cne $p.patch_db.sha256) { throw 'Staged addon DB verification failed' }
        $items += [PSCustomObject]@{ Stage=$stage; Target=$addon }
        foreach ($dll in $dlls) {
            $stage=$dll.Path+'.cap8-stage-'+[Guid]::NewGuid().ToString('N'); $stages += $stage
            $bytes=$dll.Image.Bytes.Clone()
            foreach ($offset in @(0x2BE435,0x2F1A71)) { $bytes[$offset+1]=8; $bytes[$offset+10]=8 }
            [IO.File]::WriteAllBytes($stage,$bytes)
            if ((Get-CoopImage $stage).State -ne 'patched') { throw 'Staged DLL verification failed' }
            $items += [PSCustomObject]@{ Stage=$stage; Target=$dll.Path }
        }
        $stage=$targetProfile+'.cap8-stage-'+[Guid]::NewGuid().ToString('N'); $stages += $stage
        [IO.File]::Copy($ProfilePath,$stage,$false); [void](Read-CoopProfile $stage)
        $items += [PSCustomObject]@{ Stage=$stage; Target=$targetProfile }
        # No mutable game files have changed. Publish verified immutable backups first.
        foreach ($dll in $dlls) {
            if ((Get-CoopHash $dll.Path) -cne $dll.Image.Hash) { throw 'DLL changed during staging; close game and launcher' }
            if (-not [IO.File]::Exists($dll.Backup)) { [IO.File]::Copy($dll.Path,$dll.Backup,$false) }
            if ((Get-CoopImage $dll.Backup).State -ne 'original') { throw 'DLL backup verification failed' }
        }
        if (-not [IO.File]::Exists($backupAddon)) {
            [IO.File]::Copy($addon,$backupAddon,$false)
            if ((Get-CoopHash $backupAddon) -cne $sourceHash) { throw 'Addon changed while copying backup' }
            [IO.File]::WriteAllText($backupHash,$sourceHash,[Text.Encoding]::ASCII)
        }
        if ((Get-CoopHash $addon) -cne $sourceHash) { throw 'Addon changed during staging; close game and launcher' }
        Invoke-CoopPublications $items
        Write-Host 'Capacity 8 installed; session limit remains a separate choice (1-8). / Режим 8 установлен.'
    } finally { foreach ($stage in $stages) { if ([IO.File]::Exists($stage)) { [IO.File]::Delete($stage) } } }
}

function Restore-CoopPlayerLimit([string]$GamePath) {
    $GamePath=[IO.Path]::GetFullPath($GamePath)
    # Restore the user's whole original addon and DLLs, retaining permanent backups.
    Assert-CoopPlainPath $GamePath
    $profile=Join-Path $GamePath $script:CoopProfileName
    $p=Read-CoopProfile $profile
    $addon=Join-Path $GamePath 'addons/coop.addon'; $backup=$addon+'.cap8-original'
    foreach ($path in @($profile,$addon,$backup,$backup+'.sha256')) { Assert-CoopPlainPath $path }
    if (-not [IO.File]::Exists($backup+'.sha256') -or ([IO.File]::ReadAllText($backup+'.sha256').Trim()) -cne (Get-CoopHash $backup)) { throw 'Addon backup verification failed' }
    $backupEntries=Get-CoopTar $backup
    $currentEntries=Get-CoopTar $addon -RequirePatch
    $patch=@($currentEntries | Where-Object { $_.Name -ceq $script:CoopPatchName })
    if ($patch[0].Size -ne $p.patch_db.size -or (Get-CoopRangeHash $addon $patch) -cne $p.patch_db.sha256) {
        throw 'Installed addon DB changed since capacity 8 installation; current addon is preserved'
    }
    Assert-CoopSameBase $addon $currentEntries $backup $backupEntries
    $items=@(); $stages=@()
    try {
        foreach ($rel in @('bin/xrGame.dll','bin/dedicated/xrGame.dll')) {
            $path=Join-Path $GamePath $rel
            if ($rel -eq 'bin/xrGame.dll' -or (Test-Path -LiteralPath $path)) {
                Assert-CoopPlainPath $path; Assert-CoopPlainPath ($path+'.cap8-original'); [void](Get-CoopImage $path)
                if ((Get-CoopImage ($path+'.cap8-original')).State -ne 'original') { throw 'Original DLL backup required' }
                $stage=$path+'.cap8-stage-'+[Guid]::NewGuid().ToString('N'); $stages += $stage
                [IO.File]::Copy($path+'.cap8-original',$stage,$false)
                $items += [PSCustomObject]@{ Stage=$stage; Target=$path }
            }
        }
        $stage=$addon+'.cap8-stage-'+[Guid]::NewGuid().ToString('N'); $stages += $stage
        [IO.File]::Copy($backup,$stage,$false); $items += [PSCustomObject]@{ Stage=$stage; Target=$addon }
        $items += [PSCustomObject]@{ Target=$profile; Remove=$true }
        Invoke-CoopPublications $items
        Write-Host 'Original addon and DLLs restored. / Исходные addon и DLL восстановлены.'
    } finally { foreach ($stage in $stages) { if ([IO.File]::Exists($stage)) { [IO.File]::Delete($stage) } } }
}
