"""国内平台请求：限制访问域名、跳转次数和响应大小。"""

from urllib.parse import urljoin, urlsplit, urlunsplit

import requests

HOSTS = {
    "bilibili": {
        "space.bilibili.com", "api.bilibili.com", "www.bilibili.com",
        "m.bilibili.com", "search.bilibili.com", "b23.tv",
    },
    "xiaohongshu": {
        "www.xiaohongshu.com", "xiaohongshu.com", "xhslink.com", "www.xhslink.com",
    },
    "douyin": {
        "www.douyin.com", "douyin.com", "v.douyin.com",
        "www.iesdouyin.com", "iesdouyin.com",
    },
    "kuaishou": {
        "www.kuaishou.com", "kuaishou.com", "v.kuaishou.com",
        "www.gifshow.com", "gifshow.com",
    },
    "qq": {"user.qzone.qq.com", "wpa.qq.com"},
    "wechat": {"mp.weixin.qq.com"},
}


class FetchError(Exception):
    """公开页面请求失败，无法据此判定账号是否存在。"""


def validate_url(url: str, platform: str) -> str:
    """仅允许当前平台的已知公开域名，并使用 HTTPS。"""
    if url != url.strip() or "\\" in url or any(ord(c) < 32 or ord(c) == 127 for c in url):
        raise FetchError("链接含有非法字符。")
    try:
        parts = urlsplit(url)
        if (
            parts.scheme not in {"http", "https"}
            or parts.hostname not in HOSTS.get(platform, set())
            or parts.username is not None
            or parts.password is not None
            or parts.port not in {None, 80 if parts.scheme == "http" else 443}
        ):
            raise FetchError("链接或跳转目标不在该平台的公开域名范围内。")
    except ValueError as exc:
        raise FetchError("链接格式无效。") from exc
    return urlunsplit(("https", parts.hostname, parts.path or "/", parts.query, ""))


class Client:
    """共享会话；每次跳转先校验目标，再发送请求。"""

    MAX_REDIRECTS = 5
    MAX_BYTES = 4 * 1024 * 1024

    def __init__(self, timeout: float = 20, proxy: str | None = None):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:129.0) Gecko/20100101 Firefox/129.0",
        })
        self.proxies = {"http": proxy, "https": proxy} if proxy else None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.session.close()

    def get(self, url: str, *, platform: str) -> requests.Response:
        """读取页面，不执行脚本；拒绝跨平台跳转和过大的响应。"""
        try:
            for redirect in range(self.MAX_REDIRECTS + 1):
                url = validate_url(url, platform)
                response = self.session.get(
                    url,
                    allow_redirects=False,
                    timeout=self.timeout,
                    stream=True,
                    proxies=self.proxies,
                )
                try:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("Location")
                        if not location:
                            raise FetchError("重定向响应缺少目标链接。")
                        if redirect == self.MAX_REDIRECTS:
                            raise FetchError("分享链接的重定向次数过多。")
                        url = urljoin(url, location)
                        continue

                    chunks = []
                    size = 0
                    for chunk in response.iter_content(chunk_size=65536):
                        size += len(chunk)
                        if size > self.MAX_BYTES:
                            raise FetchError("页面过大，已停止解析。")
                        chunks.append(chunk)
                    response._content = b"".join(chunks)
                    response._content_consumed = True
                    # 平台页面和接口均使用 UTF-8，避免 text/html 的默认编码误判。
                    response.encoding = "utf-8"
                    return response
                finally:
                    response.close()
        except requests.RequestException as exc:
            raise FetchError(f"网络请求失败：{exc}") from exc
        raise FetchError("未取得有效响应。")
