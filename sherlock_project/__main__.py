#! /usr/bin/env python3

"""Sherlock 模块运行入口。

检查 Python 版本后，启动跨社交网络的用户名查询。
"""

import sys


if __name__ == "__main__":
    # 检查用户使用的 Python 版本是否受支持。
    python_version = sys.version.split()[0]

    if sys.version_info < (3, 9):
        print(f"Sherlock requires Python 3.9+\nYou are using Python {python_version}, which is not supported by Sherlock.")
        sys.exit(1)

    from sherlock_project import sherlock
    sherlock.main()
