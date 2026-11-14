"""区分账号候选、链接解析结果和无法验证的情况。"""

from dataclasses import dataclass, field
from enum import Enum

PLATFORMS = {
    "bilibili": "哔哩哔哩",
    "xiaohongshu": "小红书",
    "douyin": "抖音",
    "kuaishou": "快手",
    "qq": "QQ",
    "wechat": "微信",
}

ALIASES = {
    "b站": "bilibili", "哔哩哔哩": "bilibili", "bili": "bilibili",
    "小红书": "xiaohongshu", "xhs": "xiaohongshu",
    "抖音": "douyin", "dy": "douyin",
    "快手": "kuaishou", "ks": "kuaishou",
    "微信": "wechat", "weixin": "wechat", "wx": "wechat",
}


def normalize_platform(value: str) -> str:
    """接受平台英文名称或中文别名，返回统一的平台名称。"""
    key = value.strip().lower()
    key = ALIASES.get(key, key)
    if key not in PLATFORMS:
        raise ValueError(f"不支持的平台：{value}。可选：{', '.join(PLATFORMS)}")
    return key


class Status(str, Enum):
    FOUND = "FOUND"
    RESOLVED = "RESOLVED"
    NOT_FOUND = "NOT_FOUND"
    BLOCKED = "BLOCKED"
    UNSUPPORTED = "UNSUPPORTED"
    INVALID = "INVALID"
    ERROR = "ERROR"


@dataclass
class Profile:
    platform: str
    identifier: str
    url: str
    nickname: str | None = None
    identifier_kind: str = "user_id"


@dataclass
class Result:
    platform: str
    input: str
    status: Status
    message: str
    profiles: list[Profile] = field(default_factory=list)
    search_url: str | None = None
