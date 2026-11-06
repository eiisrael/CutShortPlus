param()
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$csc = "$env:windir\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if (-not (Test-Path -LiteralPath $csc)) {
    $csc = "$env:windir\Microsoft.NET\Framework\v4.0.30319\csc.exe"
}
if (-not (Test-Path -LiteralPath $csc)) { throw "Compilador C# do .NET Framework 4 nao encontrado." }
$source = Join-Path $PSScriptRoot "Start-CSP.cs"
$icon = Join-Path $root "assets\cutshortplus.ico"
$output = Join-Path $root "Start-CSP.exe"
if (-not (Test-Path $icon)) { throw "Icone de aplicativo ausente." }
& $csc /nologo /target:winexe /platform:anycpu /r:System.dll /r:System.Drawing.dll /r:System.Windows.Forms.dll "/win32icon:$icon" "/out:$output" $source
if ($LASTEXITCODE -ne 0) { throw "Compilacao do Start-CSP.exe falhou." }
Write-Host "Executavel criado: $output"
