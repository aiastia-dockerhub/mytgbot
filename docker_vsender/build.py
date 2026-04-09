"""
Cython 编译脚本
将 .py 文件编译为 .so 共享库，保护源代码
"""
import os
import glob
from Cython.Build import cythonize
from setuptools import setup, Extension

# 入口文件和构建脚本不编译
EXCLUDE_FILES = {"main.py", "build.py"}


def get_extensions():
    """收集需要编译的 .py 文件"""
    extensions = []
    for py_file in glob.glob("*.py"):
        if py_file not in EXCLUDE_FILES:
            module_name = py_file.replace(".py", "")
            extensions.append(Extension(module_name, [py_file]))
    return extensions


setup(
    name="vsender_bot",
    ext_modules=cythonize(
        get_extensions(),
        compiler_directives={
            'language_level': "3",
            'boundscheck': False,
            'wraparound': False,
        },
        build_dir="build_temp",
    ),
)