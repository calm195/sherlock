"""验证昵称搜索的候选、平台限制和误报防护，不访问真实网络。"""

import json
from urllib.parse import parse_qs, unquote, urlsplit

import pytest
import requests

from sherlock_project.domestic.models import Status
from sherlock_project.domestic.search import search
from sherlock_project.domestic.transport import FetchError


class SearchClient:
    def __init__(self, payload=None, status=200, text=None, error=None):
        self.calls = []
        self.error = error
        self.response = requests.Response()
        self.response.status_code = status
        self.response.encoding = "utf-8"
        body = text if text is not None else json.dumps(payload, ensure_ascii=False)
        self.response._content = body.encode("utf-8")

    def get(self, url, *, platform):
        self.calls.append((url, platform))
        if self.error:
            raise self.error
        return self.response


def test_bilibili_search_extracts_encoded_query_and_candidates():
    client = SearchClient({"code": 0, "data": {"result": [
        {"mid": 2, "uname": '<em class="keyword">昵称</em>&amp;测试'},
        {"mid": "3", "uname": "相似昵称"},
    ]}})
    result = search("昵称 &/?中文", "B站", client)

    assert result.status is Status.FOUND
    assert result.platform == "bilibili"
    assert [profile.identifier for profile in result.profiles] == ["2", "3"]
    assert result.profiles[0].nickname == "昵称&测试"
    assert result.profiles[0].url == "https://space.bilibili.com/2"
    assert result.profiles[0].identifier_kind == "uid"
    assert "候选" in result.message
    assert "同一个人" in result.message
    assert len(client.calls) == 1
    request_url, platform = client.calls[0]
    assert platform == "bilibili"
    params = parse_qs(urlsplit(request_url).query)
    assert params == {"search_type": ["bili_user"], "keyword": ["昵称 &/?中文"], "page": ["1"]}
    assert parse_qs(urlsplit(result.search_url).query)["keyword"] == ["昵称 &/?中文"]


def test_bilibili_search_skips_invalid_rows_deduplicates_and_limits():
    client = SearchClient({"code": 0, "data": {"result": [
        None,
        {"mid": True, "uname": "布尔值不是账号 ID"},
        {"mid": "2/../../", "uname": "非法 ID"},
        {"mid": -1, "uname": "非法 ID"},
        {"mid": 3, "uname": " "},
        {"mid": 4, "uname": {"name": "对象不是昵称"}},
        {"mid": 5, "uname": "有效"},
        {"mid": "5", "uname": "重复"},
        {"mid": 6, "uname": "另一候选"},
        {"mid": 7, "uname": "超过上限"},
    ]}})
    result = search("用户", "bilibili", client, limit=2)
    assert result.status is Status.FOUND
    assert [profile.identifier for profile in result.profiles] == ["5", "6"]


def test_bilibili_search_empty_success_is_not_found():
    client = SearchClient({"code": 0, "data": {"result": []}})
    result = search("不存在的昵称", "bilibili", client)
    assert result.status is Status.NOT_FOUND
    assert result.profiles == []
    assert "不证明" in result.message


@pytest.mark.parametrize("payload", [
    None, [], {}, {"code": False}, {"code": "0"},
    {"code": 0}, {"code": 0, "data": None}, {"code": 0, "data": []},
    {"code": 0, "data": {}}, {"code": 0, "data": {"result": None}},
    {"code": 0, "data": {"result": {}}},
    {"code": 0, "data": {"result": [{"mid": 2}]}},
    {"code": -404, "message": "接口不存在"},
])
def test_bilibili_search_malformed_payload_is_not_an_absent_account(payload):
    result = search("用户", "bilibili", SearchClient(payload))
    assert result.status is Status.ERROR
    assert result.profiles == []


@pytest.mark.parametrize("status", [401, 403, 412, 429])
def test_search_http_restrictions(status):
    result = search("用户", "bilibili", SearchClient(status=status, text=""))
    assert result.status is Status.BLOCKED
    assert not result.profiles
    assert result.search_url


@pytest.mark.parametrize("code", [-101, -352, -403, -412, -509, 429])
def test_search_json_restrictions(code):
    result = search("用户", "bilibili", SearchClient({"code": code}))
    assert result.status is Status.BLOCKED
    assert not result.profiles


@pytest.mark.parametrize("body", [
    "<html><title>出错啦! - aba.bilibili.com</title></html>",
    "<html><title>验证码_哔哩哔哩</title></html>",
])
def test_search_http_200_challenge_is_blocked(body):
    result = search("用户", "bilibili", SearchClient(text=body))
    assert result.status is Status.BLOCKED
    assert not result.profiles


@pytest.mark.parametrize("status,body", [(200, "<html>网页外壳</html>"), (404, ""), (503, "")])
def test_search_unknown_page_and_http_errors_do_not_claim_absence(status, body):
    result = search("用户", "bilibili", SearchClient(status=status, text=body))
    assert result.status is Status.ERROR
    assert not result.profiles


def test_search_network_error_is_reported():
    result = search("用户", "bilibili", SearchClient(error=FetchError("请求超时")))
    assert result.status is Status.ERROR
    assert result.message == "请求超时"
    assert result.search_url


@pytest.mark.parametrize("platform,host,param", [
    ("小红书", "www.xiaohongshu.com", "keyword"),
    ("抖音", "www.douyin.com", None),
    ("快手", "www.kuaishou.com", "searchKey"),
])
def test_navigation_only_is_explicit_and_encodes_query(platform, host, param):
    client = SearchClient(error=AssertionError("入口导航不应该发送网络请求"))
    query = "昵称/?#&中文"
    result = search(query, platform, client)
    assert result.status is Status.UNSUPPORTED
    assert result.profiles == []
    assert "仅提供" in result.message
    assert not client.calls
    parts = urlsplit(result.search_url)
    assert parts.hostname == host
    assert not parts.fragment
    if param:
        assert parse_qs(parts.query)[param] == [query]
    else:
        assert unquote(parts.path.removeprefix("/search/")) == query
        assert parse_qs(parts.query) == {"type": ["user"]}


@pytest.mark.parametrize("platform", ["QQ", "微信"])
def test_private_messaging_nickname_search_has_no_invented_public_endpoint(platform):
    client = SearchClient(error=AssertionError("不得访问未适配的接口"))
    result = search("示例昵称", platform, client)
    assert result.status is Status.UNSUPPORTED
    assert result.search_url is None
    assert "客户端" in result.message
    assert not result.profiles
    assert not client.calls


@pytest.mark.parametrize("query,platform,limit", [
    ("", "bilibili", 5), ("  ", "bilibili", 5), ("\x1b[31m", "bilibili", 5),
    ("昵称", "不存在的平台", 5),
    ("昵称", "bilibili", 0), ("昵称", "bilibili", -1),
    ("昵称", "bilibili", 21), ("昵称", "bilibili", True),
])
def test_invalid_search_does_not_request(query, platform, limit):
    client = SearchClient(error=AssertionError("无效查询不应该访问网络"))
    result = search(query, platform, client, limit=limit)
    assert result.status is Status.INVALID
    assert not client.calls
