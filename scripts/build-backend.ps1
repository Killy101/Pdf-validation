<#
.SYNOPSIS
  Builds the validation engine (pdf-validation-backend.exe) with PyInstaller into electron\resources\backend.
.DESCRIPTION
  Uses the project .venv (created by run.bat -Dev or "py -3 -m venv .venv"). Installs the backend and build
  requirements, runs PyInstaller, signs the executable when a certificate is configured (see scripts\sign.ps1) and
  smoke-tests the result with a generated PDF and a clean environment.
#>
[CmdletBinding()]
param([string]$Python, [switch]$SkipTest)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (-not $Python) { $Python = Join-Path $root '.venv\Scripts\python.exe' }
$backend = Join-Path $root 'backend'
$build = Join-Path $root 'build'
$output = Join-Path $root 'electron\resources\backend'
if (-not (Test-Path -LiteralPath $Python)) { throw "Python was not found at $Python. Create the environment first: py -3 -m venv .venv" }

Write-Host '[1/4] Installing backend and build requirements'
& $Python -m pip install --quiet --disable-pip-version-check -r (Join-Path $backend 'requirements.txt') -r (Join-Path $backend 'requirements-build.txt')
if ($LASTEXITCODE) { throw 'Installing the requirements failed.' }

Write-Host '[2/4] Running PyInstaller'
Push-Location $backend
try {
    & $Python -m PyInstaller pdf-validation-backend.spec --noconfirm --clean --log-level WARN `
        --distpath (Join-Path $build 'backend-dist') --workpath (Join-Path $build 'pyinstaller')
    if ($LASTEXITCODE) { throw 'PyInstaller failed.' }
} finally { Pop-Location }

foreach ($old in $output, (Join-Path $root 'electron\resources\python')) {
    if (Test-Path -LiteralPath $old) { Remove-Item -LiteralPath $old -Recurse -Force }
}
New-Item -ItemType Directory -Force (Split-Path -Parent $output) | Out-Null
Move-Item (Join-Path $build 'backend-dist\pdf-validation-backend') $output
$exe = Join-Path $output 'pdf-validation-backend.exe'

Write-Host '[3/4] Signing'
& (Join-Path $PSScriptRoot 'sign.ps1') -Path $exe

if ($SkipTest) { Write-Host '[4/4] Smoke test skipped'; return }
Write-Host '[4/4] Smoke test of the packaged engine'
$sample = Join-Path $build 'smoke-sample.pdf'
& $Python -c "import sys; from reportlab.pdfgen.canvas import Canvas; c = Canvas(sys.argv[1]); c.drawString(72, 720, 'The Supreme Judicial Court'); c.showPage(); c.drawString(72, 720, 'Second page: the Supreme'); c.save()" $sample
if ($LASTEXITCODE) { throw 'Could not create the smoke-test PDF.' }
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'test-backend-exe.ps1') -BackendDir $output -SamplePdf $sample -Query 'the supreme'
if ($LASTEXITCODE) { throw 'The packaged engine failed its smoke test.' }
$size = (Get-ChildItem $output -Recurse -File | Measure-Object Length -Sum).Sum / 1MB
Write-Host ('Engine ready: {0} ({1:N0} MB)' -f $output, $size) -ForegroundColor Green
