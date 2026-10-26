# 记录页 Windows 实机自检（设计 20261025 M5）。
#   1) 跑三组 python 单测（runs_api / test_core / handoff_test）
#   2) 启动 python bridge（记录页后端，默认 8764，可用 -Port 覆盖）
#   3) 自检 GET /app/ 出页、GET /api/sessions 出 JSON
# 用法: powershell -ExecutionPolicy Bypass -File windows\test-record.ps1
#       [-Python C:\path\python.exe] [-Port 8764]
param(
    [string]$Python = "",
    [int]$Port = 8764
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot   # 仓库根（windows\ 的上一级）
Set-Location $root
$env:PYTHONIOENCODING = "utf-8"            # 用例里有中文断言，控制台编码必须 UTF-8

if (-not $Python) { $Python = $env:DINGCODE_PYTHON }
if (-not $Python) {
    foreach ($cand in @("python.exe", "python3.exe", "py.exe")) {
        $found = Get-Command $cand -ErrorAction SilentlyContinue
        if ($found) { $Python = $found.Source; break }
    }
}
if (-not $Python) { Write-Host "FAIL: 没找到 python，可用 -Python 指定"; exit 1 }
Write-Host "python: $Python"

# -- 1) 单测 ----------------------------------------------------------------
$failed = @()
foreach ($script in @("core\test_runs_api.py", "core\test_core.py", "handoff_test.py")) {
    Write-Host ""
    Write-Host "== python $script =="
    & $Python $script
    if ($LASTEXITCODE -ne 0) { $failed += $script }
}
if ($failed.Count -gt 0) {
    Write-Host ""
    Write-Host "FAIL: 单测未全过: $($failed -join ', ')"
    exit 1
}

# -- 2) 起 bridge -------------------------------------------------------------
Write-Host ""
Write-Host "== bridge 自检 (127.0.0.1:$port) =="
$env:DINGCODE_API_PORT = "$Port"
$outLog = Join-Path $env:TEMP "dingcode-test-record-out.log"
$errLog = Join-Path $env:TEMP "dingcode-test-record-err.log"
$proc = Start-Process -FilePath $Python `
    -ArgumentList @("handoff.py", "bridge", "--port", "$Port") `
    -WorkingDirectory $root -WindowStyle Hidden `
    -RedirectStandardOutput $outLog -RedirectStandardError $errLog -PassThru

$ok = $false
try {
    for ($i = 0; $i -lt 30; $i++) {
        if ($proc.HasExited) { break }
        $appOk = $false
        $apiOk = $false
        try {
            $app = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$Port/app/" -TimeoutSec 3
            $appOk = ($app.StatusCode -eq 200 -and $app.Content -match "record")
        } catch {}
        try {
            $sessions = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$Port/api/sessions" -TimeoutSec 3
            $apiOk = ($sessions.StatusCode -eq 200 -and $sessions.Content -match '"ok"\s*:\s*true')
        } catch {}
        if ($appOk -and $apiOk) { $ok = $true; break }
        Start-Sleep -Milliseconds 500
    }
}
finally {
    if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }
}

# -- 3) 结论 ----------------------------------------------------------------
if ($ok) {
    Write-Host ""
    Write-Host "PASS: 三组单测通过；/app/ 出页，/api/sessions 出 JSON"
    exit 0
}
Write-Host ""
Write-Host "FAIL: bridge 自检未通过（进程退出码 $($proc.ExitCode)）"
Write-Host "--- stdout ($outLog) ---";  Get-Content $outLog -ErrorAction SilentlyContinue
Write-Host "--- stderr ($errLog) ---";  Get-Content $errLog -ErrorAction SilentlyContinue
exit 1
