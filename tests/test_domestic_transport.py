"""验证短链不会绕过域名限制，以及网络失败和响应资源边界。"""

from io import BytesIO
from unittest.mock import Mock

import pytest
import requests

from sherlock_project.domestic.transport import Client, FetchError, validate_url


def response(url, body=b"{}", status=200, headers=None):
    result = requests.Response()
    result.status_code = status
    result.url = url
    result.headers.update(headers or {})
    result.raw = BytesIO(body)
    return result


@pytest.mark.parametrize("url", [
    "https://127.0.0.1/private", "https://localhost/private", "file:///etc/passwd",
    "https://www.bilibili.com.evil.example/", "https://evil.bilibili.com/",
    "https://user:secret@space.bilibili.com/2", "https://space.bilibili.com:8080/2",
    "https://space.bilibili.com:bad/2", "https://space.bilibili.com\\@evil.example/2",
    "https://space.bilibili.com/\n2", "https://www.douyin.com/user/test",
])
def test_rejects_urls_outside_platform(url):
    with Client() as client:
        client.session.get = Mock()
        with pytest.raises(FetchError):
            client.get(url, platform="bilibili")
        client.session.get.assert_not_called()


def test_upgrades_http_and_removes_fragment():
    assert validate_url("http://space.bilibili.com:80/2#video", "bilibili") == "https://space.bilibili.com/2"


@pytest.mark.parametrize("target", ["http://127.0.0.1/secret", "//www.douyin.com/user/test"])
def test_redirect_checked_before_request(target):
    first = response("https://b23.tv/abc", status=302, headers={"Location": target})
    with Client() as client:
        client.session.get = Mock(return_value=first)
        with pytest.raises(FetchError):
            client.get(first.url, platform="bilibili")
        assert client.session.get.call_count == 1
        assert first.raw.closed


def test_relative_redirect_and_response_remain_readable():
    first = response("https://space.bilibili.com/2", status=302, headers={"Location": "/3"})
    final = response("https://space.bilibili.com/3", '{"昵称":"测试"}'.encode())
    with Client(timeout=7, proxy="http://127.0.0.1:8080") as client:
        client.session.get = Mock(side_effect=[first, final])
        actual = client.get(first.url, platform="bilibili")
        assert actual.json() == {"昵称": "测试"}
        call = client.session.get.call_args
        assert call.args == ("https://space.bilibili.com/3",)
        assert call.kwargs["allow_redirects"] is False
        assert call.kwargs["timeout"] == 7
        assert call.kwargs["proxies"]["https"] == "http://127.0.0.1:8080"
        assert first.raw.closed
        assert actual.content == '{"昵称":"测试"}'.encode()


def test_redirect_loop_is_bounded():
    with Client() as client:
        client.session.get = Mock(side_effect=lambda url, **kwargs: response(
            url, status=302, headers={"Location": url},
        ))
        with pytest.raises(FetchError, match="次数过多"):
            client.get("https://b23.tv/abc", platform="bilibili")
        assert client.session.get.call_count == client.MAX_REDIRECTS + 1


def test_oversized_body_closed():
    oversized = response("https://space.bilibili.com/2", b"12345")
    with Client() as client:
        client.MAX_BYTES = 4
        client.session.get = Mock(return_value=oversized)
        with pytest.raises(FetchError, match="过大"):
            client.get(oversized.url, platform="bilibili")
        assert oversized.raw.closed


def test_timeout_is_fetch_error():
    with Client() as client:
        client.session.get = Mock(side_effect=requests.Timeout("timeout"))
        with pytest.raises(FetchError, match="网络请求失败"):
            client.get("https://b23.tv/abc", platform="bilibili")
