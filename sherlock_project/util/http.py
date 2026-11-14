"""并发 HTTP 请求计时与响应异常处理。"""

from time import monotonic

import requests
from requests_futures.sessions import FuturesSession


class SherlockFuturesSession(FuturesSession):
    def request(self, method, url, hooks=None, *args, **kwargs):
        """请求指定 URL。

        扩展 FuturesSession 的 request 方法，为每个请求记录响应耗时。
        实现参考：
        https://github.com/ross/requests-futures#working-in-the-background

        参数：
        self                   -- 当前对象。
        method                 -- HTTP 请求方法字符串。
        url                    -- 请求的 URL 字符串。
        hooks                  -- 保存响应处理钩子的字典。
        args                   -- 其他位置参数。
        kwargs                 -- 其他关键字参数。

        返回值：
        用于获取请求响应的 Future 对象。
        """
        # 记录请求的开始时间。
        if hooks is None:
            hooks = {}
        start = monotonic()

        def response_time(resp, *args, **kwargs):
            """在其他响应钩子执行之前记录响应耗时。"""
            resp.elapsed = monotonic() - start

        # 将计时钩子放在首位，避免将后续钩子的执行时间计入响应耗时。
        try:
            if isinstance(hooks["response"], list):
                hooks["response"].insert(0, response_time)
            elif isinstance(hooks["response"], tuple):
                # 将元组转换为列表，并在首位插入计时钩子。
                hooks["response"] = list(hooks["response"])
                hooks["response"].insert(0, response_time)
            else:
                # 原配置为单个钩子函数，将其转换为列表。
                hooks["response"] = [response_time, hooks["response"]]
        except KeyError:
            # 尚未定义响应钩子，直接注册计时钩子。
            hooks["response"] = [response_time]

        return super().request(
            method, url, *args, hooks=hooks, **kwargs
        )


def get_response(request_future, error_type, social_network):
    """读取 Future，返回响应、错误分类和异常说明；保留原有调用参数。"""
    # 请求失败时，响应对象默认为 None。
    response = None

    error_context = "General Unknown Error"
    exception_text = None
    try:
        response = request_future.result()
        if response.status_code:
            # 响应对象中存在有效的状态码。
            error_context = None
    except requests.exceptions.HTTPError as errh:
        error_context = "HTTP Error"
        exception_text = str(errh)
    except requests.exceptions.ProxyError as errp:
        error_context = "Proxy Error"
        exception_text = str(errp)
    except requests.exceptions.ConnectionError as errc:
        error_context = "Error Connecting"
        exception_text = str(errc)
    except requests.exceptions.Timeout as errt:
        error_context = "Timeout Error"
        exception_text = str(errt)
    except requests.exceptions.RequestException as err:
        error_context = "Unknown Error"
        exception_text = str(err)
    except UnicodeError as err:
        error_context = "Encoding Error"
        exception_text = str(err)

    return response, error_context, exception_text
