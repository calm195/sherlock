"""使用构造响应验证解析边界；不把模拟成功当作线上接口可用的证明。"""

import json

import pytest
import requests

from sherlock_project.domestic.models import Status
from sherlock_project.domestic.resolve import resolve
from sherlock_project.domestic.transport import FetchError

XHS_ID = "5c6a0c1b0000000011000cb1"
SEC_UID = "MS4wLjABAAAAexample_123456"
BIZ = "MzA0MDAwMDAwMA=="


def response(text="", *, payload=None, status=200, url=""):
    result = requests.Response()
    result.status_code = status
    result.url = url
    result.encoding = "utf-8"
    result._content = (json.dumps(payload) if payload is not None else text).encode()
    return result


class FakeClient:
    def __init__(self, *responses, error=None):
        self.responses = list(responses)
        self.calls = []
        self.error = error

    def get(self, url, *, platform):
        self.calls.append((url, platform))
        if self.error:
            raise self.error
        assert self.responses, f"出现未预期的网络请求：{url}"
        result = self.responses.pop(0)
        if not result.url:
            result.url = url
        return result


@pytest.mark.parametrize("value,platform,identifier,url", [
    (XHS_ID, "小红书", XHS_ID, f"https://www.xiaohongshu.com/user/profile/{XHS_ID}"),
    (f"https://www.xiaohongshu.com/user/profile/{XHS_ID.upper()}?xsec_token=example", None, XHS_ID, f"https://www.xiaohongshu.com/user/profile/{XHS_ID}"),
    (SEC_UID, "抖音", SEC_UID, f"https://www.douyin.com/user/{SEC_UID}"),
    (f"https://www.iesdouyin.com/share/user/123456?sec_uid={SEC_UID}", None, SEC_UID, f"https://www.douyin.com/user/{SEC_UID}"),
    ("kuaishou:123456", None, "123456", "https://www.kuaishou.com/profile/123456"),
    ("3xabcdefghijklm", "快手", "3xabcdefghijklm", "https://www.kuaishou.com/profile/3xabcdefghijklm"),
    ("https://www.kuaishou.com/profile/anotherid?shareObjectId=9999", None, "anotherid", "https://www.kuaishou.com/profile/anotherid"),
])
def test_profiles_are_resolved_without_claiming_existence(value, platform, identifier, url):
    client = FakeClient(response("<title>平台首页</title><button>登录</button>"))
    result = resolve(value, platform, client)
    assert result.status is Status.RESOLVED
    assert result.profiles[0].identifier == identifier
    assert result.profiles[0].url == url
    assert result.profiles[0].nickname is None
    assert len(client.calls) == 1


@pytest.mark.parametrize("value", [
    "qq:10000", "https://user.qzone.qq.com/10000", "user.qzone.qq.com/10000/",
    "https://wpa.qq.com/msgrd?v=3&uin=10000&site=qq&menu=yes",
])
def test_qq_resolution_does_not_probe_avatar_or_claim_account_exists(value):
    client = FakeClient()
    result = resolve(value, None, client)
    assert result.status is Status.RESOLVED
    assert result.profiles[0].identifier == "10000"
    assert result.profiles[0].identifier_kind == "qq"
    assert client.calls == []


@pytest.mark.parametrize("value", [
    "bilibili:2", "https://space.bilibili.com/2", "https://m.bilibili.com/space/2/",
    "看看我的主页 https://space.bilibili.com/2/video?share_mid=999。",
])
def test_bilibili_found_requires_matching_api_account(value):
    client = FakeClient(response(payload={"code": 0, "data": {"card": {"mid": "2", "name": "示例账号"}}}))
    result = resolve(value, None, client)
    assert result.status is Status.FOUND
    assert result.profiles[0].identifier == "2"
    assert result.profiles[0].nickname == "示例账号"
    assert client.calls == [("https://api.bilibili.com/x/web-interface/card?mid=2", "bilibili")]


@pytest.mark.parametrize("payload,expected", [
    ({"code": -352}, Status.BLOCKED),
    ({"code": -101}, Status.BLOCKED),
    ({"code": -404, "message": "用户不存在"}, Status.NOT_FOUND),
    ({"code": -404}, Status.RESOLVED),
    ({"code": 0, "data": {"card": {"mid": "3", "name": "错误账号"}}}, Status.ERROR),
    ({"code": 0, "data": {"card": {"mid": "2"}}}, Status.RESOLVED),
    ({"code": 0, "data": []}, Status.RESOLVED),
    ({"code": False, "data": {"card": {"mid": "2", "name": "错误响应"}}}, Status.RESOLVED),
    ({"code": {}}, Status.RESOLVED),
    ({"code": []}, Status.RESOLVED),
    ([], Status.RESOLVED),
])
def test_bilibili_handles_risk_control_missing_and_malformed_data(payload, expected):
    result = resolve("2", "bilibili", FakeClient(response(payload=payload)))
    assert result.status is expected
    assert result.profiles[0].identifier == "2"


@pytest.mark.parametrize("value,platform", [
    ("", None), ("123456", None), ("qq:10000", "bilibili"),
    ("https://space.bilibili.com/2", "qq"),
    ("https://space.bilibili.com.evil.example/2", None),
    ("https://space.bilibili.com@evil.example/2", None),
    ("https://user:password@space.bilibili.com/2", None),
    ("https://space.bilibili.com:444/2", None),
    ("https://space.bilibili.com/2\x00", None),
    ("file://space.bilibili.com/2", None),
    ("https://space.bilibili.com/2 https://space.bilibili.com/3", None),
    ("2", "不存在的平台"),
])
def test_invalid_inputs_are_rejected_before_network(value, platform):
    client = FakeClient()
    assert resolve(value, platform, client).status is Status.INVALID
    assert client.calls == []


@pytest.mark.parametrize("value,platform", [
    ("账号昵称", "bilibili"), ("１２３４５６", "bilibili"),
    ("123456", "xiaohongshu"), ("some_red_id", "xiaohongshu"),
    ("123456", "douyin"), ("some_douyin_id", "douyin"),
    ("快手昵称", "kuaishou"), ("some_kuaishou_id", "kuaishou"),
    ("1234", "qq"), ("0123456", "qq"),
    ("https://www.bilibili.com/video/BVexample?share_mid=2", None),
    (f"https://www.xiaohongshu.com/explore/{XHS_ID}?userId={XHS_ID}", None),
    (f"https://www.douyin.com/video/123456?sec_uid={SEC_UID}", None),
    ("https://www.kuaishou.com/short-video/abc?userId=123456", None),
])
def test_handles_and_content_links_are_not_mistaken_for_profile_identifiers(value, platform):
    client = FakeClient()
    result = resolve(value, platform, client)
    assert result.status is Status.UNSUPPORTED
    assert result.profiles == []
    assert client.calls == []


@pytest.mark.parametrize("status", [401, 403, 412, 418, 429, 451, 521])
def test_blocked_pages_keep_resolved_identifiers(status):
    result = resolve(XHS_ID, "xiaohongshu", FakeClient(response(status=status)))
    assert result.status is Status.BLOCKED
    assert result.profiles[0].identifier == XHS_ID


@pytest.mark.parametrize("page", [
    response(url="https://www.xiaohongshu.com/login"),
    response("<title>安全验证</title>"),
])
def test_login_and_challenge_pages_are_not_found(page):
    result = resolve(XHS_ID, "xiaohongshu", FakeClient(page))
    assert result.status is Status.BLOCKED


@pytest.mark.parametrize("status", [200, 404, 410])
def test_empty_or_missing_pages_do_not_prove_account_existence(status):
    result = resolve(SEC_UID, "douyin", FakeClient(response(status=status)))
    assert result.status is Status.RESOLVED


def test_profile_short_link_is_followed_once_and_normalized():
    client = FakeClient(response(url=f"https://www.xiaohongshu.com/user/profile/{XHS_ID}?source=share"))
    result = resolve("分享主页 http://xhslink.com/a/example。", None, client)
    assert result.status is Status.RESOLVED
    assert result.profiles[0].identifier == XHS_ID
    assert len(client.calls) == 1


def test_short_link_to_content_does_not_attribute_the_sharer_as_author():
    client = FakeClient(response(url="https://www.bilibili.com/video/BVexample?share_mid=2"))
    result = resolve("https://b23.tv/example", None, client)
    assert result.status is Status.UNSUPPORTED
    assert result.profiles == []
    assert len(client.calls) == 1


def test_cross_platform_short_link_is_not_accepted():
    client = FakeClient(response(url="https://user.qzone.qq.com/10000"))
    assert resolve("https://b23.tv/example", None, client).status is Status.ERROR


def test_bilibili_short_link_can_verify_final_uid():
    client = FakeClient(
        response(url="https://space.bilibili.com/2"),
        response(payload={"code": 0, "data": {"card": {"mid": 2, "name": "示例账号"}}}),
    )
    result = resolve("https://b23.tv/example", None, client)
    assert result.status is Status.FOUND
    assert result.profiles[0].identifier == "2"
    assert len(client.calls) == 2


def test_failed_request_keeps_resolved_identifier():
    result = resolve("2", "bilibili", FakeClient(error=FetchError("连接超时")))
    assert result.status is Status.ERROR
    assert result.profiles[0].identifier == "2"


@pytest.mark.parametrize("value", ["微信昵称", "wxid_example", "wechat_handle"])
def test_wechat_personal_account_lookup_is_explicitly_unsupported(value):
    client = FakeClient()
    assert resolve(value, "微信", client).status is Status.UNSUPPORTED
    assert client.calls == []


def test_wechat_profile_biz_is_not_proof_of_existence():
    client = FakeClient()
    result = resolve(f"https://mp.weixin.qq.com/mp/profile_ext?action=home&__biz={BIZ}", None, client)
    assert result.status is Status.RESOLVED
    assert result.profiles[0].identifier == BIZ
    assert client.calls == []


def test_wechat_article_author_fixture():
    # 该构造样本只验证字段识别，不表示已在线验证公众号页面可访问。
    page = f'''<script>var biz = "{BIZ}";</script>
        <a id="js_name"> 示例 &amp; 公众号 </a>
        <div id="js_content">正文中的另一个名字</div>'''
    result = resolve("https://mp.weixin.qq.com/s/article_example", None, FakeClient(response(page)))
    assert result.status is Status.FOUND
    assert result.profiles[0].identifier_kind == "biz"
    assert result.profiles[0].identifier == BIZ
    assert result.profiles[0].nickname == "示例 & 公众号"


def test_wechat_script_nickname_decodes_unicode_without_running_javascript():
    page = f'''<script>var biz = '{BIZ}'; var nickname = htmlDecode("\\u6d4b\\u8bd5");</script>
        <div id="js_content">正文</div>'''
    result = resolve("https://mp.weixin.qq.com/s/article_example", None, FakeClient(response(page)))
    assert result.status is Status.FOUND
    assert result.profiles[0].nickname == "测试"


def test_wechat_query_biz_and_generic_page_are_not_found():
    result = resolve(f"https://mp.weixin.qq.com/s?__biz={BIZ}", None, FakeClient(response("<title>微信公众平台</title>")))
    assert result.status is Status.RESOLVED
    assert result.profiles[0].identifier == BIZ


def test_wechat_query_biz_mismatch_is_an_error():
    page = f'<script>var biz = "{BIZ}";</script><a id="js_name">示例</a><div id="js_content"></div>'
    result = resolve("https://mp.weixin.qq.com/s?__biz=MzAwMTIzNDU2Nw==", None, FakeClient(response(page)))
    assert result.status is Status.ERROR


def test_wechat_body_text_is_not_an_author_variable():
    page = f'<a id="js_name">示例</a><div id="js_content">var biz = "{BIZ}";</div>'
    result = resolve("https://mp.weixin.qq.com/s/article_example", None, FakeClient(response(page)))
    assert result.status is Status.UNSUPPORTED
    assert result.profiles == []


@pytest.mark.parametrize("suffix", ["__biz=invalid!", f"__biz={BIZ}&__biz={BIZ}"])
def test_wechat_rejects_invalid_or_duplicate_biz(suffix):
    client = FakeClient()
    assert resolve(f"https://mp.weixin.qq.com/s?{suffix}", None, client).status is Status.INVALID
    assert client.calls == []


def test_wechat_blocked_and_network_errors_preserve_supplied_biz():
    url = f"https://mp.weixin.qq.com/s?__biz={BIZ}"
    blocked = resolve(url, None, FakeClient(response("<title>安全验证</title>")))
    failed = resolve(url, None, FakeClient(error=FetchError("连接超时")))
    assert blocked.status is Status.BLOCKED
    assert failed.status is Status.ERROR
    assert blocked.profiles[0].identifier == failed.profiles[0].identifier == BIZ
