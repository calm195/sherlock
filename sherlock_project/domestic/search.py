"""国内平台昵称搜索；候选账号与人工搜索入口分别返回。"""

import re
from html import unescape
from urllib.parse import quote, urlencode

from .models import Profile, Result, Status, normalize_platform
from .transport import Client, FetchError


def _search_url(platform: str, query: str) -> str | None:
    """构建平台自身的搜索入口，链接本身不表示搜索成功。"""
    if platform == "bilibili":
        return "https://search.bilibili.com/upuser?" + urlencode({"keyword": query})
    if platform == "xiaohongshu":
        return "https://www.xiaohongshu.com/search_result?" + urlencode({
            "keyword": query, "type": "51",
        })
    if platform == "douyin":
        return "https://www.douyin.com/search/" + quote(query, safe="") + "?type=user"
    if platform == "kuaishou":
        return "https://www.kuaishou.com/search/author?" + urlencode({"searchKey": query})
    return None


def _bilibili_search(query: str, client: Client, limit: int) -> Result:
    """只接受成功响应中的用户列表，不从通用页面推断账号存在性。"""
    result = Result(
        "bilibili", query, Status.ERROR, "未取得可验证的用户搜索结果。",
        search_url=_search_url("bilibili", query),
    )
    url = "https://api.bilibili.com/x/web-interface/search/type?" + urlencode({
        "search_type": "bili_user", "keyword": query, "page": 1,
    })
    try:
        response = client.get(url, platform="bilibili")
    except FetchError as exc:
        result.message = str(exc)
        return result

    if response.status_code in {401, 403, 412, 429}:
        result.status = Status.BLOCKED
        result.message = f"用户搜索被限制（HTTP {response.status_code}），请在官方搜索页确认。"
        return result
    if not 200 <= response.status_code < 300:
        result.message = f"用户搜索请求失败（HTTP {response.status_code}）。"
        return result

    try:
        payload = response.json()
    except ValueError:
        # 实测接口可能以 HTTP 200 返回该风控页面，不能视为搜索成功。
        if "aba.bilibili.com" in response.text or "验证码_哔哩哔哩" in response.text:
            result.status = Status.BLOCKED
            result.message = "用户搜索返回验证或风控页面，请在官方搜索页确认。"
        else:
            result.message = "用户搜索未返回预期的 JSON 数据，无法判断搜索结果。"
        return result

    if not isinstance(payload, dict) or type(payload.get("code")) is not int:
        result.message = "用户搜索响应缺少有效的状态码。"
        return result
    code = payload["code"]
    if code != 0:
        if code in {-101, -352, -403, -412, -509, 429}:
            result.status = Status.BLOCKED
            result.message = f"用户搜索受登录、风控或频率限制（code={code}），请在官方搜索页确认。"
        else:
            result.message = f"用户搜索接口返回错误（code={code}），无法判断搜索结果。"
        return result

    data = payload.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("result"), list):
        result.message = "用户搜索响应缺少用户列表，无法判断搜索结果。"
        return result
    rows = data["result"]
    if not rows:
        result.status = Status.NOT_FOUND
        result.message = "本次用户搜索未返回候选；这不证明该昵称在平台上不存在。"
        return result

    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        mid = row.get("mid")
        if type(mid) not in {str, int} or not re.fullmatch(r"[1-9][0-9]{0,19}", str(mid)):
            continue
        nickname = row.get("uname")
        if not isinstance(nickname, str):
            continue
        # 搜索接口会在命中的昵称片段外加入高亮标签。
        nickname = unescape(re.sub(r"<[^>]*>", "", nickname)).strip()
        if not nickname or str(mid) in seen:
            continue
        seen.add(str(mid))
        result.profiles.append(Profile(
            platform="bilibili", identifier=str(mid),
            url=f"https://space.bilibili.com/{mid}", nickname=nickname,
            identifier_kind="uid",
        ))
        if len(result.profiles) >= limit:
            break

    if result.profiles:
        result.status = Status.FOUND
        result.message = (
            f"首个搜索结果页中取得 {len(result.profiles)} 个候选账号；"
            "可能包含近似昵称，同名也不表示属于同一个人。"
        )
    else:
        result.message = "用户列表中没有有效的账号 ID 和昵称，无法判断搜索结果。"
    return result


def search(query: str, platform: str, client: Client, limit: int = 5) -> Result:
    """搜索昵称，或明确返回当前尚不支持自动搜索的平台入口。"""
    try:
        platform = normalize_platform(platform)
    except ValueError as exc:
        return Result(platform, query, Status.INVALID, str(exc))
    query = query.strip()
    if not query or any(ord(char) < 32 or ord(char) == 127 for char in query):
        return Result(platform, query, Status.INVALID, "请输入非空昵称，且不要包含控制字符。")
    if type(limit) is not int or not 1 <= limit <= 20:
        return Result(platform, query, Status.INVALID, "候选数量必须是 1 到 20 之间的整数。")

    if platform == "bilibili":
        return _bilibili_search(query, client, limit)

    messages = {
        "xiaohongshu": "当前不支持自动获取小红书昵称搜索结果；仅提供官方用户搜索入口，请在浏览器或客户端登录后确认。",
        "douyin": "当前不支持自动获取抖音昵称搜索结果；仅提供官方用户搜索入口，请在浏览器或客户端确认。",
        "kuaishou": "当前不支持自动获取快手昵称搜索结果；仅提供官方用户搜索入口，请在浏览器或客户端登录后确认。",
        "qq": "当前没有可用的公开 QQ 个人昵称搜索适配器，请在 QQ 客户端查找；已有 QQ 号可使用账号解析。",
        "wechat": "当前没有可用的公开微信个人昵称或微信号搜索适配器，请在微信客户端查找；公众号文章链接可使用链接解析。",
    }
    return Result(
        platform, query, Status.UNSUPPORTED, messages[platform],
        search_url=_search_url(platform, query),
    )
