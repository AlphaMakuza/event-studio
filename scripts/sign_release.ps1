param(
    [Parameter(Mandatory=$true)][string]$CertificateThumbprint,
    [Parameter(Mandatory=$true)][uri]$TimestampUrl,
    [string]$SignTool = 'signtool.exe'
)
$ErrorActionPreference = 'Stop'
$releaseRoot = Split-Path -Parent $PSScriptRoot
$executable = Join-Path $releaseRoot 'dist/Event-Based-Studio/Event-Based-Studio.exe'
if (-not (Test-Path -LiteralPath $executable)) { throw 'Build the release folder first.' }
$certificate = Get-Item -LiteralPath "Cert:/CurrentUser/My/$CertificateThumbprint"
if (-not $certificate.HasPrivateKey) { throw 'The selected certificate has no accessible private key.' }
if ($certificate.NotAfter -lt (Get-Date)) { throw 'The signing certificate has expired.' }
& $SignTool sign /s My /sha1 $CertificateThumbprint /fd SHA256 /tr $TimestampUrl.AbsoluteUri /td SHA256 /d 'Event-Based Studio' $executable
if ($LASTEXITCODE -ne 0) { throw 'Signing failed.' }
& $SignTool verify /pa /all /v $executable
if ($LASTEXITCODE -ne 0) { throw 'Signature verification failed.' }
Write-Output 'Signature verified. Repackage the signed folder and regenerate SHA-256; do not rebuild the EXE afterward.'
