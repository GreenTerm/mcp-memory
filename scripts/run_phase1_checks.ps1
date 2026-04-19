$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false

$repoRoot = Split-Path -Parent $PSScriptRoot
$artifactsDir = Join-Path $repoRoot "artifacts"
$outputPath = Join-Path $artifactsDir "phase1_checks.txt"
New-Item -ItemType Directory -Force -Path $artifactsDir | Out-Null

function Resolve-Python {
    $candidates = @()
    if ($env:PYTHON) {
        $candidates += $env:PYTHON
    }
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        $candidates += $pythonCommand.Source
    }
    $localPython = Join-Path $env:LOCALAPPDATA "Programs\Python\Python310\python.exe"
    if (Test-Path $localPython) {
        $candidates += $localPython
    }

    foreach ($candidate in $candidates) {
        try {
            & $candidate -X utf8 -c "import sys; print(sys.executable)" *> $null
            if ($LASTEXITCODE -eq 0) {
                return $candidate
            }
        } catch {
            continue
        }
    }

    return $null
}

$pythonCmd = Resolve-Python
if (-not $pythonCmd) {
    @(
        "No Python interpreter found."
        "Set PYTHON to a python.exe path, or install Python in PATH."
    ) | Set-Content -Encoding UTF8 $outputPath
    Write-Host "Saved result to $outputPath"
    exit 1
}

$env:PYTHONPATH = Join-Path $repoRoot "src"
@(
    "Running Phase 1 checks with $pythonCmd"
    "PYTHONPATH=$env:PYTHONPATH"
    ""
) | Set-Content -Encoding UTF8 $outputPath

& $pythonCmd -X utf8 -m unittest tests.test_gui_home tests.test_api_server -v *>&1 |
    Tee-Object -FilePath $outputPath -Append
$exitCode = $LASTEXITCODE

"process_exit_code=$exitCode" | Add-Content -Encoding UTF8 $outputPath
Write-Host "Saved result to $outputPath"
exit $exitCode
