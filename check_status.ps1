$ErrorActionPreference = "SilentlyContinue"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$logPath = Join-Path $scriptDir "tracker.log"

$procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like "*tracker.py*" }

Write-Host "=== Ovenbird Tracker Status ===" -ForegroundColor Cyan

if ($procs) {
    foreach ($p in $procs) {
        $started = $p.CreationDate
        Write-Host "RUNNING" -ForegroundColor Green -NoNewline
        Write-Host "  (PID $($p.ProcessId), started $started)"
    }
} else {
    Write-Host "NOT RUNNING" -ForegroundColor Red
    Write-Host "Start it with: python `"$scriptDir\tracker.py`""
}

Write-Host ""
if (Test-Path $logPath) {
    $lastLine = Get-Content $logPath -Tail 1
    if ($lastLine -match '^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})') {
        $lastTime = [datetime]::ParseExact($matches[1], "yyyy-MM-ddTHH:mm:ss", $null)
        $ageMin = [math]::Round(((Get-Date) - $lastTime).TotalMinutes, 1)
        Write-Host "Last log entry: $ageMin min ago"
        if ($procs -and $ageMin -gt 15) {
            Write-Host "WARNING: process is running but hasn't logged in a while - it may be stuck." -ForegroundColor Yellow
        }
    }
    Write-Host ""
    Write-Host "Last 5 log lines:" -ForegroundColor Cyan
    Get-Content $logPath -Tail 5
} else {
    Write-Host "No tracker.log found yet."
}
