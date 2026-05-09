$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false

$repoRoot = Split-Path -Parent $PSScriptRoot
$artifactsDir = Join-Path $repoRoot "artifacts"
$outputPath = Join-Path $artifactsDir "release_check.txt"

New-Item -ItemType Directory -Force -Path $artifactsDir | Out-Null
$env:PYTHONPATH = Join-Path $repoRoot "src"

$pythonCmd = $null
$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if ($pythonCommand) {
    $pythonCmd = $pythonCommand.Source
}

if (-not $pythonCmd) {
    "No Python interpreter found. Expected 'python' in PATH." | Set-Content -Encoding UTF8 $outputPath
    Write-Host "Saved result to $outputPath"
    exit 1
}

"== RELEASE METADATA ==" | Set-Content -Encoding UTF8 $outputPath
& $pythonCmd -X utf8 (Join-Path $repoRoot "scripts\release_check.py") *>&1 | Add-Content -Encoding UTF8 $outputPath
$metadataExitCode = $LASTEXITCODE
"metadata_exit_code=$metadataExitCode" | Add-Content -Encoding UTF8 $outputPath
if ($metadataExitCode -ne 0) {
    Write-Host "Saved result to $outputPath"
    exit $metadataExitCode
}

"`n== LOCAL CHECKS ==" | Add-Content -Encoding UTF8 $outputPath
& (Join-Path $repoRoot "scripts\run_local_checks.ps1") *>&1 | Add-Content -Encoding UTF8 $outputPath
$localExitCode = $LASTEXITCODE
"local_checks_exit_code=$localExitCode" | Add-Content -Encoding UTF8 $outputPath

Write-Host "Saved result to $outputPath"
exit $localExitCode
