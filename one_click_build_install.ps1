param(
  [string]$Serial = "",
  [string]$ApkPath,
  [switch]$SkipClean,
  [switch]$ForceUninstall,
  [switch]$SkipInstall
)



$ErrorActionPreference = "Stop"

function Convert-ToWslPath {
  param([Parameter(Mandatory = $true)][string]$WindowsPath)
  $full = [System.IO.Path]::GetFullPath($WindowsPath)
  $drive = $full.Substring(0, 1).ToLowerInvariant()
  $rest = $full.Substring(2) -replace "\\", "/"
  if ($rest.StartsWith("/")) { $rest = $rest.Substring(1) }
  return "/mnt/$drive/$rest"
}

function Invoke-Checked {
  param(
    [Parameter(Mandatory = $true)][string]$FilePath,
    [Parameter()][string[]]$Arguments = @(),
    [Parameter()][string]$StepName = $FilePath
  )

  Write-Host "==> $StepName"
  Write-Host ("    {0} {1}" -f $FilePath, ($Arguments -join " "))
  & $FilePath @Arguments
  $exitCode = $LASTEXITCODE
  if ($exitCode -ne 0) {
    throw "Step failed ($StepName), exit code: $exitCode"
  }
}

function Select-LatestApk {
  param([Parameter(Mandatory = $true)][string]$RepoRoot)

  $candidates = @(
    "orderquery-*-arm64-v8a-debug.apk",
    "orderquery-*-debug.apk",
    "orderquery-*-arm64-v8a_armeabi-v7a-debug.apk"
  )

  foreach ($pat in $candidates) {
    $hit = Get-ChildItem -Path $RepoRoot -Filter $pat -ErrorAction SilentlyContinue |
      Sort-Object LastWriteTime -Descending |
      Select-Object -First 1
    if ($hit) { return $hit }
  }
  return $null
}

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

$repoRoot = $PSScriptRoot
$repoRootWsl = Convert-ToWslPath $repoRoot

if (-not $SkipClean) {
  Invoke-Checked -FilePath "wsl.exe" -Arguments @(
    "-e", "bash", "-lc",
    'rm -rf ~/mobile_build_workspace/.buildozer/android/platform/build-*/dists/orderquery && echo "dist removed"'
  ) -StepName "Clean dist (WSL)"
} else {
  Write-Host "==> Clean dist (WSL) skipped"
}

Invoke-Checked -FilePath "wsl.exe" -Arguments @(
  "-e", "bash", "-lc",
  ("cd {0} && ./build_apk.sh" -f $repoRootWsl)
) -StepName "Build APK (WSL)"

if (-not $ApkPath) {
  $latestApk = Select-LatestApk -RepoRoot $repoRoot
  if (-not $latestApk) {
    throw "No APK found in $repoRoot"
  }
  $ApkPath = $latestApk.FullName
  Write-Host "Auto-selected APK: $ApkPath"
}

if (-not (Test-Path -LiteralPath $ApkPath)) {
  throw "APK not found: $ApkPath"
}

if ((-not $SkipInstall) -or $ForceUninstall) {
  if (-not $Serial) {
    $Serial = Select-FirstAdbSerial
  }
  if (-not $Serial) {
    throw "No adb device found. Connect a device or pass -Serial <device>"
  }
}

if ($ForceUninstall) {
  Write-Host "==> Uninstall existing app (adb)"
  Write-Host "    adb -s $Serial uninstall org.test.orderquery"
  & adb -s $Serial uninstall org.test.orderquery 2>$null
  if ($LASTEXITCODE -eq 0) {
    Write-Host "    Uninstall successful"
  } else {
    Write-Host "    App not installed or uninstall failed (continuing...)"
  }
}

if ($SkipInstall) {
  Write-Host "==> Install APK (adb) skipped"
  Write-Host "    APK: $ApkPath"
  exit 0
}

Write-Host "==> Install APK (adb)"
Write-Host ("    adb -s {0} install -r -g {1}" -f $Serial, $ApkPath)
$installOut = & adb -s $Serial install -r -g $ApkPath 2>&1
$exitCode = $LASTEXITCODE
if ($installOut) { $installOut | ForEach-Object { Write-Host $_ } }
if ($exitCode -ne 0) {
  $outText = ($installOut | Out-String)
  if ($outText -match "INSTALL_FAILED_ABORTED: User rejected permissions") {
    Write-Host ""
    Write-Host "[Hint] The device rejected USB/ADB install permissions, so installation was aborted."
    Write-Host "Please allow the required permissions on the phone and try again:"
    Write-Host "  1) Open Developer options -> enable USB debugging"
    Write-Host "  2) Open Developer options -> enable Install via USB (name may vary by device)"
    Write-Host "  3) Replug the USB cable and choose Allow / Always allow on the phone"
    Write-Host ""
    Write-Host "Then run again:"
    Write-Host ("  .\one_click_build_install.ps1 -Serial {0} -SkipClean" -f $Serial)
    throw "Install aborted by device permission prompt"
  }
  throw "Step failed (Install APK (adb)), exit code: $exitCode"
}

Write-Host "==> Done"
