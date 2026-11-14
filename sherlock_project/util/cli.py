"""命令行参数校验与退出处理。"""

import math
import sys
from argparse import ArgumentTypeError


def timeout_check(value):
    """将超时参数转换为有限的正浮点数，单位为秒。"""
    float_value = float(value)

    if not math.isfinite(float_value) or float_value <= 0:
        raise ArgumentTypeError(
            f"Invalid timeout value: {value}. Timeout must be a positive number."
        )

    return float_value


def handler(signal_received, frame):
    """正常退出程序，避免输出异常堆栈。

    参考来源：https://www.devdungeon.com/content/python-catch-sigint-ctrl-c
    """
    sys.exit(0)
