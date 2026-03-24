param(
  [Parameter(Mandatory = $true)][string]$Task,
  [string]$Serial = "",
  [switch]$LaunchApp,
  [switch]$UseFileInbox,
  [int]$WaitSeconds = 10
)

$ErrorActionPreference = "Stop"

function Select-FirstAdbSerial {
  try {
    $lines = & adb devices 2>&1
    foreach ($line in $lines) {
      $s = ($line -as [string]).Trim()
      if (-not $s) { continue }
      if ($s -like "List of devices attached*") { continue }
      if ($s -match "^\s*(\S+)\s+device\s*$") { return $Matches[1] }
    }
  } catch {
    return $null
  }
  return $null
}

if (-not $Serial) {
  $Serial = Select-FirstAdbSerial
}
if (-not $Serial) {
  throw "No adb device found. Connect a device or pass -Serial <device>"
}

$pkg = "org.test.orderquery"
$remoteDir = "/storage/emulated/0/Android/data/$pkg/files/AppAgent"
$remoteFile = "$remoteDir/inbox_task.json"

function Resolve-LauncherComponent {
  param([Parameter(Mandatory = $true)][string]$PackageName)
  $component = ""
  try {
    $lines = & adb -s $Serial shell cmd package resolve-activity --brief -a android.intent.action.MAIN -c android.intent.category.LAUNCHER $PackageName 2>$null
    foreach ($line in $lines) {
      $s = ($line -as [string]).Trim()
      if (-not $s) { continue }
      if ($s -match "^[^\\s/]+/[^\\s]+$") { $component = $s }
    }
  } catch {
    $component = ""
  }
  if (-not $component) { $component = "$PackageName/org.kivy.android.PythonActivity" }
  return $component
}

if ($UseFileInbox) {
  $payload = @{
    task = $Task
    ts_ms = [int64]([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())
  } | ConvertTo-Json -Compress

  $tmp = [System.IO.Path]::Combine([System.IO.Path]::GetTempPath(), "appagent_inbox_task_$([Guid]::NewGuid().ToString('N')).json")
  [System.IO.File]::WriteAllText($tmp, $payload, (New-Object System.Text.UTF8Encoding($false)))

  try {
    & adb -s $Serial shell mkdir -p $remoteDir
    if ($LASTEXITCODE -ne 0) { throw "adb mkdir failed" }

    & adb -s $Serial push $tmp $remoteFile | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "adb push failed" }
  } finally {
    try { Remove-Item -LiteralPath $tmp -Force } catch { }
  }
}

$component = Resolve-LauncherComponent -PackageName $pkg
if ($LaunchApp -or (-not $UseFileInbox)) {
  & adb -s $Serial shell am start -n $component --es appagent_task $Task | Out-Host
}

if ($UseFileInbox -and $WaitSeconds -gt 0) {
  $deadline = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() + ([int64]$WaitSeconds * 1000)
  while ([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() -lt $deadline) {
    $exists = & adb -s $Serial shell sh -c "test -f \"$remoteFile\" && echo 1 || echo 0" 2>$null
    if (($exists -as [string]).Trim() -eq "0") { break }
    Start-Sleep -Milliseconds 300
  }
} elseif ($WaitSeconds -gt 0) {
  Start-Sleep -Seconds $WaitSeconds
}

Write-Host "Task sent."
