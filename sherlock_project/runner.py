"""传统用户名查询的流程编排：准备站点、执行查询并导出结果。"""

import os
import sys
from json import loads as json_loads

import requests
from colorama import init

from sherlock_project import __version__, forge_api_latest_release
from sherlock_project.exports import export_results
from sherlock_project.notify import QueryNotifyPrint
from sherlock_project.query import sherlock
from sherlock_project.sites import SitesInformation
from sherlock_project.util.username import check_for_parameter, multiple_usernames


def _check_for_update():
    """提示可用的新版本；检查失败时继续查询。"""
    try:
        latest_release_raw = requests.get(forge_api_latest_release, timeout=10).text
        latest_release_json = json_loads(latest_release_raw)
        latest_remote_tag = latest_release_json["tag_name"]

        if latest_remote_tag[1:] != __version__:
            print(
                f"Update available! {__version__} --> {latest_remote_tag[1:]}"
                f"\n{latest_release_json['html_url']}"
            )
    except Exception as error:  # noqa: BLE001
        print(f"A problem occurred while checking for an update: {error}")


def _configure_output(args):
    """设置终端颜色并校验输出路径选项。"""
    if args.proxy is not None:
        print("Using the proxy: " + args.proxy)

    if args.no_color:
        init(strip=True, convert=False)
    else:
        init(autoreset=True)

    if args.output is not None and args.folderoutput is not None:
        print("You can only use one of the output methods.")
        sys.exit(1)
    if args.output is not None and len(args.username) != 1:
        print("You can only use --output with a single username")
        sys.exit(1)


def _manifest_location(value):
    """解析 --json 输入；数字仍表示上游拉取请求编号。"""
    if not value or not value.isnumeric():
        return value

    pull_url = f"https://api.github.com/repos/sherlock-project/sherlock/pulls/{value}"
    pull_request_raw = requests.get(pull_url, timeout=10).text
    pull_request_json = json_loads(pull_request_raw)
    if "message" in pull_request_json:
        print(f"ERROR: Pull request #{value} not found.")
        sys.exit(1)

    head_commit_sha = pull_request_json["head"]["sha"]
    return (
        f"https://raw.githubusercontent.com/sherlock-project/sherlock/{head_commit_sha}"
        "/sherlock_project/resources/data.json"
    )


def _load_sites(args):
    """加载清单、应用排除规则和 NSFW 选项。"""
    try:
        if args.local:
            sites = SitesInformation(
                os.path.join(os.path.dirname(__file__), "resources/data.json"),
                honor_exclusions=False,
            )
        else:
            sites = SitesInformation(
                data_file_path=_manifest_location(args.json_file),
                honor_exclusions=not args.ignore_exclusions,
                do_not_exclude=args.site_list,
            )
    except Exception as error:  # noqa: BLE001
        print(f"ERROR:  {error}")
        sys.exit(1)

    if not args.nsfw:
        sites.remove_nsfw_sites(do_not_remove=args.site_list)
    return sites


def _select_sites(sites, selected):
    """按名称选择站点，保留输入顺序并忽略名称大小写。"""
    site_data_all = {site.name: site.information for site in sites}
    if not selected:
        return site_data_all

    site_data = {}
    site_missing = []
    for site in selected:
        matches = [name for name in site_data_all if site.lower() == name.lower()]
        if matches:
            for name in matches:
                site_data[name] = site_data_all[name]
        else:
            site_missing.append(f"'{site}'")

    if site_missing:
        print(f"Error: Desired sites not found: {', '.join(site_missing)}.")
    if not site_data:
        sys.exit(1)
    return site_data


def _expand_usernames(usernames):
    """按原始输入顺序展开用户名中的 {?} 占位符。"""
    expanded = []
    for username in usernames:
        if check_for_parameter(username):
            expanded.extend(multiple_usernames(username))
        else:
            expanded.append(username)
    return expanded


def run(args):
    """执行传统用户名查询，集中管理每次查询前后的工作。"""
    _check_for_update()
    _configure_output(args)
    site_data = _select_sites(_load_sites(args), args.site_list)
    query_notify = QueryNotifyPrint(
        result=None, verbose=args.verbose, print_all=args.print_all, browse=args.browse
    )

    for username in _expand_usernames(args.username):
        results = sherlock(
            username,
            site_data,
            query_notify,
            dump_response=args.dump_response,
            proxy=args.proxy,
            timeout=args.timeout,
        )
        export_results(username, results, args)
        print()
    query_notify.finish()
