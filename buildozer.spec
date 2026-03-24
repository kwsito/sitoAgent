[app]

# (str) Title of your application
title = Order Query

# (str) Package name
package.name = orderquery

# (str) Package domain (needed for android/ios packaging)
package.domain = org.test

# (str) Source files where the main.py lives
source.dir = .

# (list) Source files to include (let empty to include all the files)
source.include_exts = py,png,jpg,kv,atlas,json,yaml

# (list) List of inclusions using pattern matching
#source.include_patterns = assets/*,images/*.png

# (list) Source files to exclude
#source.exclude_exts = spec,pyc

# (str) Application versioning (method 1)
version = 2026.2.26
android.numeric_version = 2026022601

# (list) Application requirements
# comma separated e.g. requirements = sqlite3,kivy
requirements = python3==3.11.5,kivy,pillow,requests,urllib3,charset_normalizer,idna,certifi,pyyaml,pyjnius,setuptools,wheel,adb-shell,cryptography,pyasn1,rsa,libffi

# (str) Presplash of the application
#presplash.filename = %(source.dir)s/data/presplash.png

# (str) Icon of the application
#icon.filename = %(source.dir)s/data/icon.png

# (str) Supported orientation (one of 'landscape', 'portrait' or 'sensor')
orientation = portrait

# (list) List of service to declare
#services = myservice:name=org.myapp.ServiceMyService:start=service:foreground=true

services = orderqueryservice:service.py

# (bool) Indicate if the application should be fullscreen or not
fullscreen = 0

#
# Android specific
#

# (list) Permissions
android.permissions = INTERNET,ACCESS_NETWORK_STATE,WAKE_LOCK,FOREGROUND_SERVICE,POST_NOTIFICATIONS,REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,RECORD_AUDIO

# (int) Target Android API, should be as high as possible.
android.api = 33

# (int) Minimum API your APK will support.
android.minapi = 21

# (int) Android NDK version to use
android.ndk = 25b

# (int) Android SDK version to use
android.sdk = 33

# (str) Android NDK directory (if empty, it will be automatically downloaded.)
#android.ndk_path =

# (str) Android SDK directory (if empty, it will be automatically downloaded.)
#android.sdk_path =

# (str) ANT directory (if empty, it will be automatically downloaded.)
#android.ant_path =

# (bool) If True, then skip trying to update the Android sdk
# This can be useful to avoid excess Internet downloads or save time
# when an update is due and you just want to test/build your package
android.skip_update = False

# (bool) If True, then automatically accept SDK license
# agreements. This is intended for automated build environments.
android.accept_sdk_license = True

# (str) Android entry point, default is ok for Kivy-based app
android.entrypoint = org.kivy.android.PythonActivity

# (str) Android apptheme, is available only when starting as a new project
# android.apptheme = AppTheme

# (list) Pattern to whitelist for the whole project
android.whitelist =

# (str) Path to a custom whitelist file
android.whitelist_src =

# (str) Path to a custom blacklist file
android.blacklist_src =

# (list) List of Java .jar files to add to the libs so that pyjnius can access
# their classes. Don't add jars that you do not need, since extra jars can slow
# down the build process. Allows wildcards matching, for example:
# OUYA-ODK/libs/*.jar
android.add_jars = libs/vosk-android.jar,libs/jna-5.13.0.jar

# (list) List of Java files to add to the android project (can be java or a
# directory containing the files)
android.add_src =

# (list) Android AAR archives to add (optional)
android.add_aars =
android.add_assets = assets/model:model

# (list) Android additional libraries to copy into libs/arm64-v8a
android.add_libs_arm64_v8a = libs/arm64-v8a/libvosk.so,libs/arm64-v8a/libjnidispatch.so

# (list) Gradle dependencies to add (currently for supporting AndroidX + viewbinding)
android.gradle_dependencies =

# (list) add java compile options
# this can for example be necessary when importing certain java libraries using the 'android.gradle_dependencies' option
# see https://developer.android.com/studio/write/java8-support for further information
# generally:
# android.add_compile_options = "sourceCompatibility = 1.8", "targetCompatibility = 1.8"
android.add_compile_options =

# (list) Gradle repositories to add {can be necessary for some android.gradle_dependencies}
# please enclose in double quotes if it contains spaces: "repo like 'name'"
android.gradle_repositories =

# (list) packaging options to add
# see https://developer.android.com/studio/build/build-configuration
android.packaging_options =

# (list) Python include libs to copy into the apk, in case your pyjnius setup
# needs some libs that aren't in the default path
android.python_libs =

# (str) python-for-android branch to use, defaults to master
p4a.branch = master

# (str) Use local recipe overrides (to fix hostpython setuptools for Pillow builds)
p4a.local_recipes = p4a_recipes

# (str) python-for-android specific commits to use, requires p4a.branch
# commit to use, must be within p4a.branch
# p4a.commit =

# (str) python-for-android fork to use
#p4a.fork =

# (int) python-for-android bootstrap to use, options: sdl2, webview, service_only
# (str) python-for-android android archs to build
android.archs = arm64-v8a

# (bool) enables python3 support
python.use_python3 = True

# (int) Android NDK API level to build with, default is 0 (auto)
#android.ndk_api =

# (bool) If True, enables AOT (Ahead-Of-Time) compilation for Python
#android.aot =

# (bool) Enable LTO (Link Time Optimization)
#android.lto =

# (bool) If True, then use private libs (not from python-for-android)
#android.private_libs =

# (str) Python for-android url to use for building android
# (bool) Undocumented but works: p4a builds the APK
#p4a.url =

# (str) Android logcat filters to use
android.logcat_filters = *:S python:D

# (bool) Copy python libs instead of using pyjnius injector
# This allows for cleaner builds and better compatibility
android.copy_libs = 1

# (str) The Android arch to build for, choices: armeabi-v7a, arm64-v8a, x86, x86_64
#android.arch = arm64-v8a

# (bool) enables Android auto backup feature (Android API 23+)
android.allow_backup = True

# (str) The format used to package the android app
android.package_format = apk

# (str) The filename of the APK to be built
android.filename = orderquery-{version.suffix}

# (str) The name of the signing key (None for debug)
android.signing_keys =

# (str) Path to keystore
#android.keystore =

# (str) Key alias
#android.keyalias =

# (str) Key password
#android.keypassword =

# (str) Signing algorithm to use (default SHA1withRSA)
android.sign_algorithm = SHA256withRSA

# (bool) Whether to copy the Android manifest from the template or use the
# one in the source directory
#android.copy_manifest = 1

# (str) Launcher activity class name
#android.launcher_activity =

# (str) Android launcher name
android.launcher_name = OrderQuery

# (str) Android launcher icon
#android.launcher_icon =

# (str) Android prebuilt ldr
#android.prebuilt_ldr =

# (str) Android prebuilt libloda
#android.prebuilt_libloda =

# (str) Android prebuilt libpython
#android.prebuilt_libpython =

# (str) Android prebuilt libsqlite
#android.prebuilt_libsqlite =

# (str) Android prebuilt libssl
#android.prebuilt_libssl =

# (str) Android prebuilt libcrypto
#android.prebuilt_libcrypto =

# (str) Android prebuilt libffi
#android.prebuilt_libffi =

# (str) Android prebuilt libexpat
#android.prebuilt_libexpat =

# (str) Android prebuilt libpng
#android.prebuilt_libpng =

# (str) Android prebuilt libjpeg
#android.prebuilt_libjpeg =

# (str) Android prebuilt libtiff
#android.prebuilt_libtiff =

# (str) Android prebuilt libwebp
#android.prebuilt_libwebp =

# (str) Android prebuilt libiconv
#android.prebuilt_libprebuilt_iconv =

# (str) Android prebuilt libintl
#android.prebuilt_libintl =

# (str) Android prebuilt libxml2
#android.prebuilt_libxml2 =

# (str) Android prebuilt libxslt
#android.prebuilt_libxslt =

# (str) Android prebuilt liblzma
#android.prebuilt_liblzma =

# (str) Android prebuilt libz
#android.prebuilt_libz =

# (str) Android prebuilt libbz2
#android.prebuilt_libbz2 =

# (str) Android prebuilt libcurl
#android.prebuilt_libcurl =

# (str) Android prebuilt libssl
#android.prebuilt_libssl_prebuilt =

# (str) Android prebuilt libcrypto
#android.prebuilt_libcrypto_prebuilt =

# (str) Android prebuilt libffi
#android.prebuilt_libffi_prebuilt =

# (str) Android prebuilt libsqlite
#android.prebuilt_libsqlite_prebuilt =

# (str) Android prebuilt libexpat
#android.prebuilt_libexpat_prebuilt =

# (str) Android prebuilt libpng
#android.prebuilt_libpng_prebuilt =

# (str) Android prebuilt libjpeg
#android.prebuilt_libjpeg_prebuilt =

# (str) Android prebuilt libtiff
#android.prebuilt_libtiff_prebuilt =

# (str) Android prebuilt libwebp
#android.prebuilt_libwebp_prebuilt =

# (str) Android prebuilt libiconv
#android.prebuilt_libiconv_prebuilt =

# (str) Android prebuilt libintl
#android.prebuilt_libintl_prebuilt =

# (str) Android prebuilt libxml2
#android.prebuilt_libxml2_prebuilt =

# (str) Android prebuilt libxslt
#android.prebuilt_libxslt_prebuilt =

# (str) Android prebuilt liblzma
#android.prebuilt_liblzma_prebuilt =

# (str) Android prebuilt libz
#android.prebuilt_libz_prebuilt =

# (str) Android prebuilt libbz2
#android.prebuilt_libbz2_prebuilt =

# (str) Android prebuilt libcurl
#android.prebuilt_libcurl_prebuilt =

source.exclude_exts = spec,pyc,log,txt,md,bat,ps1,sh
source.exclude_dirs = __pycache__,logs,downloaded_snapshots,bin,.buildozer,.git
source.exclude_patterns = test_*.py,token.json,executed_*.json,*.apk

[buildozer]
log_level = 2
