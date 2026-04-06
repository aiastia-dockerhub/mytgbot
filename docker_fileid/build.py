"""
Cython 编译脚本 - 将 main.py 编译为 .so 文件以保护源码
使用方法:
    1. 安装依赖: pip install cython
    2. 编译: python build.py build_ext --inplace
    3. 部署时只保留 .so 文件和 loader.py
"""
from Cython.Build import cythonize
from setuptools import setup, Extension
import os
import sys
import shutil

def build():
    """编译 main.py 为 .so 文件"""
    print("开始 Cython 编译...")

    setup(
        name='fileid_bot',
        ext_modules=cythonize(
            [Extension("main", ["main.py"])],
            compiler_directives={
                'language_level': "3",
                'embedsignature': True,
            }
        ),
    )

    # 清理临时文件
    for f in os.listdir('.'):
        if f.endswith('.c') and f != 'build.py':
            try:
                os.remove(f)
                print(f"已清理: {f}")
            except Exception:
                pass

    # 清理 build 目录
    if os.path.exists('build'):
        shutil.rmtree('build')
        print("已清理 build/ 目录")

    print("编译完成！")
    print("部署文件: main*.so + 创建 loader.py 启动")


if __name__ == '__main__':
    # 直接运行时执行编译
    if len(sys.argv) > 1:
        build()
    else:
        print("用法: python build.py build_ext --inplace")
        print("")
        print("编译后会生成 main.cpython-3xx-xxx.so 文件")
        print("然后创建 loader.py 来导入:")
        print('  from main import main')
        print('  if __name__ == "__main__":')
        print('      main()')