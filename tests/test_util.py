"""验证工具包拆分后的兼容入口、模板处理和并发请求行为。"""

from concurrent.futures import Future
from unittest.mock import Mock

import pytest
import requests

from sherlock_project import sherlock
from sherlock_project.util import cli, http, text, username


def test_legacy_imports_remain_available():
    """已有调用方仍可从 sherlock 模块导入工具。"""
    for module, names in (
        (cli, ("timeout_check", "handler")),
        (http, ("SherlockFuturesSession", "get_response")),
        (text, ("interpolate_string",)),
        (username, ("check_for_parameter", "multiple_usernames", "checksymbols")),
    ):
        for name in names:
            assert getattr(sherlock, name) is getattr(module, name)


def test_nested_request_template_preserves_input():
    template = {
        "query": ["用户 {}", {"{}": "https://example.com/{}"}],
        "page": 1,
        "enabled": True,
        "extra": None,
    }
    assert text.interpolate_string(template, "张三") == {
        "query": ["用户 张三", {"{}": "https://example.com/张三"}],
        "page": 1,
        "enabled": True,
        "extra": None,
    }
    assert template["query"] == ["用户 {}", {"{}": "https://example.com/{}"}]


@pytest.mark.parametrize("hook_kind", ["none", "missing", "empty", "single", "list", "tuple"])
def test_request_timing_precedes_existing_hooks(monkeypatch, hook_kind):
    """计时钩子应先于调用方钩子执行，并保留请求参数和 Future。"""
    ticks = iter([10.0, 10.25])
    monkeypatch.setattr(http, "monotonic", lambda: next(ticks))
    observed = []

    def existing_hook(response, **kwargs):
        observed.append(response.elapsed)

    hooks = {
        "none": None,
        "missing": {},
        "empty": {"response": []},
        "single": {"response": existing_hook},
        "list": {"response": [existing_hook]},
        "tuple": {"response": (existing_hook,)},
    }[hook_kind]
    future = Future()
    request = Mock(return_value=future)
    monkeypatch.setattr(http.FuturesSession, "request", request)
    with http.SherlockFuturesSession(max_workers=1) as session:
        assert session.request("GET", "https://example.com/", hooks=hooks, timeout=7) is future

    assert request.call_args.args == ("GET", "https://example.com/")
    assert request.call_args.kwargs["timeout"] == 7
    response = requests.Response()
    for hook in request.call_args.kwargs["hooks"]["response"]:
        hook(response)
    assert response.elapsed == 0.25
    assert observed == ([0.25] if hook_kind in {"single", "list", "tuple"} else [])


@pytest.mark.parametrize(("exception", "context"), [
    (requests.exceptions.HTTPError, "HTTP Error"),
    (requests.exceptions.ProxyError, "Proxy Error"),
    (requests.exceptions.ConnectionError, "Error Connecting"),
    (requests.exceptions.Timeout, "Timeout Error"),
    (requests.exceptions.RequestException, "Unknown Error"),
])
def test_request_errors_keep_their_classification(exception, context):
    future = Future()
    future.set_exception(exception("请求失败"))
    assert http.get_response(future, ["status_code"], "TestSite") == (None, context, "请求失败")


@pytest.mark.parametrize("status_code", [200, 404])
def test_response_status_is_left_for_site_rules(status_code):
    response = requests.Response()
    response.status_code = status_code
    future = Future()
    future.set_result(response)
    assert http.get_response(future, ["status_code"], "TestSite") == (response, None, None)
