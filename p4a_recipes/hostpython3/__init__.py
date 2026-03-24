import os
from multiprocessing import cpu_count
from pathlib import Path
from os.path import join
import shutil
import glob

import sh

from pythonforandroid.logger import shprint, info, warning
from pythonforandroid.recipe import Recipe
from pythonforandroid.util import (
    BuildInterruptingException,
    current_directory,
    ensure_dir,
)
from pythonforandroid.prerequisites import OpenSSLPrerequisite

HOSTPYTHON_VERSION_UNSET_MESSAGE = (
    'The hostpython recipe must have set version'
)

SETUP_DIST_NOT_FIND_MESSAGE = (
    'Could not find Setup.dist or Setup in Python build'
)


class HostPython3Recipe(Recipe):
    version = '3.11.5'
    name = 'hostpython3'

    build_subdir = 'native-build'

    url = 'https://www.python.org/ftp/python/{version}/Python-{version}.tgz'

    patches = ['patches/pyconfig_detection.patch']

    @property
    def _exe_name(self):
        if not self.version:
            raise BuildInterruptingException(HOSTPYTHON_VERSION_UNSET_MESSAGE)
        return f'python{self.version.split(".")[0]}'

    @property
    def python_exe(self):
        return join(self.get_path_to_python(), self._exe_name)

    def get_recipe_env(self, arch=None):
        env = os.environ.copy()
        openssl_prereq = OpenSSLPrerequisite()
        if env.get("PKG_CONFIG_PATH", ""):
            env["PKG_CONFIG_PATH"] = os.pathsep.join(
                [openssl_prereq.pkg_config_location, env["PKG_CONFIG_PATH"]]
            )
        else:
            env["PKG_CONFIG_PATH"] = openssl_prereq.pkg_config_location
        return env

    def should_build(self, arch):
        if Path(self.python_exe).exists():
            try:
                self._ensure_setuptools_available(self.get_recipe_env(arch))
            except Exception:
                raise
            self.ctx.hostpython = self.python_exe
            return False
        return True

    def get_build_container_dir(self, arch=None):
        choices = self.check_recipe_choices()
        dir_name = '-'.join([self.name] + choices)
        return join(self.ctx.build_dir, 'other_builds', dir_name, 'desktop')

    def get_build_dir(self, arch=None):
        return join(self.get_build_container_dir(), self.name)

    def get_path_to_python(self):
        return join(self.get_build_dir(), self.build_subdir)

    def _ensure_setuptools_available(self, env):
        py = self.python_exe
        if not Path(py).exists():
            raise BuildInterruptingException("hostpython executable not found")

        try:
            shprint(sh.Command(py), "-c", "import setuptools; import wheel; import pkg_resources", _env=env)
            return
        except Exception:
            pass

        build_lib_candidates = glob.glob(join(self.get_path_to_python(), "build", "lib.*"))
        build_lib_dir = build_lib_candidates[0] if build_lib_candidates else None
        if not build_lib_dir:
            raise BuildInterruptingException("hostpython build/lib.* not found for --target install")

        try:
            ensure_dir(build_lib_dir)
        except Exception:
            pass

        env_boot = dict(env or {})
        env_boot.pop("PYTHONNOUSERSITE", None)
        env_boot["PYTHONNOUSERSITE"] = "0"

        last_err = None
        try:
            info("Bootstrapping pip into hostpython via ensurepip...")
            shprint(sh.Command(py), "-m", "ensurepip", "--upgrade", _env=env_boot)
            shprint(sh.Command(py), "-m", "pip", "--version", _env=env_boot)
        except Exception as e:
            last_err = e

        if last_err is not None:
            try:
                cache_dir = join(self.get_build_dir(), "bootstrap")
                ensure_dir(cache_dir)
                get_pip = join(cache_dir, "get-pip.py")
                url = "https://bootstrap.pypa.io/get-pip.py"
                if (not Path(get_pip).exists()) or (Path(get_pip).stat().st_size < 1024):
                    if shutil.which("curl"):
                        shprint(sh.Command("curl"), "-L", "--retry", "5", "--retry-delay", "3", "-o", get_pip, url, _env=env_boot)
                    elif shutil.which("wget"):
                        shprint(sh.Command("wget"), "--tries=5", "--timeout=30", "-O", get_pip, url, _env=env_boot)
                    else:
                        raise BuildInterruptingException("curl/wget not available to fetch get-pip.py")
                info("Bootstrapping pip into hostpython via get-pip.py...")
                shprint(sh.Command(py), get_pip, _env=env_boot)
                shprint(sh.Command(py), "-m", "pip", "--version", _env=env_boot)
                last_err = None
            except Exception as e:
                last_err = e

        if last_err is not None:
            raise BuildInterruptingException(f"Failed to bootstrap pip in hostpython: {last_err}")

        try:
            info(f"Installing setuptools/wheel into hostpython build dir: {build_lib_dir}")
            shprint(
                sh.Command(py),
                "-m",
                "pip",
                "install",
                "--target",
                build_lib_dir,
                "setuptools==68.1.2",
                "wheel",
                _env=env_boot,
            )
        except Exception as e:
            raise BuildInterruptingException(f"pip install setuptools/wheel failed for hostpython: {e}")

        try:
            env_verify = dict(env or {})
            env_verify["PYTHONNOUSERSITE"] = "1"
            shprint(sh.Command(py), "-c", "import setuptools; import wheel; import pkg_resources", _env=env_verify)
        except Exception as e:
            raise BuildInterruptingException(f"hostpython still missing setuptools after install: {e}")

    def build_arch(self, arch):
        env = self.get_recipe_env(arch)

        recipe_build_dir = self.get_build_dir(arch.arch)
        build_dir = join(recipe_build_dir, self.build_subdir)
        ensure_dir(build_dir)
        prefix_dir = join(recipe_build_dir, "prefix")
        ensure_dir(prefix_dir)

        with current_directory(build_dir):
            if not Path('config.status').exists():
                shprint(
                    sh.Command(join(recipe_build_dir, 'configure')),
                    f"--prefix={prefix_dir}",
                    "--with-ensurepip=install",
                    _env=env,
                )

        with current_directory(recipe_build_dir):
            setup_dist_location = join('Modules', 'Setup.dist')
            if Path(setup_dist_location).exists():
                shprint(sh.cp, setup_dist_location, join(build_dir, 'Modules', 'Setup'))
            else:
                setup_location = join('Modules', 'Setup')
                if not Path(setup_location).exists():
                    raise BuildInterruptingException(SETUP_DIST_NOT_FIND_MESSAGE)

            shprint(sh.make, '-j', str(cpu_count()), '-C', build_dir, _env=env)

            for exe_name in ['python.exe', 'python']:
                exe = join(self.get_path_to_python(), exe_name)
                if Path(exe).is_file():
                    shprint(sh.cp, exe, self.python_exe)
                    break

        self._ensure_setuptools_available(env)
        self.ctx.hostpython = self.python_exe


recipe = HostPython3Recipe()
