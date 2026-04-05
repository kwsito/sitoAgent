$ErrorActionPreference = "Stop"
$Package = "org.test.orderquery"
$KivyCount = 5

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

function Invoke-AdbText {
  param(
    [Parameter(Mandatory = $true)][string[]]$Arguments,
    [string]$StepName = "adb",
    [int[]]$AllowedExitCodes = @(0)
  )

  $output = & adb @Arguments 2>&1
  $exitCode = $LASTEXITCODE
  if ($AllowedExitCodes -notcontains $exitCode) {
    $text = ($output | Out-String).Trim()
    throw "Step failed ($StepName), exit code: $exitCode`n$text"
  }
  return @($output | ForEach-Object { ($_ -as [string]).TrimEnd("`r", "`n") })
}

function Invoke-AdbShellText {
  param(
    [Parameter(Mandatory = $true)][string]$Serial,
    [Parameter(Mandatory = $true)][string]$CommandText,
    [string]$StepName = "adb shell",
    [int[]]$AllowedExitCodes = @(0)
  )

  return Invoke-AdbText -Arguments @("-s", $Serial, "shell", $CommandText) -StepName $StepName -AllowedExitCodes $AllowedExitCodes
}

function Save-AdbRunAsFile {
  param(
    [Parameter(Mandatory = $true)][string]$Serial,
    [Parameter(Mandatory = $true)][string]$Package,
    [Parameter(Mandatory = $true)][string]$RemotePath,
    [Parameter(Mandatory = $true)][string]$LocalPath
  )

  $dir = Split-Path -Parent $LocalPath
  if ($dir) {
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
  }

  $stderrFile = [System.IO.Path]::Combine(
    [System.IO.Path]::GetTempPath(),
    ("adb_pull_logs_{0}.stderr" -f [Guid]::NewGuid().ToString("N"))
  )

  try {
    $proc = Start-Process -FilePath "adb" `
      -ArgumentList @("-s", $Serial, "exec-out", "run-as", $Package, "cat", $RemotePath) `
      -RedirectStandardOutput $LocalPath `
      -RedirectStandardError $stderrFile `
      -NoNewWindow `
      -PassThru `
      -Wait

    if ($proc.ExitCode -ne 0) {
      $stderr = ""
      if (Test-Path -LiteralPath $stderrFile) {
        $stderr = [System.IO.File]::ReadAllText($stderrFile)
      }
      throw "adb failed for $RemotePath`n$stderr"
    }
  } finally {
    if (Test-Path -LiteralPath $stderrFile) {
      Remove-Item -LiteralPath $stderrFile -Force -ErrorAction SilentlyContinue
    }
  }
}

function Get-RunAsList {
  param(
    [Parameter(Mandatory = $true)][string]$Serial,
    [Parameter(Mandatory = $true)][string]$Package,
    [Parameter(Mandatory = $true)][string]$ShellCommand,
    [switch]$AllowEmpty
  )

  $quotedCommand = "run-as $Package sh -c '$ShellCommand'"
  $allowed = if ($AllowEmpty) { @(0, 1) } else { @(0) }
  $lines = Invoke-AdbShellText -Serial $Serial -CommandText $quotedCommand -StepName "adb shell run-as" -AllowedExitCodes $allowed
  return @($lines | ForEach-Object { $_.Trim() } | Where-Object { $_ })
}

function Get-LatestTaskDirInfos {
  param(
    [Parameter(Mandatory = $true)][string]$Serial,
    [Parameter(Mandatory = $true)][string]$Package
  )

  $results = @()
  foreach ($base in @("files/tasks", "files/app/tasks")) {
    $items = @(Get-RunAsList -Serial $Serial -Package $Package -ShellCommand ("ls -1t {0} 2>/dev/null | head -n 1" -f $base) -AllowEmpty)
    if ($items.Count -gt 0) {
      $results += [pscustomobject]@{
        BaseDir = $base
        TaskDir = $items[0]
      }
    }
  }

  return @($results)
}

function Get-KivyLogList {
  param(
    [Parameter(Mandatory = $true)][string]$Serial,
    [Parameter(Mandatory = $true)][string]$Package,
    [Parameter(Mandatory = $true)][int]$Count
  )

  foreach ($base in @("files/.kivy/logs", "files/app/.kivy/logs")) {
    $items = @(Get-RunAsList -Serial $Serial -Package $Package -ShellCommand ("ls -1t {0}/kivy_*.txt 2>/dev/null | head -n {1}" -f $base, $Count) -AllowEmpty)
    if ($items.Count -gt 0) {
      return @{
        BaseDir = $base
        Paths = @($items)
      }
    }
  }

  return @{
    BaseDir = ""
    Paths = @()
  }
}

function Get-RecentTaskArtifacts {
  param(
    [Parameter(Mandatory = $true)][string]$Serial,
    [Parameter(Mandatory = $true)][string]$Package
  )

  foreach ($base in @("files/tasks", "files/app/tasks")) {
    $items = @(Get-RunAsList -Serial $Serial -Package $Package -ShellCommand ("find {0} -type f \( -name '*.png' -o -name '*.xml' -o -name '*.json' -o -name '*.txt' \) 2>/dev/null | sort" -f $base) -AllowEmpty)
    if ($items.Count -gt 0) {
      return @{
        BaseDir = $base
        Paths = @($items)
      }
    }
  }

  return @{
    BaseDir = ""
    Paths = @()
  }
}

$Serial = Select-FirstAdbSerial
if (-not $Serial) {
  throw "No adb device found. Connect one device and run .\pull_logs.ps1 again."
}

$ts = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
$OutDir = Join-Path $PSScriptRoot ("downloaded_snapshots\logs_snapshot_{0}" -f $ts)

$taskOut = Join-Path $OutDir "task"
$kivyOut = Join-Path $OutDir "kivy"
New-Item -ItemType Directory -Force -Path $taskOut, $kivyOut | Out-Null

$summary = New-Object System.Collections.Generic.List[string]
$summary.Add(("SERIAL={0}" -f $Serial))
$summary.Add(("PACKAGE={0}" -f $Package))
$summary.Add(("OUT_DIR={0}" -f $OutDir))

$taskInfos = @(Get-LatestTaskDirInfos -Serial $Serial -Package $Package)
$summary.Add(("TASK_DIR_COUNT={0}" -f $taskInfos.Count))
if ($taskInfos.Count -gt 0) {
  $totalTaskFiles = 0
  foreach ($taskInfo in $taskInfos) {
    $taskDirRel = "{0}/{1}" -f $taskInfo.BaseDir, $taskInfo.TaskDir
    $taskBaseName = $taskInfo.BaseDir -replace "[/\\]", "_"
    $taskLocalDir = Join-Path $taskOut ("{0}__{1}" -f $taskBaseName, $taskInfo.TaskDir)
    New-Item -ItemType Directory -Force -Path $taskLocalDir | Out-Null

    $summary.Add(("TASK_DIR={0}" -f $taskInfo.TaskDir))
    $summary.Add(("TASK_DIR_PATH={0}" -f $taskDirRel))

    $taskFiles = @(Get-RunAsList -Serial $Serial -Package $Package -ShellCommand ("find {0} -type f 2>/dev/null | sort" -f $taskDirRel) -AllowEmpty)
    $summary.Add(("TASK_FILE_COUNT[{0}]={1}" -f $taskDirRel, $taskFiles.Count))
    $totalTaskFiles += $taskFiles.Count

    foreach ($remote in $taskFiles) {
      $relativePath = $remote
      if ($remote.StartsWith($taskDirRel + "/")) {
        $relativePath = $remote.Substring($taskDirRel.Length + 1)
      }
      $local = Join-Path $taskLocalDir ($relativePath -replace "/", "\")
      Save-AdbRunAsFile -Serial $Serial -Package $Package -RemotePath $remote -LocalPath $local
    }
  }
  $summary.Add(("TASK_FILE_COUNT_TOTAL={0}" -f $totalTaskFiles))
} else {
  $summary.Add("TASK_DIR=")
  $summary.Add("TASK_FILE_COUNT_TOTAL=0")
}

if ($taskInfos.Count -eq 0 -or $totalTaskFiles -eq 0) {
  $artifactInfo = Get-RecentTaskArtifacts -Serial $Serial -Package $Package
  $artifactFiles = @($artifactInfo.Paths)
  $summary.Add(("TASK_ARTIFACT_DIR={0}" -f $artifactInfo.BaseDir))
  $summary.Add(("TASK_ARTIFACT_FILE_COUNT={0}" -f $artifactFiles.Count))

  if ($artifactFiles.Count -gt 0) {
    $artifactOut = Join-Path $taskOut "_artifacts"
    New-Item -ItemType Directory -Force -Path $artifactOut | Out-Null
    foreach ($remote in $artifactFiles) {
      $relativePath = $remote
      if ($artifactInfo.BaseDir -and $remote.StartsWith($artifactInfo.BaseDir + "/")) {
        $relativePath = $remote.Substring($artifactInfo.BaseDir.Length + 1)
      }
      $local = Join-Path $artifactOut ($relativePath -replace "/", "\")
      Save-AdbRunAsFile -Serial $Serial -Package $Package -RemotePath $remote -LocalPath $local
    }
  }
}

$kivyInfo = Get-KivyLogList -Serial $Serial -Package $Package -Count $KivyCount
$kivyList = @($kivyInfo.Paths)
$summary.Add(("KIVY_DIR={0}" -f $kivyInfo.BaseDir))
$summary.Add(("KIVY_FILE_COUNT={0}" -f $kivyList.Count))

foreach ($remotePath in $kivyList) {
  $name = [System.IO.Path]::GetFileName($remotePath)
  $local = Join-Path $kivyOut $name
  Save-AdbRunAsFile -Serial $Serial -Package $Package -RemotePath $remotePath -LocalPath $local
}

$summaryPath = Join-Path $OutDir "summary.txt"
[System.IO.File]::WriteAllLines($summaryPath, $summary, [System.Text.UTF8Encoding]::new($false))

$fileCount = (Get-ChildItem -Path $OutDir -Recurse -File | Measure-Object).Count
Write-Host ("TASK_DIR_COUNT={0}" -f $taskInfos.Count)
foreach ($taskInfo in $taskInfos) {
  Write-Host ("TASK_DIR={0}" -f $taskInfo.TaskDir)
  Write-Host ("TASK_DIR_PATH={0}" -f ("{0}/{1}" -f $taskInfo.BaseDir, $taskInfo.TaskDir))
}
Write-Host ("OUT_DIR={0}" -f $OutDir)
Write-Host ("KIVY_DIR={0}" -f $kivyInfo.BaseDir)
Write-Host ("KIVY_FILE_COUNT={0}" -f $kivyList.Count)
Write-Host ("FILE_COUNT={0}" -f $fileCount)
Get-ChildItem -Path $OutDir -Recurse -File |
  Sort-Object FullName |
  Select-Object FullName, Length, LastWriteTime |
  Format-Table -AutoSize
