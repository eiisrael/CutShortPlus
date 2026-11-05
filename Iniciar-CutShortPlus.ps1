$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    python -m venv (Join-Path $root ".venv")
    & $py -m pip install -r (Join-Path $root "requirements.txt")
    if ($LASTEXITCODE -ne 0) { throw "Instalacao falhou" }
}
$running = $false
try { $r=Invoke-WebRequest "http://127.0.0.1:8765/api/status" -TimeoutSec 2; $running=($r.StatusCode -eq 200) } catch {}
if (-not $running) {
    Start-Process -FilePath $py -ArgumentList @("app.py") -WorkingDirectory $root -WindowStyle Minimized
    $ready = $false
    foreach ($i in 1..20) {
        Start-Sleep -Milliseconds 350
        try {
            $r = Invoke-WebRequest "http://127.0.0.1:8765/api/status" -TimeoutSec 1
            if ($r.StatusCode -eq 200) { $ready = $true; break }
        } catch {}
    }
    if (-not $ready) { throw "CutShortPlus nao respondeu na porta 8765." }
}
Start-Process "http://127.0.0.1:8765/"
Write-Host "CutShortPlus aberto em http://127.0.0.1:8765/" -ForegroundColor Green
