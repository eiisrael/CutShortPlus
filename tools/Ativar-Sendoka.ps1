# Ativa codigo novo do CutShortPlus apenas se nao houver tarefas em andamento.
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $py)) { throw "VENV_NAO_ENCONTRADA" }
$statusChecked = $false
$tasksRunning = $false
try {
    $state = Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/status" -TimeoutSec 3
    $statusChecked = $true
    $tasksRunning = @($state.tasks | Where-Object { $_.status -eq "working" }).Count -gt 0
} catch {
    $statusChecked = $false
}
$running = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like ("*" + $py + "*") -and
                   $_.CommandLine -like "*app.py*" })
if ($tasksRunning) { throw "CUTSHORT_TAREFAS_ATIVAS" }
if (-not $statusChecked -and $running.Count -gt 0) { throw "STATUS_INDISPONIVEL: sem reinicio para proteger tarefas" }
foreach ($p in $running) {
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Milliseconds 700
Start-Process -FilePath $py -ArgumentList @("app.py") -WorkingDirectory $root -WindowStyle Minimized
$ready = $false
for ($i = 0; $i -lt 25; $i++) {
    Start-Sleep -Milliseconds 350
    try {
        $boot = Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/bootstrap" -TimeoutSec 2
        if ($null -ne $boot.settings.sendoka_mode) { $ready = $true; break }
    } catch {}
}
if (-not $ready) { throw "SENDOKA_SERVER_NOT_READY" }
Write-Output "SENDOKA_ACTIVATED; NO_ACTIVE_TASKS; READY=YES"
