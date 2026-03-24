from os.path import join

from pythonforandroid.recipe import CompiledComponentsPythonRecipe


class PillowRecipe(CompiledComponentsPythonRecipe):
    version = '8.4.0'
    url = 'https://github.com/python-pillow/Pillow/archive/{version}.tar.gz'
    site_packages_name = 'Pillow'
    depends = ['png', 'jpeg', 'freetype', 'setuptools']
    opt_depends = ['libwebp']
    patches = [join('patches', 'fix-setup.patch')]

    call_hostpython_via_targetpython = False

    def get_recipe_env(self, arch=None, with_flags_in_cc=True):
        env = super().get_recipe_env(arch, with_flags_in_cc)
        env.pop("PYTHONNOUSERSITE", None)

        png = self.get_recipe('png', self.ctx)
        png_lib_dir = join(png.get_build_dir(arch.arch), '.libs')
        png_inc_dir = png.get_build_dir(arch)

        jpeg = self.get_recipe('jpeg', self.ctx)
        jpeg_inc_dir = jpeg_lib_dir = jpeg.get_build_dir(arch.arch)

        freetype = self.get_recipe('freetype', self.ctx)
        free_lib_dir = join(freetype.get_build_dir(arch.arch), 'objs', '.libs')
        free_inc_dir = join(freetype.get_build_dir(arch.arch), 'include')

        harfbuzz = self.get_recipe('harfbuzz', self.ctx)
        harf_lib_dir = join(harfbuzz.get_build_dir(arch.arch), 'src', '.libs')
        harf_inc_dir = harfbuzz.get_build_dir(arch.arch)

        build_with_webp_support = 'libwebp' in self.ctx.recipe_build_order
        if build_with_webp_support:
            webp = self.get_recipe('libwebp', self.ctx)
            webp_install = join(webp.get_build_dir(arch.arch), 'installation')

        cflags = f' -I{png_inc_dir}'
        cflags += f' -I{harf_inc_dir} -I{join(harf_inc_dir, "src")}'
        cflags += f' -I{free_inc_dir}'
        cflags += f' -I{jpeg_inc_dir}'
        if build_with_webp_support:
            cflags += f' -I{join(webp_install, "include")}'
        cflags += f' -I{self.ctx.ndk.sysroot_include_dir}'

        env['LIBS'] = ' -lpng -lfreetype -lharfbuzz -ljpeg -lturbojpeg -lz -lm'

        env['LDFLAGS'] += f' -L{png_lib_dir}'
        env['LDFLAGS'] += f' -L{free_lib_dir}'
        env['LDFLAGS'] += f' -L{harf_lib_dir}'
        env['LDFLAGS'] += f' -L{jpeg_lib_dir}'
        if build_with_webp_support:
            env['LDFLAGS'] += f' -L{join(webp_install, "lib")}'
        env['LDFLAGS'] += f' -L{arch.ndk_lib_dir_versioned}'

        if cflags not in env['CFLAGS']:
            env['CFLAGS'] += cflags + " -lm"
        return env


recipe = PillowRecipe()
