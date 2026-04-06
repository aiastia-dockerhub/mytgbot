"""
Cython 编译脚本
将 .py 文件编译为 .so 共享库，保护源代码
"""
import os
import sys
import glob
from Cython.Build import cythonize
from setuptools import setup, Extension

# 需要编译的包/模块
COMPILE_PACKAGES = ["modules"]
# 入口文件不编译（main.py 保持 .py）
ENTRY_FILE = "main.py"


def get_extensions():
    """收集需要编译的 .py 文件"""
    extensions = []

    for package in COMPILE_PACKAGES:
        py_files = glob.glob(os.path.join(package, "*.py"))
        for py_file in py_files:
            # __init__.py 也编译
            module_name = py_file.replace("/", ".").replace("\\", ".").replace(".py", "")
            extensions.append(
                Extension(module_name, [py_file])
            )

    # config.py 也编译
    if os.path.exists("config.py"):
        extensions.append(Extension("config", ["config.py"]))

    return extensions


setup(
    name="javbus_bot",
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