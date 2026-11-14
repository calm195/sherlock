"""Sherlock 兼容入口；命令行、流程编排和站点查询由各自模块实现。"""

import sys

try:
    from sherlock_project import import_error_test_var  # noqa: F401
except ImportError:
    print("Did you run Sherlock with `python3 sherlock/sherlock.py ...`?")
    print("This is an outdated method. Please see https://sherlockproject.xyz/installation for up to date instructions.")
    sys.exit(1)

import requests

from sherlock_project.cli import main
from sherlock_project.notify import QueryNotify, QueryNotifyPrint
from sherlock_project.query import sherlock
from sherlock_project.result import QueryResult, QueryStatus
from sherlock_project.sites import SitesInformation
from sherlock_project.util.cli import handler, timeout_check
from sherlock_project.util.http import SherlockFuturesSession, get_response
from sherlock_project.util.text import interpolate_string
from sherlock_project.util.username import (
    check_for_parameter,
    checksymbols,
    multiple_usernames,
)

# 保留历史导入入口；新代码直接从对应业务模块或 util 子模块导入。
__all__ = [
    "QueryNotify",
    "QueryNotifyPrint",
    "QueryResult",
    "QueryStatus",
    "SherlockFuturesSession",
    "SitesInformation",
    "check_for_parameter",
    "checksymbols",
    "get_response",
    "handler",
    "interpolate_string",
    "main",
    "multiple_usernames",
    "requests",
    "sherlock",
    "timeout_check",
]


if __name__ == "__main__":
    main()
