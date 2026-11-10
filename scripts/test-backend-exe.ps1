<#
.SYNOPSIS
  Smoke-tests the packaged validation engine on its own, without the project's Python environment.
.DESCRIPTION
  Starts pdf-validation-backend.exe with a clean environment (no PYTHONPATH, no virtual environment, no Python on PATH),
  checks the health endpoint and runs a PDF text search, which goes through an isolated worker process.
  With -Url it also validates the sample PDF against that Content URI; with -ReferenceUrl it runs Reference URL
  discovery from that website page. Both need internet access. The engine is stopped by closing its input, the same
  way the desktop shell stops it.
#>
[CmdletBinding()]
param(
    [string]$BackendDir,
    [Parameter(Mandatory = $true)][string]$SamplePdf,
    [string]$Query = 'Supreme Judicial Court',
    [string]$Url,
    [string]$ReferenceUrl
)
$ErrorActionPreference = 'Stop'
if (-not $BackendDir) { $BackendDir = Join-Path (Split-Path -Parent $PSScriptRoot) 'electron\resources\backend' }
$exe = Join-Path $BackendDir 'pdf-validation-backend.exe'
if (-not (Test-Path -LiteralPath $exe)) { throw "The engine was not found at $exe. Build it with scripts\build-backend.ps1." }
if (-not (Test-Path -LiteralPath $SamplePdf)) { throw "The sample PDF was not found: $SamplePdf" }

$logDir = Join-Path ([System.IO.Path]::GetTempPath()) ('pdfv-exe-smoke-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
$token = -join ((1..48) | ForEach-Object { '{0:x}' -f (Get-Random -Maximum 16) })
$listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, 0)
$listener.Start(); $port = $listener.LocalEndpoint.Port; $listener.Stop()

$info = New-Object System.Diagnostics.ProcessStartInfo
$info.FileName = $exe
$info.Arguments = "--port $port --exit-on-stdin-close"
$info.WorkingDirectory = [System.IO.Path]::GetTempPath()
$info.UseShellExecute = $false
$info.RedirectStandardInput = $true
$info.CreateNoWindow = $true
foreach ($name in 'PYTHONPATH', 'PYTHONHOME', 'VIRTUAL_ENV', 'PDF_VALIDATION_PYTHON') { [void]$info.EnvironmentVariables.Remove($name) }
$info.EnvironmentVariables['PATH'] = (($env:PATH -split ';') | Where-Object { $_ -and $_ -notmatch 'python|\.venv' }) -join ';'
$info.EnvironmentVariables['PDF_VALIDATION_DESKTOP_TOKEN'] = $token
$info.EnvironmentVariables['PDF_VALIDATION_LOG_DIR'] = $logDir

$base = "http://127.0.0.1:$port/api"
$auth = "Authorization: Bearer $token"
$failures = 0
function Check([string]$Name, [scriptblock]$Test) {
    try { $detail = & $Test; Write-Host ('  PASS  {0}  {1}' -f $Name, $detail) -ForegroundColor Green }
    catch { $script:failures++; Write-Host ('  FAIL  {0}  {1}' -f $Name, $_.Exception.Message) -ForegroundColor Red }
}
function Post([string]$Path, [string[]]$Fields, [int]$Seconds = 120) {
    $arguments = @('-s', '-S', '--max-time', $Seconds, '-H', $auth, '-F', ('document=@' + $SamplePdf + ';type=application/pdf'))
    foreach ($field in $Fields) { $arguments += @('-F', $field) }
    $text = & curl.exe @arguments "$base$Path"
    if ($LASTEXITCODE) { throw "curl exit code $LASTEXITCODE" }
    $body = $text | Out-String | ConvertFrom-Json
    if (-not $body.success) { throw ($text | Out-String) }
    return $body.data
}

Write-Host "Engine : $exe"
Write-Host "Logs   : $logDir"
$process = [System.Diagnostics.Process]::Start($info)
try {
    Check 'engine starts and reports healthy' {
        $deadline = (Get-Date).AddSeconds(60)
        while ($true) {
            if ($process.HasExited) { throw "the engine exited with code $($process.ExitCode)" }
            try { $health = Invoke-RestMethod "$base/health" -Headers @{ Authorization = "Bearer $token" } -TimeoutSec 3; break } catch { }
            if ((Get-Date) -gt $deadline) { throw 'no answer within 60 s' }
            Start-Sleep -Milliseconds 500
        }
        'status=' + ($health | ConvertTo-Json -Compress)
    }
    Check 'requests without the token are refused' {
        $code = & curl.exe -s -o NUL -w '%{http_code}' "$base/pdf-validations/configuration"
        if ($code -ne '401' -and $code -ne '403') { throw "expected 401 or 403, got $code" }
        "HTTP $code"
    }
    Check "text search through the worker ('$Query')" {
        $found = Post '/pdf-validations/search-text' @("query=$Query")
        if (-not $found.matches -or $found.matches.Count -eq 0) { throw 'no matches: ' + ($found | ConvertTo-Json -Compress -Depth 3) }
        '{0} matches on {1} pages, first on page {2}' -f $found.total_matches, $found.pages_matched, $found.matches[0].page
    }
    if ($Url) {
        Check 'validation against the Content URI' {
            $result = Post '/pdf-validations' @("content_uri=$Url") 300
            if (-not $result.status) { throw ($result | ConvertTo-Json -Compress -Depth 3) }
            'status={0} summary={1}' -f $result.status, $result.summary
        }
    }
    if ($ReferenceUrl) {
        Check 'Reference URL discovery' {
            $result = Post '/pdf-validations/reference-discovery' @("content_uri=$ReferenceUrl") 300
            if (-not $result.discovery) { throw ($result | ConvertTo-Json -Compress -Depth 3) }
            'status={0} path={1}' -f $result.discovery.status, (($result.discovery.path | ForEach-Object { $_.label }) -join ' > ')
        }
    }
} finally {
    if (-not $process.HasExited) {
        $process.StandardInput.Close()
        if (-not $process.WaitForExit(15000)) { $process.Kill(); $failures++; Write-Host '  FAIL  engine did not stop when its input closed' -ForegroundColor Red }
        else { Write-Host '  PASS  engine stopped when its input closed' -ForegroundColor Green }
    }
}
foreach ($log in (Get-ChildItem $logDir -Recurse -Filter '*.log' -ErrorAction SilentlyContinue)) {
    Write-Host ''
    Write-Host ('Events in ' + $log.Name + ':')
    Get-Content $log.FullName | ForEach-Object { if ($_ -match 'event=(\S+)') { '  ' + $Matches[1] } } | Select-Object -Unique | ForEach-Object { Write-Host $_ }
}
if ($failures) { Write-Host "$failures check(s) failed." -ForegroundColor Red; exit 1 }
Write-Host 'All checks passed.' -ForegroundColor Green
