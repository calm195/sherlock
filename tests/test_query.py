"""使用替代网络响应验证查询引擎拆分后的判定与请求编排。"""

from concurrent.futures import Future
from unittest.mock import Mock

import pytest
import requests

from sherlock_project import query
from sherlock_project.result import QueryStatus


def response(body="公开主页", status=200):
    result = requests.Response()
    result.status_code = status
    result._content = body.encode("utf-8")
    result.encoding = "utf-8"
    result.elapsed = 0.25
    return result


def site(**rules):
    return {
        "urlMain": "https://example.com",
        "url": "https://example.com/users/{}",
        "errorType": "status_code",
        **rules,
    }


@pytest.fixture
def network(monkeypatch):
    """只记录请求与收集顺序，所有响应都由测试预先指定。"""
    session = Mock()
    replies = []
    events = []

    class RecordedFuture(Future):
        def result(self, timeout=None):
            events.append("collect")
            return super().result(timeout=timeout)

    def request(method, **kwargs):
        events.append((method, kwargs))
        future = RecordedFuture()
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            future.set_exception(reply)
        else:
            future.set_result(reply)
        return future

    for method in ("get", "head", "post", "put"):
        getattr(session, method).side_effect = lambda method=method, **kwargs: request(method, **kwargs)
    factory = Mock(return_value=session)
    monkeypatch.setattr(query, "SherlockFuturesSession", factory)
    monkeypatch.setattr(query.requests, "session", Mock())
    return replies, events, factory


@pytest.mark.parametrize(("rules", "body", "http_status", "expected"), [
    ({}, "主页", 200, QueryStatus.CLAIMED),
    ({}, "缺失", 404, QueryStatus.AVAILABLE),
    ({"errorCode": 204}, "", 204, QueryStatus.AVAILABLE),
    ({"errorCode": [201, 204]}, "", 204, QueryStatus.AVAILABLE),
    ({"errorType": "message", "errorMsg": "不存在"}, "用户不存在", 200, QueryStatus.AVAILABLE),
    ({"errorType": "message", "errorMsg": ["不存在", "已注销"]}, "用户已注销", 200, QueryStatus.AVAILABLE),
    ({"errorType": "message", "errorMsg": "不存在"}, "主页", 200, QueryStatus.CLAIMED),
    ({"errorType": "response_url"}, "", 200, QueryStatus.CLAIMED),
    ({"errorType": "response_url"}, "", 302, QueryStatus.AVAILABLE),
    ({"errorType": ["message", "status_code"], "errorMsg": "缺失"}, "缺失", 200, QueryStatus.AVAILABLE),
    ({"errorType": ["message", "status_code"], "errorMsg": "缺失"}, "主页", 404, QueryStatus.AVAILABLE),
    ({"errorType": ["message", "response_url"], "errorMsg": "缺失"}, "缺失", 200, QueryStatus.AVAILABLE),
    ({}, '<span id="challenge-error-text">', 403, QueryStatus.WAF),
    ({"errorType": "unknown"}, "主页", 200, QueryStatus.UNKNOWN),
])
def test_site_verdicts_preserve_existing_rules(network, rules, body, http_status, expected):
    replies, _, _ = network
    replies.append(response(body, http_status))
    notify = Mock()
    actual = query.sherlock("昵称", {"TestSite": site(**rules)}, notify)["TestSite"]
    assert actual["status"].status is expected
    assert actual["status"].query_time == 0.25
    assert actual["http_status"] == http_status
    assert actual["response_text"] == body.encode("utf-8")
    assert actual["url_main"] == "https://example.com"
    assert actual["url_user"] == "https://example.com/users/昵称"
    notify.start.assert_called_once_with("昵称")
    notify.update.assert_called_once_with(actual["status"])
    if expected is QueryStatus.UNKNOWN:
        assert actual["status"].context == "Unknown error type '['unknown']' for TestSite"


def test_all_requests_are_submitted_before_collecting(network):
    replies, events, factory = network
    replies.extend([response(), response()])
    sites = {"First": site(), "Second": site(errorType="response_url")}
    actual = query.sherlock("test", sites, Mock())
    assert list(actual) == ["First", "Second"]
    assert [event[0] if isinstance(event, tuple) else event for event in events] == [
        "head", "get", "collect", "collect",
    ]
    assert events[0][1]["allow_redirects"] is True
    assert events[1][1]["allow_redirects"] is False
    assert factory.call_args.kwargs["max_workers"] == 2
    assert all(isinstance(info["request_future"], Future) for info in sites.values())


@pytest.mark.parametrize("method", ["GET", "HEAD", "POST", "PUT"])
def test_custom_requests_keep_payload_headers_proxy_and_timeout(network, method):
    replies, events, _ = network
    replies.append(response())
    data = site(
        errorType="message", errorMsg="缺失", request_method=method,
        headers={"User-Agent": "custom", "Accept": "application/json"},
        urlProbe="https://example.com/api/{}",
        request_payload={"users": ["{}"], "page": 1},
    )
    actual = query.sherlock("张 三", {"TestSite": data}, Mock(), proxy="socks5://localhost:1080", timeout=3.5)
    assert events[0] == (method.lower(), {
        "url": "https://example.com/api/张 三",
        "headers": {"User-Agent": "custom", "Accept": "application/json"},
        "allow_redirects": True,
        "timeout": 3.5,
        "json": {"users": ["张 三"], "page": 1},
        "proxies": {"http": "socks5://localhost:1080", "https": "socks5://localhost:1080"},
    })
    assert actual["TestSite"]["url_user"] == "https://example.com/users/张%20三"
    assert data["request_payload"] == {"users": ["{}"], "page": 1}


def test_default_request_does_not_add_proxy_option(network):
    replies, events, _ = network
    replies.append(response())
    query.sherlock("test", {"TestSite": site()}, Mock())
    assert "proxies" not in events[0][1]
    assert events[0][1]["timeout"] == 60


def test_illegal_username_is_reported_without_request(network):
    _, events, _ = network
    notify = Mock()
    actual = query.sherlock("姓名", {"TestSite": site(regexCheck=r"^[a-z]+$")}, notify)["TestSite"]
    assert not events
    assert actual["status"].status is QueryStatus.ILLEGAL
    assert actual["url_user"] == actual["http_status"] == actual["response_text"] == ""
    notify.update.assert_called_once_with(actual["status"])


def test_failed_request_keeps_unknown_status_and_debug_output(network, capsys):
    replies, _, _ = network
    replies.append(requests.Timeout("timeout"))
    actual = query.sherlock("test", {"TestSite": site()}, Mock(), dump_response=True)["TestSite"]
    assert actual["status"].status is QueryStatus.UNKNOWN
    assert actual["status"].context == "Timeout Error"
    assert actual["status"].query_time is None
    assert actual["http_status"] == "?"
    assert actual["response_text"] == ""
    output = capsys.readouterr().out
    assert "TARGET NAME   : TestSite" in output
    assert "VERDICT       : Unknown" in output


def test_successful_response_debug_output(network, capsys):
    replies, _, _ = network
    replies.append(response("调试内容"))
    query.sherlock("test", {"TestSite": site(errorCode=404)}, Mock(), dump_response=True)
    output = capsys.readouterr().out
    assert "STATUS CODES  : 404" in output
    assert "RESPONSE CODE : 200" in output
    assert ">>>>> BEGIN RESPONSE TEXT\n调试内容\n<<<<< END RESPONSE TEXT" in output


def test_unsupported_request_method_still_fails(network):
    with pytest.raises(RuntimeError, match="Unsupported request_method"):
        query.sherlock("test", {"TestSite": site(request_method="DELETE")}, Mock())


def test_worker_count_remains_bounded(network):
    replies, _, factory = network
    replies.extend(response() for _ in range(25))
    query.sherlock("test", {f"Site{i}": site() for i in range(25)}, Mock())
    assert factory.call_args.kwargs["max_workers"] == 20
