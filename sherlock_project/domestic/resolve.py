"""解析国内平台公开主页、账号标识及主页分享链接。"""

import json
import re
from dataclasses import replace
from html import unescape
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit, urlunsplit

from .models import Profile, Result, Status, normalize_platform
from .transport import HOSTS, Client, FetchError, validate_url

_SHORT_HOSTS = {"b23.tv", "xhslink.com", "www.xhslink.com", "v.douyin.com", "v.kuaishou.com"}
_UID = r"[1-9][0-9]{0,19}"
_XHS_ID = r"[0-9a-fA-F]{24}"
_SEC_UID = r"MS4wLjAB[A-Za-z0-9_-]{6,200}"
_QQ_ID = r"[1-9][0-9]{4,11}"
_BIZ = r"[A-Za-z0-9+/]{6,128}={0,2}"


def _result(platform, value, status, message, profile=None):
    return Result(platform, value, status, message, [profile] if profile else [])


def _identify_url(url):
    """严格校验域名，避免把带有平台名称的其他网址当作主页。"""
    hostname = urlsplit(url).hostname
    for platform, hosts in HOSTS.items():
        if hostname in hosts:
            try:
                validate_url(url, platform)
            except FetchError as exc:
                raise ValueError(str(exc)) from exc
            return platform
    raise ValueError("链接域名不属于支持的平台。")


def _extract_input(value, platform):
    """接受平台前缀或包含一个网址的分享文本，拒绝有歧义的多链接输入。"""
    value = value.strip()
    if not value:
        raise ValueError("请输入账号 ID、主页链接或主页分享文本。")
    prefix, separator, remainder = value.partition(":")
    if separator and prefix.lower() not in {"http", "https"}:
        try:
            prefixed_platform = normalize_platform(prefix)
        except ValueError:
            pass
        else:
            if platform and platform != prefixed_platform:
                raise ValueError("输入中的平台前缀与所选平台不一致。")
            platform = prefixed_platform
            value = remainder.strip()
    links = re.findall(r"https?://[^\s<>\"'`]+", unescape(value), re.IGNORECASE)
    if len(links) > 1:
        raise ValueError("一次解析只能包含一个链接，请分别传入多个链接。")
    if links:
        # 分享文本末尾可能附带标点；独立 URL 则保留参数中的合法字符。
        value = links[0] if value == links[0] else links[0].rstrip(".,;!?)>]】）。，；！")
    elif any(value.startswith(host + "/") for hosts in HOSTS.values() for host in hosts):
        value = "https://" + value
    if "://" in value:
        inferred = _identify_url(value)
        if platform and platform != inferred:
            raise ValueError("链接所属平台与所选平台不一致。")
        return value, inferred, True
    if not platform:
        raise ValueError("裸账号 ID 无法自动确定平台，请使用 --platform 或平台前缀。")
    return value, platform, False


def _profile(platform, identifier):
    if platform == "bilibili":
        return Profile(platform, identifier, f"https://space.bilibili.com/{identifier}", identifier_kind="uid")
    if platform == "xiaohongshu":
        identifier = identifier.lower()
        return Profile(platform, identifier, f"https://www.xiaohongshu.com/user/profile/{identifier}")
    if platform == "douyin":
        return Profile(platform, identifier, f"https://www.douyin.com/user/{identifier}", identifier_kind="sec_uid")
    if platform == "kuaishou":
        return Profile(platform, identifier, f"https://www.kuaishou.com/profile/{identifier}")
    return Profile(platform, identifier, f"https://user.qzone.qq.com/{identifier}", identifier_kind="qq")


def _from_identifier(platform, identifier):
    patterns = {
        "bilibili": _UID,
        "xiaohongshu": _XHS_ID,
        "douyin": _SEC_UID,
        # 数字 UID 与网页常见的加密 ID 均可使用；可修改的快手号需另行搜索。
        "kuaishou": rf"(?:{_UID}|3x[a-zA-Z0-9]{{10,32}})",
        "qq": _QQ_ID,
    }
    pattern = patterns.get(platform)
    if pattern and re.fullmatch(pattern, identifier):
        return _profile(platform, identifier)
    return None


def _from_url(platform, url):
    parts = urlsplit(url)
    path = parts.path
    pattern = None
    if platform == "bilibili":
        if parts.hostname == "space.bilibili.com":
            pattern = rf"/({_UID})(?:/(?:video|dynamic|favlist|fans|follow))?/?"
        elif parts.hostname == "m.bilibili.com":
            pattern = rf"/space/({_UID})/?"
    elif platform == "xiaohongshu" and parts.hostname in {"www.xiaohongshu.com", "xiaohongshu.com"}:
        pattern = rf"/user/profile/({_XHS_ID})/?"
    elif platform == "douyin":
        if parts.hostname in {"www.douyin.com", "douyin.com"}:
            pattern = rf"/user/({_SEC_UID})/?"
        elif parts.hostname in {"www.iesdouyin.com", "iesdouyin.com"} and re.fullmatch(r"/share/user/[0-9]+/?", path):
            identifiers = parse_qs(parts.query).get("sec_uid", [])
            if len(identifiers) == 1 and re.fullmatch(_SEC_UID, identifiers[0]):
                return _profile(platform, identifiers[0])
    elif platform == "kuaishou" and parts.hostname in {"www.kuaishou.com", "kuaishou.com"}:
        pattern = r"/profile/([A-Za-z0-9_-]{3,64})/?"
    elif platform == "qq":
        if parts.hostname == "user.qzone.qq.com":
            pattern = rf"/({_QQ_ID})/?"
        elif parts.hostname == "wpa.qq.com" and path == "/msgrd":
            identifiers = parse_qs(parts.query).get("uin", [])
            if len(identifiers) == 1 and re.fullmatch(_QQ_ID, identifiers[0]):
                return _profile(platform, identifiers[0])
    match = re.fullmatch(pattern, path) if pattern else None
    return _profile(platform, match[1]) if match else None


def _access_limited(response):
    """仅使用明确拦截特征，普通页面上的登录按钮不代表请求被拒绝。"""
    if response.status_code in {401, 403, 412, 418, 429, 451, 521}:
        return True
    if re.search(r"/(?:login|passport|captcha|verify)(?:/|$)", urlsplit(response.url).path, re.IGNORECASE):
        return True
    title = re.search(r"<title[^>]*>(.*?)</title>", response.text, re.DOTALL | re.IGNORECASE)
    return bool(title and re.search(r"安全验证|验证码|访问受限|操作频繁|出错啦|请.{0,3}登录", unescape(title[1])))


def _bilibili(value, profile, client):
    response = client.get(
        f"https://api.bilibili.com/x/web-interface/card?mid={profile.identifier}",
        platform="bilibili",
    )
    if _access_limited(response):
        return _result("bilibili", value, Status.BLOCKED, "B站限制了公开接口访问；已提取 UID，但未验证账号存在。", profile)
    if response.status_code != 200:
        return _result("bilibili", value, Status.ERROR, f"B站接口返回 HTTP {response.status_code}；无法验证账号。", profile)
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if not isinstance(payload, dict):
        return _result("bilibili", value, Status.RESOLVED, "已解析 UID；接口未返回可验证的账号数据。", profile)
    code = payload.get("code")
    if type(code) is not int:
        return _result("bilibili", value, Status.RESOLVED, "已解析 UID；接口未返回有效的业务状态码。", profile)
    if code in {-101, -111, -352, -403, -412, -509}:
        return _result("bilibili", value, Status.BLOCKED, f"B站接口要求登录或限制访问（code={code}）；未验证账号存在。", profile)
    if code == -404 and payload.get("message") in ("用户不存在", "账号不存在", "用户已注销"):
        return _result("bilibili", value, Status.NOT_FOUND, "B站账号接口明确返回用户不存在（code=-404）。", profile)
    data = payload.get("data")
    card = data.get("card") if isinstance(data, dict) else None
    if code == 0 and isinstance(card, dict):
        if str(card.get("mid", "")) != profile.identifier:
            return _result("bilibili", value, Status.ERROR, "接口返回的 UID 与请求不一致，无法确认账号。", profile)
        nickname = card.get("name")
        if isinstance(nickname, str) and nickname.strip():
            return _result("bilibili", value, Status.FOUND, "公开账号接口返回了匹配 UID 的账号资料。", replace(profile, nickname=nickname.strip()))
    return _result("bilibili", value, Status.RESOLVED, "已解析 UID；接口没有提供完整且匹配的账号资料。", profile)


class _ArticleAuthor(HTMLParser):
    """只读取公众号文章作者元素，忽略正文里其他账号的名称。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.author_parts = []
        self.in_author = False
        self.author_tag = None
        self.has_content = False
        self.script_parts = []
        self.in_script = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script":
            self.in_script = True
        if attrs.get("id") == "js_name":
            self.in_author = True
            self.author_tag = tag
        if attrs.get("id") == "js_content":
            self.has_content = True

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_script = False
        if tag == self.author_tag:
            self.in_author = False

    def handle_data(self, data):
        if self.in_script:
            self.script_parts.append(data)
        if self.in_author:
            self.author_parts.append(data)


def _article_variable(text, name):
    # 只处理字符串字面量，绝不执行网页中的 JavaScript。
    match = re.search(
        rf"\b(?:var\s+|window\.){name}\s*=\s*(?:htmlDecode\(\s*)?(\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*')",
        text,
    )
    if not match:
        return None
    token = match[1]
    if token.startswith('"'):
        try:
            return unescape(json.loads(token))
        except ValueError:
            return None
    value = token[1:-1]
    value = re.sub(r"\\u([0-9a-fA-F]{4})|\\x([0-9a-fA-F]{2})", lambda m: chr(int(m[1] or m[2], 16)), value)
    return unescape(value.replace("\\'", "'").replace("\\\\", "\\"))


def _wechat(value, url, client):
    parts = urlsplit(url)
    supplied = parse_qs(parts.query, keep_blank_values=True).get("__biz", [])
    if len(supplied) > 1 or (supplied and not re.fullmatch(_BIZ, supplied[0])):
        return _result("wechat", value, Status.INVALID, "公众号链接中的 __biz 参数无效或不唯一。")
    biz = supplied[0] if supplied else None
    source_url = urlunsplit(("https", "mp.weixin.qq.com", parts.path, parts.query, ""))
    profile = Profile("wechat", biz, source_url, identifier_kind="biz") if biz else None
    if parts.path == "/mp/profile_ext" and profile:
        return _result("wechat", value, Status.RESOLVED, "已从公众号主页链接提取 biz；未验证公众号存在。", profile)
    if not (parts.path == "/s" or re.fullmatch(r"/s/[A-Za-z0-9_-]+/?", parts.path)):
        return _result("wechat", value, Status.UNSUPPORTED, "支持公众号文章或带 __biz 的公众号主页链接；不支持微信个人号查询。")
    try:
        response = client.get(source_url, platform="wechat")
    except FetchError as exc:
        return _result("wechat", value, Status.ERROR, f"公开文章请求失败：{exc}", profile)
    if _access_limited(response):
        return _result("wechat", value, Status.BLOCKED, "微信文章需要登录或安全验证；无法验证公众号作者。", profile)
    if response.status_code != 200:
        return _result("wechat", value, Status.ERROR, f"文章返回 HTTP {response.status_code}；无法确认公众号作者。", profile)
    author = _ArticleAuthor()
    author.feed(response.text)
    scripts = "\n".join(author.script_parts)
    body_biz = _article_variable(scripts, "biz")
    nickname = "".join(author.author_parts).strip() or _article_variable(scripts, "nickname")
    if body_biz and re.fullmatch(_BIZ, body_biz):
        if biz and body_biz != biz:
            return _result("wechat", value, Status.ERROR, "文章中的公众号标识与链接参数不一致。", profile)
        profile = Profile("wechat", body_biz, source_url, nickname=nickname or None, identifier_kind="biz")
        if nickname and author.has_content:
            return _result("wechat", value, Status.FOUND, "已从公开文章的作者字段解析公众号标识与名称。", profile)
    if profile:
        return _result("wechat", value, Status.RESOLVED, "已提取公众号标识；页面未提供可验证的完整作者信息。", profile)
    return _result("wechat", value, Status.UNSUPPORTED, "文章未返回可识别的公众号作者数据，可能需要在微信内打开。")


def resolve(value: str, platform: str | None, client: Client) -> Result:
    """解析输入并尝试验证公开资料；RESOLVED 仅表示格式与链接归一化成功。"""
    original = value
    profile = None
    try:
        platform = normalize_platform(platform) if platform else None
        value, platform, is_url = _extract_input(value, platform)
    except ValueError as exc:
        return _result(platform or "unknown", original, Status.INVALID, str(exc))
    try:
        if platform == "wechat":
            if is_url:
                return _wechat(original, value, client)
            return _result(platform, original, Status.UNSUPPORTED, "无法通过微信个人号或昵称进行公开账号验证；可解析公众号文章链接。")
        response = None
        if is_url:
            if urlsplit(value).hostname in _SHORT_HOSTS:
                response = client.get(value, platform=platform)
                if _access_limited(response):
                    return _result(platform, original, Status.BLOCKED, "分享链接需要登录或安全验证，暂时无法取得主页地址。")
                if _identify_url(response.url) != platform:
                    return _result(platform, original, Status.ERROR, "分享链接跳转到了其他平台，未继续解析。")
                value = response.url
            profile = _from_url(platform, value)
        else:
            profile = _from_identifier(platform, value)
        if profile is None:
            hints = {
                "bilibili": "请提供数字 UID 或 space.bilibili.com 主页链接。",
                "xiaohongshu": "请提供主页中的 24 位内部 ID 或主页链接；小红书号和昵称需使用搜索。",
                "douyin": "请提供主页链接或以 MS4wLjAB 开头的 sec_uid；抖音号和昵称需使用搜索。",
                "kuaishou": "请提供网页主页 ID 或 /profile/ 主页链接；快手号和昵称需使用搜索。",
                "qq": "请提供 5 至 12 位 QQ 号、QQ 空间链接或含 uin 的官方联系链接。",
            }
            message = hints[platform]
            if is_url:
                message += "视频、笔记等内容链接暂不解析为作者，也不会使用分享者参数代替作者。"
            return _result(platform, original, Status.UNSUPPORTED, message)
        if platform == "qq":
            return _result(platform, original, Status.RESOLVED, "已解析 QQ 号和空间地址；未验证 QQ 账号或空间存在。", profile)
        if platform == "bilibili":
            return _bilibili(original, profile, client)
        # 当前未验证其他平台的公开账号响应，不能仅凭 HTTP 200 宣告账号存在。
        if response is None:
            response = client.get(value if is_url else profile.url, platform=platform)
        if _access_limited(response):
            return _result(platform, original, Status.BLOCKED, "已解析主页标识，但平台要求登录或安全验证；未验证账号存在。", profile)
        if response.status_code >= 500:
            return _result(platform, original, Status.ERROR, f"已解析主页标识，但平台返回 HTTP {response.status_code}。", profile)
        return _result(platform, original, Status.RESOLVED, "已解析主页标识与规范链接；页面响应不足以验证账号是否存在。", profile)
    except FetchError as exc:
        return _result(platform, original, Status.ERROR, f"公开页面请求失败：{exc}", profile)
    except ValueError as exc:
        return _result(platform, original, Status.ERROR, f"页面或跳转地址无法解析：{exc}", profile)
