"""用户名查询引擎：提交站点请求、判定响应并通知查询结果。"""

import re
from contextlib import suppress

import requests

from sherlock_project.notify import QueryNotify
from sherlock_project.result import QueryResult, QueryStatus
from sherlock_project.util.http import SherlockFuturesSession, get_response
from sherlock_project.util.text import interpolate_string

# WAF 指纹应尽量精确，并保留防护服务和采集日期，避免把拦截页当作账号结果。
_WAF_MESSAGES = (
    r'.loading-spinner{visibility:hidden}body.no-js .challenge-running{display:none}body.dark{background-color:#222;color:#d9d9d9}body.dark a{color:#fff}body.dark a:hover{color:#ee730a;text-decoration:underline}body.dark .lds-ring div{border-color:#999 transparent transparent}body.dark .font-red{color:#b20f03}body.dark',  # 2024-05-13 Cloudflare
    r'<span id="challenge-error-text">',  # 2024-11-11 Cloudflare 错误页面
    r'AwsWafIntegration.forceRefreshToken',  # 2024-11-11 Cloudfront (AWS)
    r'{return l.onPageView}}),Object.defineProperty(r,"perimeterxIdentifiers",{enumerable:',  # 2024-04-09 PerimeterX / Human Security
)


def _submit_request(session, net_info, url, username, headers, proxy, timeout):
    """按站点规则选择请求方法，替换模板并提交后台请求。"""
    method = net_info.get("request_method")
    if method is None:
        method = "HEAD" if net_info["errorType"] == "status_code" else "GET"
    elif method not in ("GET", "HEAD", "POST", "PUT"):
        raise RuntimeError(f"Unsupported request_method for {url}")
    request = getattr(session, method.lower())

    payload = net_info.get("request_payload")
    if payload is not None:
        payload = interpolate_string(payload, username)
    probe = net_info.get("urlProbe")
    probe = url if probe is None else interpolate_string(probe, username)
    options = {
        "url": probe,
        "headers": headers,
        # 单独使用 response_url 检测时保留原始响应，不自动跟随跳转。
        "allow_redirects": net_info["errorType"] != "response_url",
        "timeout": timeout,
        "json": payload,
    }
    if proxy is not None:
        options["proxies"] = {"http": proxy, "https": proxy}
    return request(**options)


def _prepare_site(username, social_network, net_info, query_notify, session, proxy, timeout):
    """检查用户名约束，非法输入立即通知，其余输入提交请求。"""
    result = {"url_main": net_info.get("urlMain")}
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:129.0) Gecko/20100101 Firefox/129.0",
    }
    if "headers" in net_info:
        headers.update(net_info["headers"])
    url = interpolate_string(net_info["url"], username.replace(" ", "%20"))

    regex_check = net_info.get("regexCheck")
    if regex_check and re.search(regex_check, username) is None:
        result.update({
            "status": QueryResult(username, social_network, url, QueryStatus.ILLEGAL),
            "url_user": "", "http_status": "", "response_text": "",
        })
        query_notify.update(result["status"])
    else:
        result["url_user"] = url
        # 沿用站点字典保存 Future 的接口，供收集阶段及现有调用方读取。
        net_info["request_future"] = _submit_request(
            session, net_info, url, username, headers, proxy, timeout,
        )
    return result


def _classify_response(response, net_info, error_type, social_network, error_text):
    """按原有顺序处理请求错误、WAF 和各类站点判定规则。"""
    if error_text is not None:
        return QueryStatus.UNKNOWN, error_text
    if any(message in response.text for message in _WAF_MESSAGES):
        return QueryStatus.WAF, None
    if any(kind not in ("message", "status_code", "response_url") for kind in error_type):
        return QueryStatus.UNKNOWN, f"Unknown error type '{error_type}' for {social_network}"

    status = QueryStatus.UNKNOWN
    if "message" in error_type:
        errors = net_info.get("errorMsg")
        if isinstance(errors, str):
            errors = [errors]
        absent = any(error in response.text for error in errors)
        status = QueryStatus.AVAILABLE if absent else QueryStatus.CLAIMED

    # 组合规则中，一旦判为 AVAILABLE，后续规则不能将其覆盖为 CLAIMED。
    if "status_code" in error_type and status is not QueryStatus.AVAILABLE:
        error_codes = net_info.get("errorCode")
        if isinstance(error_codes, int):
            error_codes = [error_codes]
        if (
            (error_codes is not None and response.status_code in error_codes)
            or response.status_code >= 300
            or response.status_code < 200
        ):
            status = QueryStatus.AVAILABLE
        else:
            status = QueryStatus.CLAIMED

    if "response_url" in error_type and status is not QueryStatus.AVAILABLE:
        status = QueryStatus.CLAIMED if 200 <= response.status_code < 300 else QueryStatus.AVAILABLE
    return status, None


def _dump_response(username, social_network, url, net_info, error_type, response, status):
    """输出原有调试信息；请求失败时仍能显示可用字段和最终判定。"""
    print("+++++++++++++++++++++")
    print(f"TARGET NAME   : {social_network}")
    print(f"USERNAME      : {username}")
    print(f"TARGET URL    : {url}")
    print(f"TEST METHOD   : {error_type}")
    try:
        print(f"STATUS CODES  : {net_info['errorCode']}")
    except KeyError:
        pass
    print("Results...")
    with suppress(Exception):
        print(f"RESPONSE CODE : {response.status_code}")
    try:
        print(f"ERROR TEXT    : {net_info['errorMsg']}")
    except KeyError:
        pass
    print(">>>>> BEGIN RESPONSE TEXT")
    with suppress(Exception):
        print(response.text)
    print("<<<<< END RESPONSE TEXT")
    print("VERDICT       : " + str(status))
    print("+++++++++++++++++++++")


def _collect_response(username, social_network, net_info, result, query_notify, dump_response):
    """读取单站点请求，填充结果并发送通知。"""
    error_type = net_info["errorType"]
    if isinstance(error_type, str):
        error_type = [error_type]
    response, error_text, _ = get_response(
        request_future=net_info["request_future"],
        error_type=error_type,
        social_network=social_network,
    )
    try:
        response_time = response.elapsed
    except AttributeError:
        response_time = None
    try:
        http_status = response.status_code
    except Exception:  # noqa: BLE001 - 沿用原有容错，读取响应失败时保留占位值。
        http_status = "?"
    try:
        response_text = response.text.encode(response.encoding or "UTF-8")
    except Exception:  # noqa: BLE001 - 编码或响应属性读取失败都不应中断结果汇总。
        response_text = ""

    status, context = _classify_response(response, net_info, error_type, social_network, error_text)
    if dump_response:
        _dump_response(username, social_network, result["url_user"], net_info, error_type, response, status)
    notification = QueryResult(
        username=username,
        site_name=social_network,
        site_url_user=result["url_user"],
        status=status,
        query_time=response_time,
        context=context,
    )
    query_notify.update(notification)
    result.update({"status": notification, "http_status": http_status, "response_text": response_text})


def sherlock(
    username: str,
    site_data: dict[str, dict[str, str]],
    query_notify: QueryNotify,
    dump_response: bool = False,
    proxy: str | None = None,
    timeout: int = 60,
) -> dict[str, dict[str, str | QueryResult]]:
    """查询一个用户名，在所有请求提交后按站点顺序收集结果。

    site_data 提供站点 URL、请求方式和判定规则；query_notify 接收开始与结果通知。
    返回以站点名称为键的字典，每项包含 url_main、url_user、status、http_status
    和 response_text；status 为 QueryResult，response_text 保留原有字节数据格式。
    """
    query_notify.start(username)
    underlying_session = requests.session()
    session = SherlockFuturesSession(max_workers=min(len(site_data), 20), session=underlying_session)

    # 先提交全部站点请求，避免逐个等待导致并发查询退化为串行。
    results = {
        name: _prepare_site(username, name, info, query_notify, session, proxy, timeout)
        for name, info in site_data.items()
    }
    for name, info in site_data.items():
        if results[name].get("status") is None:
            _collect_response(username, name, info, results[name], query_notify, dump_response)
    return results
