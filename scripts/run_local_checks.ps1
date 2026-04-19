$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false

$repoRoot = Split-Path -Parent $PSScriptRoot
$artifactsDir = Join-Path $repoRoot "artifacts"
$outputPath = Join-Path $artifactsDir "local_checks.txt"
$stdoutPath = Join-Path $artifactsDir "local_checks.stdout.txt"
$stderrPath = Join-Path $artifactsDir "local_checks.stderr.txt"
$coveragePath = Join-Path $artifactsDir "coverage.txt"
$smokeTimeoutMs = 180000
$phaseExitCode = 0

New-Item -ItemType Directory -Force -Path $artifactsDir | Out-Null

function Invoke-ExternalProcess {
    param(
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$WorkingDirectory,
        [int]$TimeoutMs,
        [string]$StdoutPath,
        [string]$StderrPath
    )

    function Quote-Argument {
        param([string]$Value)
        if ($null -eq $Value) {
            return '""'
        }
        if ($Value -notmatch '[\s"]') {
            return $Value
        }
        return '"' + ($Value -replace '"', '\"') + '"'
    }

    $psi = [System.Diagnostics.ProcessStartInfo]::new()
    $psi.FileName = $FilePath
    $psi.Arguments = (($Arguments | ForEach-Object { Quote-Argument $_ }) -join " ")
    $psi.WorkingDirectory = $WorkingDirectory
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true

    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $psi
    [void]$process.Start()

    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()

    if (-not $process.WaitForExit($TimeoutMs)) {
        try { $process.Kill($true) } catch {}
        $process.WaitForExit()
        $stdout = $stdoutTask.GetAwaiter().GetResult()
        $stderr = $stderrTask.GetAwaiter().GetResult()
        Set-Content -Encoding UTF8 $StdoutPath $stdout
        Set-Content -Encoding UTF8 $StderrPath $stderr
        return @{ TimedOut = $true; ExitCode = 124 }
    }

    $process.WaitForExit()
    $stdout = $stdoutTask.GetAwaiter().GetResult()
    $stderr = $stderrTask.GetAwaiter().GetResult()
    Set-Content -Encoding UTF8 $StdoutPath $stdout
    Set-Content -Encoding UTF8 $StderrPath $stderr
    return @{ TimedOut = $false; ExitCode = [int]$process.ExitCode }
}

$pythonCmd = $null
if (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonCmd = "python"
}

if (-not $pythonCmd) {
    @(
        "No Python interpreter found."
        "Expected 'python' in PATH."
    ) | Set-Content -Encoding UTF8 $outputPath
    Write-Host "Saved result to $outputPath"
    exit 1
}

"Running checks with $pythonCmd" | Set-Content -Encoding UTF8 $outputPath
$env:PYTHONPATH = Join-Path $repoRoot "src"
if (Test-Path $stdoutPath) { Remove-Item -Force $stdoutPath }
if (Test-Path $stderrPath) { Remove-Item -Force $stderrPath }

"`n== PHASE CHECKS ==" | Add-Content -Encoding UTF8 $outputPath
$phaseScripts = Get-ChildItem -Path $PSScriptRoot -Filter "run_phase*_checks.ps1" |
    Sort-Object Name

foreach ($phaseScript in $phaseScripts) {
    "`n== $($phaseScript.BaseName) ==" | Add-Content -Encoding UTF8 $outputPath
    $phaseNumber = [regex]::Match($phaseScript.BaseName, "run_phase(\d+)_checks").Groups[1].Value
    $phaseOutputPath = Join-Path $artifactsDir "phase$phaseNumber`_checks.txt"
    $phaseStdoutPath = Join-Path $artifactsDir "phase$phaseNumber`_checks.stdout.txt"
    $phaseStderrPath = Join-Path $artifactsDir "phase$phaseNumber`_checks.stderr.txt"

    @(
        "Running Phase $phaseNumber checks with $pythonCmd"
        "PYTHONPATH=$env:PYTHONPATH"
        ""
    ) | Set-Content -Encoding UTF8 $phaseOutputPath

    $phaseResult = Invoke-ExternalProcess `
        -FilePath $pythonCmd `
        -Arguments @(
            "-X", "utf8",
            "-m", "unittest", "discover",
            "-s", (Join-Path $repoRoot "tests"),
            "-v"
        ) `
        -WorkingDirectory $repoRoot `
        -TimeoutMs 180000 `
        -StdoutPath $phaseStdoutPath `
        -StderrPath $phaseStderrPath

    $currentPhaseExitCode = [int]$phaseResult.ExitCode
    if ($phaseResult.TimedOut) {
        $currentPhaseExitCode = 124
        "phase timed out after timeout_ms=180000" | Add-Content -Encoding UTF8 $phaseOutputPath
    }
    $phaseExitCode = [Math]::Max($phaseExitCode, $currentPhaseExitCode)

    if (Test-Path $phaseStdoutPath) {
        Get-Content $phaseStdoutPath | Add-Content -Encoding UTF8 $phaseOutputPath
    }
    if (Test-Path $phaseStderrPath) {
        "stderr:" | Add-Content -Encoding UTF8 $phaseOutputPath
        Get-Content $phaseStderrPath | Add-Content -Encoding UTF8 $phaseOutputPath
    }
    "process_exit_code=$currentPhaseExitCode" | Add-Content -Encoding UTF8 $phaseOutputPath

    "phase_script=$($phaseScript.Name)" | Add-Content -Encoding UTF8 $outputPath
    "phase_report=$phaseOutputPath" | Add-Content -Encoding UTF8 $outputPath
    "phase_process_exit_code=$currentPhaseExitCode" | Add-Content -Encoding UTF8 $outputPath
    Get-Content $phaseOutputPath | Add-Content -Encoding UTF8 $outputPath
}

"`nphase_checks_process_exit_code=$phaseExitCode" | Add-Content -Encoding UTF8 $outputPath

"`n== SMOKE ==" | Add-Content -Encoding UTF8 $outputPath
$processResult = Invoke-ExternalProcess `
    -FilePath $pythonCmd `
    -Arguments @("-X", "utf8", (Join-Path $repoRoot "scripts\local_smoke_check.py")) `
    -WorkingDirectory $repoRoot `
    -TimeoutMs $smokeTimeoutMs `
    -StdoutPath $stdoutPath `
    -StderrPath $stderrPath

if ($processResult.TimedOut) {
    "`n== TIMEOUT ==" | Add-Content -Encoding UTF8 $outputPath
    "local_smoke_check.py exceeded timeout_ms=$smokeTimeoutMs" | Add-Content -Encoding UTF8 $outputPath
    if (Test-Path $stdoutPath) {
        Get-Content $stdoutPath | Add-Content -Encoding UTF8 $outputPath
    }
    if (Test-Path $stderrPath) {
        "`n== STDERR ==" | Add-Content -Encoding UTF8 $outputPath
        Get-Content $stderrPath | Add-Content -Encoding UTF8 $outputPath
    }
    exit 1
}

$exitCode = [int]$processResult.ExitCode

if (Test-Path $stdoutPath) {
    Get-Content $stdoutPath | Add-Content -Encoding UTF8 $outputPath
}

if (Test-Path $stderrPath) {
    "`n== STDERR ==" | Add-Content -Encoding UTF8 $outputPath
    Get-Content $stderrPath | Add-Content -Encoding UTF8 $outputPath
}

"`nsmoke_process_exit_code=$exitCode" | Add-Content -Encoding UTF8 $outputPath

"`n== COVERAGE ==" | Add-Content -Encoding UTF8 $outputPath
powershell -ExecutionPolicy Bypass -File (Join-Path $repoRoot "scripts\run_coverage.ps1") | Out-Null
$coverageExitCode = $LASTEXITCODE
"coverage_report=$coveragePath" | Add-Content -Encoding UTF8 $outputPath
"coverage_process_exit_code=$coverageExitCode" | Add-Content -Encoding UTF8 $outputPath

$finalExitCode = [Math]::Max($phaseExitCode, [Math]::Max($exitCode, $coverageExitCode))
"`nprocess_exit_code=$finalExitCode" | Add-Content -Encoding UTF8 $outputPath

Write-Host "Saved result to $outputPath"
exit $finalExitCode
