# Quick Build Script for Testing
# Quick build script for background execution fix

param(
    [switch]$Clean,
    [switch]$Install,
    [string]$Serial = ""
)

$ErrorActionPreference = "Stop"

function Select-FirstAdbSerial {
    try {
        $lines = & adb.exe devices 2>&1
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

function Select-LatestApk {
    param([Parameter(Mandatory = $true)][string]$RepoRoot)

    $candidates = @(
        "sitoagent-*-arm64-v8a-debug.apk",
        "sitoagent-*-debug.apk",
        "sitoagent-*-arm64-v8a_armeabi-v7a-debug.apk",
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

Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "   Quick Build Script - Background Fix Version" -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host ""

# Check WSL availability
try {
    $wslVersion = wsl.exe --version 2>&1
    Write-Host "[OK] WSL is installed" -ForegroundColor Green
} catch {
    Write-Host "[ERROR] WSL is not installed, please install WSL first" -ForegroundColor Red
    exit 1
}

# Check buildozer
Write-Host ""
Write-Host "Checking buildozer..." -ForegroundColor Yellow
try {
    $buildozerCheck = wsl.exe -e bash -lc "which buildozer"
    Write-Host "[OK] buildozer is installed" -ForegroundColor Green
} catch {
    Write-Host "[WARN] buildozer not installed, installing..." -ForegroundColor Yellow
    wsl.exe -e bash -lc "pip install buildozer"
    Write-Host "[OK] buildozer installed" -ForegroundColor Green
}

# Clean build if requested
if ($Clean) {
    Write-Host ""
    Write-Host "Cleaning build directory..." -ForegroundColor Yellow
    wsl.exe -e bash -lc "rm -rf ~/mobile_build_workspace/.buildozer/android/platform/build-*/dists/orderquery && echo '[OK] Clean completed'"
    if ($LASTEXITCODE -ne 0) { throw "Clean failed in WSL (exit code: $LASTEXITCODE)" }
    if ($LASTEXITCODE -ne 0) { throw "Clean failed in WSL (exit code: $LASTEXITCODE)" }
}

# Build APK
Write-Host ""
Write-Host "Starting APK build..." -ForegroundColor Yellow
Write-Host "This may take several minutes, please be patient..." -ForegroundColor Gray
Write-Host ""

try {
    $repoRoot = $PSScriptRoot
    $repoRootWsl = (wsl.exe -e bash -lc "python3 - <<'PY'\nimport os\np=os.environ.get('WIN_PROJECT_DIR','')\nprint(p)\nPY" 2>$null)
    if (-not $repoRootWsl) {
        $drive = $repoRoot.Substring(0, 1).ToLowerInvariant()
        $rest = $repoRoot.Substring(2) -replace "\\", "/"
        if ($rest.StartsWith("/")) { $rest = $rest.Substring(1) }
        $repoRootWsl = "/mnt/$drive/$rest"
    }
    wsl.exe -e bash -lc "cd $repoRootWsl && ./build_apk.sh"
    if ($LASTEXITCODE -ne 0) { throw "WSL build failed (exit code: $LASTEXITCODE)" }
    Write-Host ""
    Write-Host "[OK] APK built successfully!" -ForegroundColor Green
    
    # List generated APKs
    Write-Host ""
    Write-Host "Generated APK files:" -ForegroundColor Cyan
    Get-ChildItem -Filter "sitoagent-*.apk" | Sort-Object LastWriteTime -Descending | Select-Object -First 5 | Format-Table Name, Length, LastWriteTime

    $selected = Select-LatestApk -RepoRoot $repoRoot
    if ($selected) {
        Write-Host ""
        Write-Host ("Selected APK: {0}" -f $selected.Name) -ForegroundColor Yellow
    }
    
} catch {
    Write-Host ""
    Write-Host "[ERROR] APK build failed" -ForegroundColor Red
    Write-Host "Error: $_" -ForegroundColor Red
    Write-Host ""
    Write-Host "Suggestions:" -ForegroundColor Yellow
    Write-Host "  1. Use -Clean parameter for clean build" -ForegroundColor Gray
    Write-Host "  2. Check network connection" -ForegroundColor Gray
    Write-Host "  3. See BUILD_INSTRUCTIONS.md for details" -ForegroundColor Gray
    exit 1
}

# Install if requested
if ($Install) {
    Write-Host ""
    if (-not $Serial) { $Serial = Select-FirstAdbSerial }
    if (-not $Serial) { throw "No adb device found. Connect a device or pass -Serial <device>" }
    Write-Host "Installing APK to device $Serial..." -ForegroundColor Yellow
    try {
        $apk = Select-LatestApk -RepoRoot $PSScriptRoot
        if (-not $apk) { throw "No APK found in repo root ($PSScriptRoot)" }
        $apkPath = $apk.FullName
        adb.exe -s $Serial install -r $apkPath
        Write-Host "[OK] APK installed to device $Serial" -ForegroundColor Green
    } catch {
        Write-Host "[ERROR] APK installation failed" -ForegroundColor Red
        Write-Host "Please ensure:" -ForegroundColor Yellow
        Write-Host "  1. Device $Serial is connected" -ForegroundColor Gray
        Write-Host "  2. USB debugging is enabled" -ForegroundColor Gray
        Write-Host "  3. adb server is running" -ForegroundColor Gray
        exit 1
    }
}

Write-Host ""
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "   Build completed!" -ForegroundColor Green
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "  1. If not installed: .\quick_build.ps1 -Install" -ForegroundColor Gray
Write-Host "  2. If build fails: .\quick_build.ps1 -Clean" -ForegroundColor Gray
Write-Host "  3. Or use full script: .\one_click_build_install.ps1 -Serial $Serial" -ForegroundColor Gray
Write-Host ""
