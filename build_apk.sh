#!/bin/bash
set -e

# 定义路径
# In some WSL setups, Windows may pass a Windows-style HOME into WSL (e.g. C:Users\name),
# which breaks paths. Prefer resolving the real Linux home via passwd/tilde expansion.
LINUX_HOME=""
if command -v getent >/dev/null 2>&1; then
    LINUX_HOME="$(getent passwd "$(id -un)" 2>/dev/null | cut -d: -f6)"
fi
if [ -z "$LINUX_HOME" ]; then
    LINUX_HOME="$(eval echo ~)"
fi
if [ -z "$LINUX_HOME" ]; then
    LINUX_HOME="."
fi
LINUX_BUILD_DIR="$LINUX_HOME/mobile_build_workspace"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WIN_PROJECT_DIR="${WIN_PROJECT_DIR:-$SCRIPT_DIR}"
if [ ! -d "$WIN_PROJECT_DIR" ]; then
    echo "Error: WIN_PROJECT_DIR not found: $WIN_PROJECT_DIR"
    exit 1
fi

# 清理 Windows 项目目录中的缓存
echo "清理缓存..."
find "$WIN_PROJECT_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$WIN_PROJECT_DIR" -type f -name "*.pyc" -delete 2>/dev/null || true
rm -f "$WIN_PROJECT_DIR"/*.apk
rm -rf "$WIN_PROJECT_DIR"/downloaded_snapshots/

echo "========================================================"
echo "   解决 WSL 权限问题：将项目复制到 Linux 本地环境构建"
echo "========================================================"

# 1. 创建并清理 Linux 构建目录
echo "[1/4] 准备构建环境..."
mkdir -p "$LINUX_BUILD_DIR"
# 同步代码（排除构建产物和隐藏文件，但保留必要的配置文件）
# 使用 rsync 可以增量同步，如果没安装则使用 cp
if command -v rsync >/dev/null 2>&1; then
    rsync -a --delete --info=progress2 --human-readable \
        --exclude '.buildozer' \
        --exclude 'bin' \
        --exclude 'downloaded_apk' \
        --exclude 'downloaded_tasks' \
        --exclude 'downloaded_images' \
        --exclude 'logs' \
        --exclude 'tasks' \
        --exclude '__pycache__' \
        --exclude '*.apk' \
        --exclude '*.log' \
        --exclude '*output*.png' \
        --exclude '.git' \
        "$WIN_PROJECT_DIR/" "$LINUX_BUILD_DIR/"
else
    echo "Warning: rsync not found, using cp (slower)..."
    cp -r "$WIN_PROJECT_DIR/"* "$LINUX_BUILD_DIR/"
fi
rm -rf "$LINUX_BUILD_DIR/.buildozer/android/platform/build-"*/dists/orderquery 2>/dev/null || true
rm -rf "$LINUX_BUILD_DIR/.buildozer/android/platform/build-"*/build/python-installs/orderquery 2>/dev/null || true

# 2. 设置环境变量
export _JAVA_OPTIONS="-Xmx4096m"
export PIP_BREAK_SYSTEM_PACKAGES=1
export PATH=$PATH:$HOME/.local/bin
# Force single-threaded build to avoid OOM/deadlock in WSL
export P4A_NUM_JOBS=1
export MAKEFLAGS="-j1"
# Disable Gradle daemon to prevent it from hanging or holding file locks
export GRADLE_OPTS="-Dorg.gradle.daemon=false"
export GIT_TERMINAL_PROMPT=0
export GIT_HTTP_LOW_SPEED_LIMIT=1000
export GIT_HTTP_LOW_SPEED_TIME=30

cleanup_gradle_locks() {
    local gradle_home=""
    local cleaned=0

    for gradle_home in "$HOME/.gradle" "$LINUX_BUILD_DIR/.gradle"; do
        [ -n "$gradle_home" ] || continue
        [ -d "$gradle_home" ] || continue

        if find "$gradle_home" -type f \( -name "*.lck" -o -name "*.lock" \) -print -delete 2>/dev/null | grep -q .; then
            cleaned=1
        fi
    done

    if [ "$cleaned" -eq 1 ]; then
        echo "Cleaned stale Gradle lock files."
    fi
}

GCC_MAJOR=""
if command -v gcc >/dev/null 2>&1; then
    GCC_MAJOR="$(gcc -dumpversion 2>/dev/null | cut -d. -f1 || true)"
fi

if command -v gcc-12 >/dev/null 2>&1; then
    export CC="gcc-12"
    export CXX="g++-12"
elif command -v gcc-11 >/dev/null 2>&1; then
    export CC="gcc-11"
    export CXX="g++-11"
elif command -v clang >/dev/null 2>&1; then
    export CC="clang"
    export CXX="clang++"
elif [ -n "$GCC_MAJOR" ] && [ "$GCC_MAJOR" -ge 13 ] 2>/dev/null; then
    echo "❌ 检测到宿主 gcc=$GCC_MAJOR，但未安装 gcc-12/gcc-11/clang。"
    echo "   这会导致 python-for-android 构建 hostpython3 时出现随机崩溃/Segmentation fault。"
    echo "   请在 WSL 安装其一后重试："
    echo "     sudo apt update && sudo apt install -y gcc-12 g++-12"
    echo "   或："
    echo "     sudo apt update && sudo apt install -y clang"
    exit 1
fi

export CFLAGS="${CFLAGS:--O1} -g0"
export CXXFLAGS="${CXXFLAGS:--O1} -g0"

# Copy AndroidManifest.xml if it exists
if [ -f "$WIN_PROJECT_DIR/AndroidManifest.xml" ]; then
    cp "$WIN_PROJECT_DIR/AndroidManifest.xml" "$LINUX_BUILD_DIR/"
    echo "Copied AndroidManifest.xml"
else
    echo "Warning: AndroidManifest.xml not found, will use buildozer.spec configuration"
fi

# buildozer.spec should already be copied by rsync, but verify it exists
if [ ! -f "$LINUX_BUILD_DIR/buildozer.spec" ]; then
    echo "Error: buildozer.spec not found in build directory"
    exit 1
fi
echo "Using buildozer.spec for configuration"

ensure_pillow_cached() {
    local platform_dir=""
    platform_dir="$(ls -d "$LINUX_BUILD_DIR/.buildozer/android/platform/build-"* 2>/dev/null | head -n 1 || true)"
    if [ -z "$platform_dir" ]; then
        return 0
    fi

    local build_root="$platform_dir/packages/Pillow"
    local tarball="$build_root/8.4.0.tar.gz"
    local mark="$build_root/.mark-8.4.0.tar.gz"

    mkdir -p "$build_root"

    if [ -f "$mark" ] && [ ! -f "$tarball" ]; then
        rm -f "$mark"
    fi

    if [ -f "$tarball" ]; then
        if tar -tzf "$tarball" >/dev/null 2>&1; then
            touch "$mark"
            return 0
        fi
        rm -f "$tarball" "$mark"
    fi

    local urls=(
        "https://files.pythonhosted.org/packages/source/P/Pillow/Pillow-8.4.0.tar.gz"
        "https://codeload.github.com/python-pillow/Pillow/tar.gz/8.4.0"
        "https://github.com/python-pillow/Pillow/archive/8.4.0.tar.gz"
    )

    for url in "${urls[@]}"; do
        echo "Prefetching Pillow source: $url"
        if command -v wget >/dev/null 2>&1; then
            rm -f "$tarball"
            if wget --tries=5 --timeout=30 --continue -O "$tarball" "$url"; then
                if tar -tzf "$tarball" >/dev/null 2>&1; then
                    touch "$mark"
                    return 0
                fi
            fi
        elif command -v curl >/dev/null 2>&1; then
            rm -f "$tarball"
            if curl -L --retry 5 --retry-delay 3 --connect-timeout 30 -o "$tarball" "$url"; then
                if tar -tzf "$tarball" >/dev/null 2>&1; then
                    touch "$mark"
                    return 0
                fi
            fi
        fi
        rm -f "$tarball" "$mark"
    done

    echo "❌ Pillow 预下载失败"
    return 1
}

ensure_python3_cached() {
    local version="3.11.5"
    local platform_dir=""
    platform_dir="$(ls -d "$LINUX_BUILD_DIR/.buildozer/android/platform/build-"* 2>/dev/null | head -n 1 || true)"
    if [ -z "$platform_dir" ]; then
        return 0
    fi

    local build_root="$platform_dir/packages/python3"
    local tarball="$build_root/Python-$version.tgz"
    local mark="$build_root/.mark-Python-$version.tgz"

    mkdir -p "$build_root"

    if [ -f "$mark" ] && [ ! -f "$tarball" ]; then
        rm -f "$mark"
    fi

    if [ -f "$tarball" ]; then
        if tar -tzf "$tarball" >/dev/null 2>&1; then
            touch "$mark"
            return 0
        fi
        rm -f "$tarball" "$mark"
    fi

    local url="https://www.python.org/ftp/python/$version/Python-$version.tgz"
    echo "Prefetching python3 source: $url"
    if command -v wget >/dev/null 2>&1; then
        rm -f "$tarball"
        if wget --tries=5 --timeout=30 --continue -O "$tarball" "$url"; then
            if tar -tzf "$tarball" >/dev/null 2>&1; then
                touch "$mark"
                return 0
            fi
        fi
    elif command -v curl >/dev/null 2>&1; then
        rm -f "$tarball"
        if curl -L --retry 5 --retry-delay 3 --connect-timeout 30 -o "$tarball" "$url"; then
            if tar -tzf "$tarball" >/dev/null 2>&1; then
                touch "$mark"
                return 0
            fi
        fi
    fi

    rm -f "$tarball" "$mark"
    echo "❌ python3 源码预下载失败: $url"
    return 1
}

ensure_gradle_wrapper_cached() {
    local gradle_version="8.0.2"
    local gradle_dist="gradle-${gradle_version}-all"
    local gradle_zip="${gradle_dist}.zip"
    local gradle_url="https://services.gradle.org/distributions/${gradle_zip}"
    local gradle_hash_dir="14bt34ptcsg1ikmfn78tdh1keu"
    local primary_dir="$HOME/.gradle/wrapper/dists/${gradle_dist}/${gradle_hash_dir}"
    local mirror_dir="$LINUX_BUILD_DIR/.gradle/wrapper/dists/${gradle_dist}/${gradle_hash_dir}"
    local primary_zip="$primary_dir/$gradle_zip"
    local mirror_zip="$mirror_dir/$gradle_zip"

    is_valid_gradle_zip() {
        local zip_path="$1"
        [ -f "$zip_path" ] || return 1
        python3 - "$zip_path" <<'PY'
import sys
import zipfile

path = sys.argv[1]
try:
    with zipfile.ZipFile(path) as zf:
        bad = zf.testzip()
        sys.exit(0 if bad is None else 1)
except Exception:
    sys.exit(1)
PY
    }

    mkdir -p "$primary_dir" "$mirror_dir"

    if is_valid_gradle_zip "$primary_zip"; then
        if ! is_valid_gradle_zip "$mirror_zip"; then
            cp -f "$primary_zip" "$mirror_zip" 2>/dev/null || true
        fi
        return 0
    fi

    rm -f "$primary_zip" "$primary_zip.part"
    echo "Prefetching Gradle wrapper distribution: $gradle_url"
    if command -v wget >/dev/null 2>&1; then
        wget --tries=5 --timeout=30 --continue -O "$primary_zip.part" "$gradle_url" || true
    elif command -v curl >/dev/null 2>&1; then
        curl -L --retry 5 --retry-delay 3 --connect-timeout 30 -o "$primary_zip.part" "$gradle_url" || true
    else
        echo "Warning: wget/curl not found, Gradle wrapper will download on demand."
        return 0
    fi

    if is_valid_gradle_zip "$primary_zip.part"; then
        mv -f "$primary_zip.part" "$primary_zip"
        cp -f "$primary_zip" "$mirror_zip" 2>/dev/null || true
        return 0
    fi

    rm -f "$primary_zip.part" "$primary_zip" "$mirror_zip"
    echo "Warning: Gradle wrapper prefetch failed, falling back to gradlew download."
    return 0
}

# 3. 进入 Linux 目录执行打包
echo "[2/4] 开始 Buildozer 打包..."
cd "$LINUX_BUILD_DIR"
BIN_DIR="$LINUX_BUILD_DIR/bin"
mkdir -p "$BIN_DIR"
rm -f "$BIN_DIR"/*.apk 2>/dev/null || true
echo "Using buildozer.spec android.archs: $(grep -E '^android\.archs\s*=' -m1 buildozer.spec || true)"
echo "Using CC=${CC:-gcc} CFLAGS=${CFLAGS:-} P4A_NUM_JOBS=${P4A_NUM_JOBS:-} MAKEFLAGS=${MAKEFLAGS:-}"
cleanup_gradle_locks
ensure_gradle_wrapper_cached || true
ensure_pillow_cached || true
ensure_python3_cached || true
# rm -rf "$LINUX_BUILD_DIR/.buildozer/android/platform/build-arm64-v8a_armeabi-v7a" 2>/dev/null || true
HOSTPY_DIR=""
PLATFORM_DIR="$(ls -d "$LINUX_BUILD_DIR/.buildozer/android/platform/build-"* 2>/dev/null | head -n 1 || true)"
if [ -n "$PLATFORM_DIR" ]; then
    HOSTPY_DIR="$PLATFORM_DIR/build/other_builds/hostpython3"
fi
# if [ -d "$HOSTPY_DIR" ]; then
#     rm -rf "$HOSTPY_DIR" || true
# fi
PILLOW_DIR=""
if [ -n "$PLATFORM_DIR" ]; then
    PILLOW_DIR="$PLATFORM_DIR/build/other_builds/Pillow"
fi
# if [ -d "$PILLOW_DIR" ]; then
#     rm -rf "$PILLOW_DIR" || true
# fi
CRYPTOGRAPHY_DIR=""
if [ -n "$PLATFORM_DIR" ]; then
    CRYPTOGRAPHY_DIR="$PLATFORM_DIR/build/other_builds/cryptography"
fi
# if [ -d "$CRYPTOGRAPHY_DIR" ]; then
#     rm -rf "$CRYPTOGRAPHY_DIR" || true
# fi
max_attempts=3
attempt=1
while [ $attempt -le $max_attempts ]; do
    echo "Build attempt $attempt/$max_attempts ..."
    build_log="$LINUX_BUILD_DIR/buildozer_build_attempt_${attempt}.log"
    rm -f "$build_log" 2>/dev/null || true

    set +e
    success_detected=0
    (
        set -o pipefail
        if command -v stdbuf >/dev/null 2>&1 && [ -t 1 ] && [ -t 2 ]; then
            # Pipe 'yes' to handle any interactive prompts (licenses, etc)
            stdbuf -oL -eL buildozer android debug 2>&1 | tee "$build_log"
        else
            buildozer android debug 2>&1 | tee "$build_log"
        fi
    ) &
    build_pid=$!

    while kill -0 "$build_pid" 2>/dev/null; do
        sleep 5
        # echo "[heartbeat] $(date '+%Y-%m-%d %H:%M:%S') buildozer running (pid=$build_pid)"
        # ps -eo pid,etimes,pcpu,cmd | egrep 'buildozer|pythonforandroid|download.sh|git clone' | egrep -v 'egrep|grep -E' | head -n 20 || true
        if [ -f "$build_log" ]; then
            # Check for success message in log (handle binary/color codes)
            if grep -a -q "APK .* available in the bin directory" "$build_log"; then
                 echo "✅ Build success detected in logs!"
                 success_detected=1
                 sleep 1
                 if kill -0 "$build_pid" 2>/dev/null; then
                     echo "Force killing buildozer process..."
                     kill -9 "$build_pid" 2>/dev/null || true
                 fi
                 break
            fi
            # Also check for "packaging done" as alternative
            if grep -a -q "# Android packaging done!" "$build_log"; then
                 echo "✅ Build success detected (packaging done)!"
                 success_detected=1
                 sleep 1
                 if kill -0 "$build_pid" 2>/dev/null; then
                     echo "Force killing buildozer process..."
                     kill -9 "$build_pid" 2>/dev/null || true
                 fi
                 break
            fi
        fi
    done

    wait "$build_pid"
    build_rc=$?
    # If we manually detected success, override rc
    if [ $success_detected -eq 1 ]; then
        build_rc=0
    fi
    set -e

    if [ $build_rc -eq 0 ]; then
        break
    fi
    if [ $attempt -lt $max_attempts ]; then
        sleep_sec=$((attempt * 20))
        echo "Build failed (exit=$build_rc). Retrying in ${sleep_sec}s..."
        if [ -d "$HOSTPY_DIR" ]; then
            rm -rf "$HOSTPY_DIR" || true
        fi
        # Try cleaning more if first attempt fails
        if [ $attempt -eq 1 ]; then
            echo "First attempt failed. Cleaning up locks and partial builds..."
            find "$LINUX_BUILD_DIR/.buildozer" -name "*.lock" -delete 2>/dev/null || true
            cleanup_gradle_locks
            rm -rf "$LINUX_BUILD_DIR/.buildozer/android/platform/build-arm64-v8a_armeabi-v7a/dists" 2>/dev/null || true
        fi
        sleep "$sleep_sec"
    fi
    attempt=$((attempt + 1))
done
if [ $attempt -gt $max_attempts ]; then
    echo "❌ Buildozer 多次重试仍失败"
    echo "建议："
    echo "  1) 确认 buildozer.spec 已使用 python3==3.11.x（不能只写 3.11，否则下载 404）"
    echo "  2) 清理 WSL 缓存后重试：rm -rf ~/mobile_build_workspace/.buildozer/android/platform/build-arm64-v8a_armeabi-v7a/build/other_builds/hostpython3"
    if [ -f "$LINUX_BUILD_DIR/buildozer_build_attempt_${max_attempts}.log" ]; then
        echo "  3) 查看最后一次构建日志：tail -n 200 $LINUX_BUILD_DIR/buildozer_build_attempt_${max_attempts}.log"
    fi
    exit 1
fi

# 4. 将 APK 复制回 Windows 目录
echo "[3/4] 构建完成，复制 APK..."
if [ -d "$BIN_DIR" ]; then
    rm -f "$WIN_PROJECT_DIR"/orderquery-*.apk 2>/dev/null || true
    cp "$BIN_DIR"/*.apk "$WIN_PROJECT_DIR/"
    echo "✅ APK 已成功复制到: $WIN_PROJECT_DIR"
    ls -lh "$WIN_PROJECT_DIR"/*.apk
else
    echo "❌ 未找到生成的 APK 文件！"
    exit 1
fi

echo "========================================================"
echo "   全部完成！"
echo "========================================================"
