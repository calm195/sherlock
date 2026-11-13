#! /usr/bin/env python3

"""Sherlock 跨社交网络用户名查询模块。

实现查询各社交网站用户名的主要逻辑。
"""

import sys

try:
    from sherlock_project.__init__ import import_error_test_var # noqa: F401
except ImportError:
    print("Did you run Sherlock with `python3 sherlock/sherlock.py ...`?")
    print("This is an outdated method. Please see https://sherlockproject.xyz/installation for up to date instructions.")
    sys.exit(1)

import csv
import signal
import pandas as pd
import os
import re
from argparse import ArgumentParser, RawDescriptionHelpFormatter
from json import loads as json_loads
from time import monotonic
from typing import Optional

import requests
from requests_futures.sessions import FuturesSession

from sherlock_project.__init__ import (
    __longname__,
    __shortname__,
    __version__,
    forge_api_latest_release,
)

from sherlock_project.result import QueryStatus
from sherlock_project.result import QueryResult
from sherlock_project.notify import QueryNotify
from sherlock_project.notify import QueryNotifyPrint
from sherlock_project.sites import SitesInformation
from colorama import init
from argparse import ArgumentTypeError


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
            """记录响应耗时的钩子。

            参数：
            resp                   -- 响应对象。
            args                   -- 其他位置参数。
            kwargs                 -- 其他关键字参数。

            返回值：
            无。
            """
            resp.elapsed = monotonic() - start


        # 注册在收到响应时执行的钩子。
        # 将计时钩子放在首位，
        # 避免将后续钩子的执行时间计入响应耗时。
        try:
            if isinstance(hooks["response"], list):
                hooks["response"].insert(0, response_time)
            elif isinstance(hooks["response"], tuple):
                # 将元组转换为列表，并在首位插入计时钩子。
                hooks["response"] = list(hooks["response"])
                hooks["response"].insert(0, response_time)
            else:
                # 原配置为单个钩子函数，
                # 将其转换为列表。
                hooks["response"] = [response_time, hooks["response"]]
        except KeyError:
            # 尚未定义响应钩子，直接注册计时钩子。
            hooks["response"] = [response_time]

        return super(SherlockFuturesSession, self).request(
            method, url, hooks=hooks, *args, **kwargs
        )


def get_response(request_future, error_type, social_network):
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


def interpolate_string(input_object, username):
    if isinstance(input_object, str):
        return input_object.replace("{}", username)
    elif isinstance(input_object, dict):
        return {k: interpolate_string(v, username) for k, v in input_object.items()}
    elif isinstance(input_object, list):
        return [interpolate_string(i, username) for i in input_object]
    return input_object


def check_for_parameter(username):
    """检查用户名是否包含 {?} 占位符，以判断是否需要生成多个用户名。"""
    return "{?}" in username


checksymbols = ["_", "-", "."]


def multiple_usernames(username):
    """用不同符号替换占位符，并返回生成的用户名列表。"""
    allUsernames = []
    for i in checksymbols:
        allUsernames.append(username.replace("{?}", i))
    return allUsernames


def sherlock(
    username: str,
    site_data: dict[str, dict[str, str]],
    query_notify: QueryNotify,
    dump_response: bool = False,
    proxy: Optional[str] = None,
    timeout: int = 60,
) -> dict[str, dict[str, str | QueryResult]]:
    """执行 Sherlock 查询，检查用户名是否存在于各社交网站。

    参数：
    username               -- 待查询的用户名字符串。
    site_data              -- 包含所有待查询站点信息的字典。
    query_notify           -- QueryNotify 或其子类对象，用于通知查询结果。
    dump_response          -- 是否打印响应内容以便调试，默认为 False。
    proxy                  -- 代理 URL 字符串，默认为 None。
    timeout                -- 请求超时时间，单位为秒，默认为 60。

    返回值：
    以站点名称为键的结果字典，每个值也是字典，包含以下字段：
        url_main:      站点首页 URL。
        url_user:      用户的个人主页 URL（若账号存在）。
        status:        表示账号存在性检测结果的 QueryResult 对象。
        http_status:   本次请求的 HTTP 状态码；无法获取时为占位字符串。
        response_text: 响应正文编码后的字节数据；无法获取时为空字符串。
    """

    # 通知调用方开始查询。
    query_notify.start(username)

    # 创建基础 HTTP 会话。
    underlying_session = requests.session()

    # 将工作线程数限制为最多 20 个。
    # 该上限通常已足够处理并发请求。
    if len(site_data) >= 20:
        max_workers = 20
    else:
        max_workers = len(site_data)

    # 为所有请求创建多线程会话。
    session = SherlockFuturesSession(
        max_workers=max_workers, session=underlying_session
    )

    # 保存所有站点的分析结果。
    results_total = {}

    # 先为所有请求创建 Future，使请求可以并发执行。
    for social_network, net_info in site_data.items():
        # 保存当前站点的分析结果。
        results_site = {"url_main": net_info.get("urlMain")}

        # 记录站点首页 URL。

        # 设置 User-Agent，因为部分站点识别出自动化请求后
        # 不会返回正常页面内容。
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:129.0) Gecko/20100101 Firefox/129.0",
        }

        if "headers" in net_info:
            # 覆盖或补充当前站点要求的请求头。
            headers.update(net_info["headers"])

        # 用户在站点上的个人主页 URL（若账号存在）。
        url = interpolate_string(net_info["url"], username.replace(' ', '%20'))

        # 用户名不符合站点规则时，不发送请求。
        regex_check = net_info.get("regexCheck")
        if regex_check and re.search(regex_check, username) is None:
            # 站点不接受此用户名，无需发送请求进行检测。
            results_site["status"] = QueryResult(
                username, social_network, url, QueryStatus.ILLEGAL
            )
            results_site["url_user"] = ""
            results_site["http_status"] = ""
            results_site["response_text"] = ""
            query_notify.update(results_site["status"])
        else:
            # 用户在站点上的个人主页 URL（若账号存在）。
            results_site["url_user"] = url
            url_probe = net_info.get("urlProbe")
            request_method = net_info.get("request_method")
            request_payload = net_info.get("request_payload")
            request = None

            if request_method is not None:
                if request_method == "GET":
                    request = session.get
                elif request_method == "HEAD":
                    request = session.head
                elif request_method == "POST":
                    request = session.post
                elif request_method == "PUT":
                    request = session.put
                else:
                    raise RuntimeError(f"Unsupported request_method for {url}")

            if request_payload is not None:
                request_payload = interpolate_string(request_payload, username)

            if url_probe is None:
                # 未配置专用探测地址，使用用户可访问的个人主页 URL。
                url_probe = url
            else:
                # 站点配置了专用于检测账号是否存在的 URL，
                # 该地址与常规个人主页地址不同。
                url_probe = interpolate_string(url_probe, username)

            if request is None:
                if net_info["errorType"] == "status_code":
                    # 按状态码检测时，通常无需获取完整响应正文。
                    # 只需发送 HEAD 请求，
                    # 即可根据响应状态码进行判断。
                    request = session.head
                else:
                    # 其他检测方式可能需要 GET 响应正文，
                    # 或者站点只有在请求完整页面时
                    # 才会正确响应。
                    request = session.get

            if net_info["errorType"] == "response_url":
                # 账号不存在时，站点会重定向到其他 URL。
                # 禁止自动重定向，
                # 以便读取原始请求的 HTTP 状态码。
                allow_redirects = False
            else:
                # 允许站点重定向。
                # 使用重定向结束后的最终响应进行判断。
                allow_redirects = True

            # Future 在工作线程中执行请求，不阻塞主线程。
            if proxy is not None:
                proxies = {"http": proxy, "https": proxy}
                future = request(
                    url=url_probe,
                    headers=headers,
                    proxies=proxies,
                    allow_redirects=allow_redirects,
                    timeout=timeout,
                    json=request_payload,
                )
            else:
                future = request(
                    url=url_probe,
                    headers=headers,
                    allow_redirects=allow_redirects,
                    timeout=timeout,
                    json=request_payload,
                )

            # 保存 Future，供后续读取请求结果。
            net_info["request_future"] = future

        # 将当前站点的结果加入汇总字典。
        results_total[social_network] = results_site

    # 遍历各站点并收集请求结果。
    for social_network, net_info in site_data.items():
        # 取回当前站点已记录的结果。
        results_site = results_total.get(social_network)

        # 取回该站点的其他信息。
        url = results_site.get("url_user")
        status = results_site.get("status")
        if status is not None:
            # 已根据用户名格式规则确定结果，无需等待请求。
            continue

        # 获取站点配置的错误检测方式。
        error_type = net_info["errorType"]
        if isinstance(error_type, str):
            error_type: list[str] = [error_type]

        # 取回 Future，并等待请求完成。
        future = net_info["request_future"]
        r, error_text, exception_text = get_response(
            request_future=future, error_type=error_type, social_network=social_network
        )

        # 获取本次请求的响应耗时。
        try:
            response_time = r.elapsed
        except AttributeError:
            response_time = None

        # 尝试读取请求的响应信息。
        try:
            http_status = r.status_code
        except Exception:
            http_status = "?"
        try:
            response_text = r.text.encode(r.encoding or "UTF-8")
        except Exception:
            response_text = ""

        query_status = QueryStatus.UNKNOWN
        error_context = None

        # Web 应用防火墙（WAF）的规则会持续更新，可能拦截 Sherlock，
        # 从而导致误报或漏报。在此添加具有明确特征的响应指纹，
        # 用于识别并过滤被 WAF 拦截的结果。
        # 指纹应尽量精确，并在每条指纹末尾注明
        # 对应的防护服务及采集日期。
        WAFHitMsgs = [
            r'.loading-spinner{visibility:hidden}body.no-js .challenge-running{display:none}body.dark{background-color:#222;color:#d9d9d9}body.dark a{color:#fff}body.dark a:hover{color:#ee730a;text-decoration:underline}body.dark .lds-ring div{border-color:#999 transparent transparent}body.dark .font-red{color:#b20f03}body.dark', # 2024-05-13 Cloudflare
            r'<span id="challenge-error-text">', # 2024-11-11 Cloudflare 错误页面
            r'AwsWafIntegration.forceRefreshToken', # 2024-11-11 Cloudfront (AWS)
            r'{return l.onPageView}}),Object.defineProperty(r,"perimeterxIdentifiers",{enumerable:' # 2024-04-09 PerimeterX / Human Security
        ]

        if error_text is not None:
            error_context = error_text

        elif any(hitMsg in r.text for hitMsg in WAFHitMsgs):
            query_status = QueryStatus.WAF

        else:
            if any(errtype not in ["message", "status_code", "response_url"] for errtype in error_type):
                error_context = f"Unknown error type '{error_type}' for {social_network}"
                query_status = QueryStatus.UNKNOWN
            else:
                if "message" in error_type:
                    # error_flag 为 True 表示 HTML 中未发现错误提示。
                    # error_flag 为 False 表示 HTML 中发现了错误提示。
                    error_flag = True
                    errors = net_info.get("errorMsg")
                    # errors 保存用于判断账号不存在的错误提示，
                    # 可以是字符串或列表。
                    # 使用 isinstance 判断类型：
                    # 字符串按单条提示处理，
                    # 列表则逐项检查。
                    if isinstance(errors, str):
                        # 检查 HTML 中是否包含错误提示；
                        # 若存在，则将标志设为 False。
                        if errors in r.text:
                            error_flag = False
                    else:
                        # 对列表中的错误提示逐项检查。
                        for error in errors:
                            if error in r.text:
                                error_flag = False
                                break
                    if error_flag:
                        query_status = QueryStatus.CLAIMED
                    else:
                        query_status = QueryStatus.AVAILABLE

                if "status_code" in error_type and query_status is not QueryStatus.AVAILABLE:
                    error_codes = net_info.get("errorCode")
                    query_status = QueryStatus.CLAIMED

                    # 统一为列表，兼容站点清单中的单个错误码和错误码列表。
                    if isinstance(error_codes, int):
                        error_codes = [error_codes]

                    if error_codes is not None and r.status_code in error_codes:
                        query_status = QueryStatus.AVAILABLE
                    elif r.status_code >= 300 or r.status_code < 200:
                        query_status = QueryStatus.AVAILABLE

                if "response_url" in error_type and query_status is not QueryStatus.AVAILABLE:
                    # 单独使用 response_url 检测时，前面已禁止自动重定向。
                    # 此时响应 URL 与请求 URL 一致，无需比较。
                    # 根据响应状态码判断请求是否成功：
                    # 404 等错误状态和重定向状态
                    # 均视为账号不存在。
                    if 200 <= r.status_code < 300:
                        query_status = QueryStatus.CLAIMED
                    else:
                        query_status = QueryStatus.AVAILABLE

        if dump_response:
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
            try:
                print(f"RESPONSE CODE : {r.status_code}")
            except Exception:
                pass
            try:
                print(f"ERROR TEXT    : {net_info['errorMsg']}")
            except KeyError:
                pass
            print(">>>>> BEGIN RESPONSE TEXT")
            try:
                print(r.text)
            except Exception:
                pass
            print("<<<<< END RESPONSE TEXT")
            print("VERDICT       : " + str(query_status))
            print("+++++++++++++++++++++")

        # 将查询结果通知调用方。
        result: QueryResult = QueryResult(
            username=username,
            site_name=social_network,
            site_url_user=url,
            status=query_status,
            query_time=response_time,
            context=error_context,
        )
        query_notify.update(result)

        # 保存请求的查询状态。
        results_site["status"] = result

        # 保存请求的响应结果。
        results_site["http_status"] = http_status
        results_site["response_text"] = response_text

        # 将当前站点的结果加入汇总字典。
        results_total[social_network] = results_site

    return results_total


def timeout_check(value):
    """检查超时参数是否有效。

    参数：
    value                  -- 请求超时时间，单位为秒。

    返回值：
    表示超时时间（秒）的浮点数。

    注意：无法转换为浮点数或不大于零时抛出异常。
    """

    float_value = float(value)

    if float_value <= 0:
        raise ArgumentTypeError(
            f"Invalid timeout value: {value}. Timeout must be a positive number."
        )

    return float_value


def handler(signal_received, frame):
    """正常退出程序，避免输出异常堆栈。

    参考来源：https://www.devdungeon.com/content/python-catch-sigint-ctrl-c
    """
    sys.exit(0)


def main():
    parser = ArgumentParser(
        formatter_class=RawDescriptionHelpFormatter,
        description=f"{__longname__} (Version {__version__})",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"{__shortname__} v{__version__}",
        help="Display version information and dependencies.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        "-d",
        "--debug",
        action="store_true",
        dest="verbose",
        default=False,
        help="Display extra debugging information and metrics.",
    )
    parser.add_argument(
        "--folderoutput",
        "-fo",
        dest="folderoutput",
        help="If using multiple usernames, the output of the results will be saved to this folder.",
    )
    parser.add_argument(
        "--output",
        "-o",
        dest="output",
        help="If using single username, the output of the result will be saved to this file.",
    )
    parser.add_argument(
        "--csv",
        action="store_true",
        dest="csv",
        default=False,
        help="Create Comma-Separated Values (CSV) File.",
    )
    parser.add_argument(
        "--xlsx",
        action="store_true",
        dest="xlsx",
        default=False,
        help="Create the standard file for the modern Microsoft Excel spreadsheet (xlsx).",
    )
    parser.add_argument(
        "--site",
        action="append",
        metavar="SITE_NAME",
        dest="site_list",
        default=[],
        help="Limit analysis to just the listed sites. Add multiple options to specify more than one site.",
    )
    parser.add_argument(
        "--proxy",
        "-p",
        metavar="PROXY_URL",
        action="store",
        dest="proxy",
        default=None,
        help="Make requests over a proxy. e.g. socks5://127.0.0.1:1080",
    )
    parser.add_argument(
        "--dump-response",
        action="store_true",
        dest="dump_response",
        default=False,
        help="Dump the HTTP response to stdout for targeted debugging.",
    )
    parser.add_argument(
        "--json",
        "-j",
        metavar="JSON_FILE",
        dest="json_file",
        default=None,
        help="Load data from a JSON file or an online, valid, JSON file. Upstream PR numbers also accepted.",
    )
    parser.add_argument(
        "--timeout",
        action="store",
        metavar="TIMEOUT",
        dest="timeout",
        type=timeout_check,
        default=60,
        help="Time (in seconds) to wait for response to requests (Default: 60)",
    )
    parser.add_argument(
        "--print-all",
        action="store_true",
        dest="print_all",
        default=False,
        help="Output sites where the username was not found.",
    )
    parser.add_argument(
        "--print-found",
        action="store_true",
        dest="print_found",
        default=True,
        help="Output sites where the username was found (also if exported as file).",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        dest="no_color",
        default=False,
        help="Don't color terminal output",
    )
    parser.add_argument(
        "username",
        nargs="+",
        metavar="USERNAMES",
        action="store",
        help="One or more usernames to check with social networks. Check similar usernames using {?} (replace to '_', '-', '.').",
    )
    parser.add_argument(
        "--browse",
        "-b",
        action="store_true",
        dest="browse",
        default=False,
        help="Browse to all results on default browser.",
    )

    parser.add_argument(
        "--local",
        "-l",
        action="store_true",
        default=False,
        help="Force the use of the local data.json file.",
    )

    parser.add_argument(
        "--nsfw",
        action="store_true",
        default=False,
        help="Include checking of NSFW sites from default list.",
    )

    parser.add_argument(
        "--txt",
        action="store_true",
        dest="output_txt",
        default=False,
        help="Enable creation of a txt file",
    )

    parser.add_argument(
        "--ignore-exclusions",
        action="store_true",
        dest="ignore_exclusions",
        default=False,
        help="Ignore upstream exclusions (may return more false positives)",
    )

    args = parser.parse_args()

    # 用户按下 Ctrl+C 时正常退出，避免输出异常堆栈。
    signal.signal(signal.SIGINT, handler)

    # 检查 Sherlock 是否有新版本，并在发现更新时提示用户。
    try:
        latest_release_raw = requests.get(forge_api_latest_release, timeout=10).text
        latest_release_json = json_loads(latest_release_raw)
        latest_remote_tag = latest_release_json["tag_name"]

        if latest_remote_tag[1:] != __version__:
            print(
                f"Update available! {__version__} --> {latest_remote_tag[1:]}"
                f"\n{latest_release_json['html_url']}"
            )

    except Exception as error:
        print(f"A problem occurred while checking for an update: {error}")

    # 输出运行提示。
    if args.proxy is not None:
        print("Using the proxy: " + args.proxy)

    if args.no_color:
        # 禁用彩色输出。
        init(strip=True, convert=False)
    else:
        # 启用彩色输出。
        init(autoreset=True)

    # 检查是否同时指定了两种互斥的输出路径选项。
    if args.output is not None and args.folderoutput is not None:
        print("You can only use one of the output methods.")
        sys.exit(1)

    # 检查指定输出文件时是否只输入了一个用户名。
    if args.output is not None and len(args.username) != 1:
        print("You can only use --output with a single username")
        sys.exit(1)

    # 创建包含所有已知站点信息的对象。
    try:
        if args.local:
            sites = SitesInformation(
                os.path.join(os.path.dirname(__file__), "resources/data.json"),
                honor_exclusions=False,
            )
        else:
            json_file_location = args.json_file
            if args.json_file:
                # --json 参数为数字时，将其视为拉取请求编号。
                if args.json_file.isnumeric():
                    pull_number = args.json_file
                    pull_url = f"https://api.github.com/repos/sherlock-project/sherlock/pulls/{pull_number}"
                    pull_request_raw = requests.get(pull_url, timeout=10).text
                    pull_request_json = json_loads(pull_request_raw)

                    # 检查拉取请求是否有效。
                    if "message" in pull_request_json:
                        print(f"ERROR: Pull request #{pull_number} not found.")
                        sys.exit(1)

                    head_commit_sha = pull_request_json["head"]["sha"]
                    json_file_location = f"https://raw.githubusercontent.com/sherlock-project/sherlock/{head_commit_sha}/sherlock_project/resources/data.json"

            sites = SitesInformation(
                data_file_path=json_file_location,
                honor_exclusions=not args.ignore_exclusions,
                do_not_exclude=args.site_list,
            )
    except Exception as error:
        print(f"ERROR:  {error}")
        sys.exit(1)

    if not args.nsfw:
        sites.remove_nsfw_sites(do_not_remove=args.site_list)

    # 将 SitesInformation 对象转换为原有的字典格式。
    # 后续代码尚未全部改为直接使用站点对象，
    # 此处用于衔接两种数据结构。
    site_data_all = {site.name: site.information for site in sites}
    if args.site_list == []:
        # 未指定站点子集，查询所有已加载的站点。
        site_data = site_data_all
    else:
        # 用户只要求查询部分站点。
        # 确认这些站点受支持，并构建筛选后的站点字典。
        site_data = {}
        site_missing = []
        for site in args.site_list:
            counter = 0
            for existing_site in site_data_all:
                if site.lower() == existing_site.lower():
                    site_data[existing_site] = site_data_all[existing_site]
                    counter += 1
            if counter == 0:
                # 记录不受支持的站点，供后续错误提示使用。
                site_missing.append(f"'{site}'")

        if site_missing:
            print(f"Error: Desired sites not found: {', '.join(site_missing)}.")

        if not site_data:
            sys.exit(1)

    # 创建查询结果通知对象。
    query_notify = QueryNotifyPrint(
        result=None, verbose=args.verbose, print_all=args.print_all, browse=args.browse
    )

    # 对所有指定的用户名执行查询。
    all_usernames = []
    for username in args.username:
        if check_for_parameter(username):
            for name in multiple_usernames(username):
                all_usernames.append(name)
        else:
            all_usernames.append(username)
    for username in all_usernames:
        results = sherlock(
            username,
            site_data,
            query_notify,
            dump_response=args.dump_response,
            proxy=args.proxy,
            timeout=args.timeout,
        )

        if args.output:
            result_file = args.output
        elif args.folderoutput:
            # 将用户名的查询结果保存到指定目录。
            # 目录不存在时先创建。
            os.makedirs(args.folderoutput, exist_ok=True)
            result_file = os.path.join(args.folderoutput, f"{username}.txt")
        else:
            result_file = f"{username}.txt"

        if args.output_txt:
            with open(result_file, "w", encoding="utf-8") as file:
                exists_counter = 0
                for website_name in results:
                    dictionary = results[website_name]
                    if dictionary.get("status").status == QueryStatus.CLAIMED:
                        exists_counter += 1
                        file.write(dictionary["url_user"] + "\n")
                file.write(f"Total Websites Username Detected On : {exists_counter}\n")

        if args.csv:
            result_file = f"{username}.csv"
            if args.folderoutput:
                # 将用户名的查询结果保存到指定目录。
                # 目录不存在时先创建。
                os.makedirs(args.folderoutput, exist_ok=True)
                result_file = os.path.join(args.folderoutput, result_file)

            with open(result_file, "w", newline="", encoding="utf-8") as csv_report:
                writer = csv.writer(csv_report)
                writer.writerow(
                    [
                        "username",
                        "name",
                        "url_main",
                        "url_user",
                        "exists",
                        "http_status",
                        "response_time_s",
                    ]
                )
                for site in results:
                    if (
                        args.print_found
                        and not args.print_all
                        and results[site]["status"].status != QueryStatus.CLAIMED
                    ):
                        continue

                    response_time_s = results[site]["status"].query_time
                    if response_time_s is None:
                        response_time_s = ""
                    writer.writerow(
                        [
                            username,
                            site,
                            results[site]["url_main"],
                            results[site]["url_user"],
                            str(results[site]["status"].status),
                            results[site]["http_status"],
                            response_time_s,
                        ]
                    )
        if args.xlsx:
            usernames = []
            names = []
            url_main = []
            url_user = []
            exists = []
            http_status = []
            response_time_s = []

            for site in results:
                if (
                    args.print_found
                    and not args.print_all
                    and results[site]["status"].status != QueryStatus.CLAIMED
                ):
                    continue

                if response_time_s is None:
                    response_time_s.append("")
                else:
                    response_time_s.append(results[site]["status"].query_time)
                usernames.append(username)
                names.append(site)
                url_main.append(results[site]["url_main"])
                url_user.append(results[site]["url_user"])
                exists.append(str(results[site]["status"].status))
                http_status.append(results[site]["http_status"])

            DataFrame = pd.DataFrame(
                {
                    "username": usernames,
                    "name": names,
                    "url_main": [f'=HYPERLINK(\"{u}\")' for u in url_main],
                    "url_user": [f'=HYPERLINK(\"{u}\")' for u in url_user],
                    "exists": exists,
                    "http_status": http_status,
                    "response_time_s": response_time_s,
                }
            )
            DataFrame.to_excel(f"{username}.xlsx", sheet_name="sheet1", index=False)

        print()
    query_notify.finish()


if __name__ == "__main__":
    main()
