param(
    [Parameter(Mandatory=$true)][string]$ApplicationFolder,
    [Parameter(Mandatory=$true)][string]$ReportFolder
)
$ErrorActionPreference = 'Stop'
$folder = (Resolve-Path -LiteralPath $ApplicationFolder).Path
New-Item -ItemType Directory -Force -Path $ReportFolder | Out-Null
$reportRoot = (Resolve-Path -LiteralPath $ReportFolder).Path
$runId = [guid]::NewGuid().ToString('N')
$env:EVENT_STUDIO_HOME = Join-Path $reportRoot "user data-$runId"
$env:QT_QPA_PLATFORM = 'windows'
$env:PYTHONPATH = ''
$env:PYTHONHOME = ''
$env:PATH = Join-Path $env:SystemRoot 'System32'
$exe = Join-Path $folder 'Event-Based-Studio.exe'
$hash = (Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash
$process = Start-Process -FilePath $exe -ArgumentList '--smoke-test' -WorkingDirectory $folder -PassThru -WindowStyle Hidden
if (-not $process.WaitForExit(45000)) {
    Stop-Process -Id $process.Id
    throw 'Clean Windows check timed out; review the application log.'
}
$record = Join-Path $env:EVENT_STUDIO_HOME 'smoke-test.json'
if ($process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $record)) {
    throw "Application check failed with exit code $($process.ExitCode). See $env:EVENT_STUDIO_HOME"
}
$result = Get-Content -LiteralPath $record -Raw | ConvertFrom-Json
if (-not $result.passed -or -not $result.frozen) { throw 'Packaged functional checks failed.' }
$report = [ordered]@{
    tested_at = (Get-Date).ToUniversalTime().ToString('o')
    executable_sha256 = $hash
    windows_version = [Environment]::OSVersion.VersionString
    powershell_version = $PSVersionTable.PSVersion.ToString()
    msvc_runtime_version = (Get-Item -LiteralPath (Join-Path $env:SystemRoot 'System32/msvcp140.dll')).VersionInfo.FileVersion
    checks = $result.checks
    functional_checks_passed = $true
    clean_machine_confirmed_by_tester = $false
    manual_startup_audio_and_interaction = 'pending'
}
$destination = Join-Path $reportRoot "windows-check-$runId.json"
$report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $destination -Encoding UTF8
Write-Output "PASS packaged native checks. Report: $destination"
Write-Output 'Record whether this is a clean PC/VM and complete manual startup/audio/save/reopen checks before release approval.'
