# Windows smoke test for the record page (design 20261025 M5).
#   1) run the three python test suites (runs_api / test_core / handoff_test)
#   2) start the python bridge (record page backend, default 8764, -Port overrides)
#   3) check GET /app/ serves the page and GET /api/sessions returns JSON
# Usage: powershell -ExecutionPolicy Bypass -File windows\test-record.ps1
#       [-Python C:\path\python.exe] [-Port 8764]
# NOTE: keep this file pure ASCII. Windows PowerShell 5.1 reads a BOM-less
#       script as ANSI, and Chinese comments then break the parser.
param(
    [string]$Python = "",
    [int]$Port = 8764
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot   # repo root (parent of windows\)
Set-Location $root
$env:PYTHONIOENCODING = "utf-8"            # tests assert Chinese text
$env:PYTHONUTF8 = "1"                      # force UTF-8 mode in child python
$env:PYTHONUNBUFFERED = "1"                # child logs must reach the redirect files

if (-not $Python) { $Python = $env:DINGCODE_PYTHON }
if (-not $Python) {
    # py.exe first: python.exe is often the Store alias stub on Windows.
    foreach ($cand in @("py.exe", "python.exe", "python3.exe")) {
        $found = Get-Command $cand -ErrorAction SilentlyContinue
        if ($found) { $Python = $found.Source; break }
    }
}
if (-not $Python) { Write-Host "FAIL: no python found, pass -Python"; exit 1 }
Write-Host "python: $Python"

# -- 1) unit tests -----------------------------------------------------------
$failed = @()
foreach ($script in @("core\test_runs_api.py", "core\test_core.py", "handoff_test.py")) {
    Write-Host ""
    Write-Host "== python $script =="
    & $Python $script
    if ($LASTEXITCODE -ne 0) { $failed += $script }
}
if ($failed.Count -gt 0) {
    Write-Host ""
    Write-Host "FAIL: tests did not all pass: $($failed -join ', ')"
    exit 1
}

# -- 2) start the bridge -------------------------------------------------------
Write-Host ""
Write-Host "== bridge check (127.0.0.1:$port) =="
$env:DINGCODE_API_PORT = "$Port"
$outLog = Join-Path $env:TEMP "dingcode-test-record-out.log"
$errLog = Join-Path $env:TEMP "dingcode-test-record-err.log"
$proc = Start-Process -FilePath $Python `
    -ArgumentList @("handoff.py", "bridge", "--port", "$Port") `
    -WorkingDirectory $root -WindowStyle Hidden `
    -RedirectStandardOutput $outLog -RedirectStandardError $errLog -PassThru

$ok = $false
$appErr = "not attempted"
$apiErr = "not attempted"
try {
    for ($i = 0; $i -lt 30; $i++) {
        if ($proc.HasExited) { break }
        $appOk = $false
        $apiOk = $false
        try {
            $app = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$Port/app/" -TimeoutSec 3
            # The built index.html is a minimal SPA shell: its title is
            # Chinese and the literal "record" never appears in it. What is
            # stable across rebuilds: the #app mount node and /app/assets/.
            if ($app.StatusCode -eq 200 -and
                $app.Content -match 'id="app"' -and
                $app.Content -match "/app/assets/") {
                $appOk = $true
            } else {
                $appErr = "HTTP $($app.StatusCode), content check failed (body length $($app.Content.Length))"
            }
        } catch {
            $appErr = $_.Exception.Message
        }
        try {
            $sessions = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$Port/api/sessions" -TimeoutSec 3
            if ($sessions.StatusCode -eq 200 -and $sessions.Content -match '"ok"\s*:\s*true') {
                $apiOk = $true
            } else {
                $apiErr = "HTTP $($sessions.StatusCode), body: $($sessions.Content)"
            }
        } catch {
            $apiErr = $_.Exception.Message
        }
        if ($appOk -and $apiOk) { $ok = $true; break }
        Start-Sleep -Milliseconds 500
    }
}
finally {
    if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }
}

# -- 3) verdict ----------------------------------------------------------------
if ($ok) {
    Write-Host ""
    Write-Host "PASS: all three test suites passed; /app/ serves the page, /api/sessions returns JSON"
    exit 0
}
Write-Host ""
if ($proc.HasExited) {
    Write-Host "FAIL: bridge check failed (bridge exited with code $($proc.ExitCode))"
} else {
    Write-Host "FAIL: bridge check failed (bridge still running after $((30 * 0.5))s of polling; not a crash)"
}
Write-Host "--- last /app/ error ---"
Write-Host $appErr
Write-Host "--- last /api/sessions error ---"
Write-Host $apiErr
Write-Host "--- stdout ($outLog) ---";  Get-Content $outLog -ErrorAction SilentlyContinue
Write-Host "--- stderr ($errLog) ---";  Get-Content $errLog -ErrorAction SilentlyContinue
exit 1
