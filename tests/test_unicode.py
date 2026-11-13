"""测试包含特殊字符或 Unicode 字符的用户名处理逻辑。"""

from concurrent.futures import Future

from sherlock_project.sherlock import get_response


def _make_future_with_exception(exc):
    """创建一个在获取结果时抛出指定异常的 Future。"""
    future = Future()
    future.set_exception(exc)
    return future


def test_get_response_handles_unicode_decode_error():
    """Issue #2730 的回归测试。

    包含特殊字符的用户名（如 "Émile"）可能导致 requests 库
    在处理重定向时抛出 UnicodeDecodeError，程序应处理该异常而非崩溃。
    """
    future = _make_future_with_exception(
        UnicodeDecodeError("utf-8", b"\xe9", 0, 1, "invalid continuation byte")
    )
    response, error_context, exception_text = get_response(
        request_future=future,
        error_type=["status_code"],
        social_network="TestSite",
    )
    assert response is None
    assert error_context == "Encoding Error"
    assert "utf-8" in exception_text


def test_get_response_handles_unicode_encode_error():
    """同样应捕获 UnicodeError 的子类 UnicodeEncodeError。"""
    future = _make_future_with_exception(
        UnicodeEncodeError("ascii", "É", 0, 1, "ordinal not in range(128)")
    )
    response, error_context, exception_text = get_response(
        request_future=future,
        error_type=["status_code"],
        social_network="TestSite",
    )
    assert response is None
    assert error_context == "Encoding Error"
    assert "ascii" in exception_text
