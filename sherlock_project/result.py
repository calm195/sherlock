"""Sherlock 查询结果模块。

定义用于记录查询状态与结果的对象。
"""
from enum import Enum


class QueryStatus(Enum):
    """查询状态枚举。

    描述针对指定用户名的查询状态。
    """
    CLAIMED   = "Claimed"   # 检测到用户名。
    AVAILABLE = "Available" # 未检测到用户名。
    UNKNOWN   = "Unknown"   # 检测用户名时发生错误。
    ILLEGAL   = "Illegal"   # 用户名不符合该站点的格式要求。
    WAF       = "WAF"       # 请求被 Web 应用防火墙（如 Cloudflare）拦截。

    def __str__(self):
        """返回查询状态的字符串值。"""
        return self.value

class QueryResult():
    """查询结果对象。

    描述针对指定用户名的查询结果。
    """
    def __init__(self, username, site_name, site_url_user, status,
                 query_time=None, context=None):
        """创建查询结果对象。

        保存指定站点上用户名存在性检测的结果。

        参数：
        self                   -- 当前对象。
        username               -- 本次查询的用户名字符串。
        site_name              -- 站点名称字符串。
        site_url_user          -- 用户在该站点的个人主页 URL。
                                  此地址不保证账号存在，仅表示账号存在时的地址。
        status                 -- 表示查询状态的 QueryStatus 枚举值。
        query_time             -- 查询耗时，单位为秒，默认为 None。
        context                -- 查询的额外上下文字符串，例如发生的错误类型。
                                  默认为 None。

        返回值：
        无。
        """

        self.username      = username
        self.site_name     = site_name
        self.site_url_user = site_url_user
        self.status        = status
        self.query_time    = query_time
        self.context       = context


    def __str__(self):
        """返回查询状态及额外上下文信息的字符串表示。"""
        status = str(self.status)
        if self.context is not None:
            # 结果包含额外的上下文信息时，
            # 将其追加到常规状态文本之后。
            status += f" ({self.context})"

        return status
