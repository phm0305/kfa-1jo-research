# Copies the shared engine (tools/collect.py, tools/engine.py) as committed at one hash of the deployment
# repo into engine/, and records the hash in engine/SOURCE.txt.
# Only `git show` and `git log` are run against the deployment repo; its working tree is never read,
# because another session may be editing it.
# Usage (from the repo root): powershell -File scripts\copy_engine.ps1 -Hash <commit>
param(
    [Parameter(Mandatory = $true)][string]$Hash,
    [string]$SourceRepo
)
$ErrorActionPreference = "Stop"
# $PSScriptRoot is empty while Windows PowerShell 5.1 evaluates parameter defaults.
if (-not $SourceRepo) { $SourceRepo = Join-Path $PSScriptRoot "..\..\KFA-ai-agent-study" }
$files = @("collect.py", "engine.py")
$engine = Join-Path $PSScriptRoot "..\engine"
$SourceRepo = (Resolve-Path $SourceRepo).Path

$full = git -C $SourceRepo log -1 --format=%H $Hash
if ($LASTEXITCODE -ne 0 -or -not $full) { throw "Commit $Hash not found in $SourceRepo" }
$date = git -C $SourceRepo log -1 --format=%ad --date=iso $full

New-Item -ItemType Directory -Force $engine | Out-Null
foreach ($f in $files) {
    # PowerShell 5.1 re-encodes native output through its pipeline, so the bytes are copied from the raw stream.
    $psi = New-Object System.Diagnostics.ProcessStartInfo "git"
    $psi.Arguments = "-C `"$SourceRepo`" show ${full}:tools/$f"
    $psi.RedirectStandardOutput = $true
    $psi.UseShellExecute = $false
    $proc = [System.Diagnostics.Process]::Start($psi)
    $out = [System.IO.File]::Create((Join-Path $engine $f))
    $proc.StandardOutput.BaseStream.CopyTo($out)
    $out.Close()
    $proc.WaitForExit()
    if ($proc.ExitCode -ne 0) { throw "git show ${full}:tools/$f failed" }
}

$source = "repo: phm0305/KFA-ai-agent-study`ncommit: $full`ncommit date: $date`nfiles: tools/" + ($files -join ", tools/") + "`n"
[System.IO.File]::WriteAllText((Join-Path $engine "SOURCE.txt"), $source, (New-Object System.Text.UTF8Encoding $false))
Get-Content (Join-Path $engine "SOURCE.txt")
