$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false

$repoRoot = Split-Path -Parent $PSScriptRoot
$artifactsDir = Join-Path $repoRoot "artifacts"
$outputPath = Join-Path $artifactsDir "coverage.txt"
$jsonPath = Join-Path $artifactsDir "coverage.json"
$xmlPath = Join-Path $artifactsDir "coverage.xml"
New-Item -ItemType Directory -Force -Path $artifactsDir | Out-Null
$env:TEMP = $artifactsDir
$env:TMP = $artifactsDir

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    @(
        "No Python interpreter found."
        "Expected 'python' in PATH."
    ) | Set-Content -Encoding UTF8 $outputPath
    Write-Host "Saved result to $outputPath"
    exit 1
}

$pythonCmd = "python"
$env:PYTHONPATH = Join-Path $repoRoot "src"

"Running coverage with $pythonCmd" | Set-Content -Encoding UTF8 $outputPath

$stepStdoutPath = Join-Path $artifactsDir "coverage.step.stdout.txt"
$stepStderrPath = Join-Path $artifactsDir "coverage.step.stderr.txt"

$exitCode = 0
$defaultStepTimeoutMs = 180000
$coverageRunTimeoutMs = 300000

function Invoke-PythonStep {
    param(
        [string[]]$Arguments,
        [int]$TimeoutMs
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
    $psi.FileName = $pythonCmd
    $psi.Arguments = (($Arguments | ForEach-Object { Quote-Argument $_ }) -join " ")
    $psi.WorkingDirectory = $repoRoot
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
        return @{
            TimedOut = $true
            ExitCode = 124
            Stdout = $stdoutTask.GetAwaiter().GetResult()
            Stderr = $stderrTask.GetAwaiter().GetResult()
        }
    }

    $process.WaitForExit()
    return @{
        TimedOut = $false
        ExitCode = [int]$process.ExitCode
        Stdout = $stdoutTask.GetAwaiter().GetResult()
        Stderr = $stderrTask.GetAwaiter().GetResult()
    }
}

function Invoke-CoverageStep {
    param(
        [string]$Label,
        [string[]]$Arguments,
        [int]$TimeoutMs = $defaultStepTimeoutMs
    )

    "`n== $Label ==" | Add-Content -Encoding UTF8 $outputPath
    if (Test-Path $stepStdoutPath) { Remove-Item -Force $stepStdoutPath }
    if (Test-Path $stepStderrPath) { Remove-Item -Force $stepStderrPath }

    $result = Invoke-PythonStep -Arguments $Arguments -TimeoutMs $TimeoutMs
    Set-Content -Encoding UTF8 $stepStdoutPath $result.Stdout
    Set-Content -Encoding UTF8 $stepStderrPath $result.Stderr

    if ($result.TimedOut) {
        "stderr:" | Add-Content -Encoding UTF8 $outputPath
        "step timed out after timeout_ms=$TimeoutMs" | Add-Content -Encoding UTF8 $outputPath
        if (Test-Path $stepStdoutPath) {
            Get-Content $stepStdoutPath | Add-Content -Encoding UTF8 $outputPath
        }
        if (Test-Path $stepStderrPath) {
            Get-Content $stepStderrPath | Add-Content -Encoding UTF8 $outputPath
        }
        "step_exit_code=124" | Add-Content -Encoding UTF8 $outputPath
        return 124
    }

    $stepExitCode = [int]$result.ExitCode

    if (Test-Path $stepStdoutPath) {
        Get-Content $stepStdoutPath | Add-Content -Encoding UTF8 $outputPath
    }

    if (Test-Path $stepStderrPath) {
        "stderr:" | Add-Content -Encoding UTF8 $outputPath
        Get-Content $stepStderrPath | Add-Content -Encoding UTF8 $outputPath
    }

    "step_exit_code=$stepExitCode" | Add-Content -Encoding UTF8 $outputPath
    return $stepExitCode
}

$stepExitCode = Invoke-CoverageStep `
    -Label "coverage erase" `
    -Arguments @("-X", "utf8", "-m", "coverage", "erase")
if ($stepExitCode -ne 0) {
    $exitCode = $stepExitCode
}

if ($exitCode -eq 0) {
    $stepExitCode = Invoke-CoverageStep `
    -Label "coverage run" `
    -Arguments @(
        "-X", "utf8",
        "-m", "coverage", "run",
        "--rcfile", (Join-Path $repoRoot ".coveragerc"),
        "-m", "unittest", "discover",
        "-s", (Join-Path $repoRoot "tests"),
        "-v"
    ) `
    -TimeoutMs $coverageRunTimeoutMs
    if ($stepExitCode -ne 0) {
        $exitCode = $stepExitCode
    }
}

if ($exitCode -eq 0) {
    $stepExitCode = Invoke-CoverageStep `
        -Label "coverage report" `
        -Arguments @(
            "-X", "utf8",
            "-m", "coverage", "report",
            "--rcfile", (Join-Path $repoRoot ".coveragerc")
        )
    if ($stepExitCode -ne 0) {
        $exitCode = $stepExitCode
    }
}

if ($exitCode -eq 0) {
    $stepExitCode = Invoke-CoverageStep `
        -Label "coverage json" `
        -Arguments @(
            "-X", "utf8",
            "-m", "coverage", "json",
            "--rcfile", (Join-Path $repoRoot ".coveragerc"),
            "-o", $jsonPath
        )
    if ($stepExitCode -ne 0) {
        $exitCode = $stepExitCode
    }
}

if ($exitCode -eq 0) {
    $stepExitCode = Invoke-CoverageStep `
        -Label "coverage xml" `
        -Arguments @(
            "-X", "utf8",
            "-m", "coverage", "xml",
            "--rcfile", (Join-Path $repoRoot ".coveragerc"),
            "-o", $xmlPath
        )
    if ($stepExitCode -ne 0) {
        $exitCode = $stepExitCode
    }
}
"`ncoverage_json=$jsonPath" | Add-Content -Encoding UTF8 $outputPath
"coverage_xml=$xmlPath" | Add-Content -Encoding UTF8 $outputPath
"process_exit_code=$exitCode" | Add-Content -Encoding UTF8 $outputPath

Write-Host "Saved result to $outputPath"
exit $exitCode
