<#
.SYNOPSIS
  Authenticode-signs and verifies Windows executables with signtool. The certificate never lives in the repository.
.DESCRIPTION
  The certificate is chosen with environment variables (set them in the build machine or CI secret store):
    PDF_VALIDATION_SIGN_THUMBPRINT  SHA-1 thumbprint of a code-signing certificate in the Windows certificate store
                                    (CurrentUser\My or LocalMachine\My; also works for USB tokens and cloud HSM providers).
    PDF_VALIDATION_SIGN_PFX         Path to a .pfx file outside the repository, with
    PDF_VALIDATION_SIGN_PASSWORD    its password.
  Optional:
    PDF_VALIDATION_SIGN_TIMESTAMP   RFC 3161 timestamp server (default http://timestamp.digicert.com).
    PDF_VALIDATION_SIGNTOOL         Full path to signtool.exe (default: newest Windows SDK copy).
    PDF_VALIDATION_SIGN_REQUIRED=1  Fail instead of leaving files unsigned when no certificate is configured.
    PDF_VALIDATION_SIGN_ALLOW_UNTRUSTED=1  Accept a signature whose root is not trusted (self-signed test certificates).
  Without a certificate the files are left unsigned and a warning is printed, so local builds still work.
#>
[CmdletBinding()]
param([Parameter(Mandatory = $true)][string[]]$Path, [switch]$Required)
$ErrorActionPreference = 'Stop'

$thumbprint = $env:PDF_VALIDATION_SIGN_THUMBPRINT
$pfx = $env:PDF_VALIDATION_SIGN_PFX
$required = $Required -or $env:PDF_VALIDATION_SIGN_REQUIRED -eq '1'
if (-not $thumbprint -and -not $pfx) {
    if ($required) { throw 'Signing is required but no certificate is configured (PDF_VALIDATION_SIGN_THUMBPRINT or PDF_VALIDATION_SIGN_PFX).' }
    foreach ($file in $Path) { Write-Warning "Not signed (no certificate configured): $file" }
    return
}
if ($pfx -and -not (Test-Path -LiteralPath $pfx)) { throw "The certificate file was not found: $pfx" }

$signtool = $env:PDF_VALIDATION_SIGNTOOL
if (-not $signtool) {
    $kits = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10\bin'
    $signtool = Get-ChildItem $kits -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
        Where-Object { $_.Directory.Name -eq 'x64' } | Sort-Object { $_.Directory.Parent.Name } -Descending |
        Select-Object -First 1 -ExpandProperty FullName
}
if (-not $signtool -or -not (Test-Path -LiteralPath $signtool)) {
    throw 'signtool.exe was not found. Install the Windows SDK "Signing Tools" or set PDF_VALIDATION_SIGNTOOL.'
}
$timestamp = if ($env:PDF_VALIDATION_SIGN_TIMESTAMP) { $env:PDF_VALIDATION_SIGN_TIMESTAMP } else { 'http://timestamp.digicert.com' }
$identity = if ($thumbprint) { @('/sha1', $thumbprint) } else { @('/f', $pfx, '/p', $env:PDF_VALIDATION_SIGN_PASSWORD) }

foreach ($file in $Path) {
    if (-not (Test-Path -LiteralPath $file)) { throw "File to sign was not found: $file" }
    # The password is passed to signtool only; it is never echoed or logged.
    & $signtool sign /fd SHA256 /td SHA256 /tr $timestamp @identity /d 'PDF Validation' $file | Out-Null
    if ($LASTEXITCODE) { throw "signtool could not sign $file (exit code $LASTEXITCODE). Check the certificate and the timestamp server." }
    $signature = Get-AuthenticodeSignature -LiteralPath $file
    $untrustedOk = $env:PDF_VALIDATION_SIGN_ALLOW_UNTRUSTED -eq '1' -and $signature.SignerCertificate -and $signature.Status -eq 'UnknownError'
    if ($signature.Status -ne 'Valid' -and -not $untrustedOk) {
        throw "The signature on $file did not verify: $($signature.Status) $($signature.StatusMessage)"
    }
    Write-Host ('Signed {0}  signer="{1}" status={2} timestamped={3}' -f $file, $signature.SignerCertificate.Subject, $signature.Status, [bool]$signature.TimeStamperCertificate)
}
