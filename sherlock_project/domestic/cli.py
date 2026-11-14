"""国内平台解析模式，与传统用户名探测使用独立的结果语义。"""

import json
from argparse import ArgumentTypeError
from dataclasses import asdict
from pathlib import Path

from sherlock_project.util.text import escape_terminal_text

from .models import PLATFORMS, Result, normalize_platform
from .transport import Client


def _platform(value: str) -> str:
    try:
        return normalize_platform(value)
    except ValueError as exc:
        raise ArgumentTypeError(str(exc)) from exc


def _limit(value: str) -> int:
    try:
        count = int(value)
    except ValueError as exc:
        raise ArgumentTypeError("候选数量必须是 1 到 20 的整数。") from exc
    if not 1 <= count <= 20:
        raise ArgumentTypeError("候选数量必须是 1 到 20 的整数。")
    return count


def add_arguments(parser):
    """注册公开主页解析和昵称搜索参数。"""
    group = parser.add_argument_group("国内平台公开账号解析")
    modes = group.add_mutually_exclusive_group()
    modes.add_argument(
        "--resolve", action="store_true",
        help="解析国内平台主页、主页分享链接或账号 ID。裸 ID 需指定 --platform。",
    )
    modes.add_argument(
        "--search", action="store_true",
        help="按昵称搜索国内平台候选账号；无法自动查询时说明限制和搜索入口。",
    )
    group.add_argument(
        "--platform", action="append", type=_platform, default=[],
        metavar="PLATFORM",
        help="选择平台，可重复；支持 bilibili、小红书、抖音、快手、QQ、微信及英文名称。",
    )
    group.add_argument(
        "--max-results", type=_limit, default=None, metavar="N",
        help="昵称搜索时每个平台最多输出多少候选（1–20，默认 5）。",
    )
    group.add_argument(
        "--result-json", metavar="FILE",
        help="将国内平台解析结果写入 JSON 文件；用 - 输出纯 JSON。",
    )


def _display(result: Result):
    """显示所有状态，避免未验证结果被默认为账号命中。"""
    def emit(text):
        print(escape_terminal_text(text))

    name = PLATFORMS.get(result.platform, result.platform or "未识别平台")
    emit(f"[{result.status.value}] {name} · {result.input}")
    emit(f"  {result.message}")
    for profile in result.profiles:
        nickname = f" · {profile.nickname}" if profile.nickname else ""
        emit(f"  {profile.identifier_kind}: {profile.identifier}{nickname}")
        if profile.url:
            emit(f"  {profile.url}")
    if result.search_url:
        emit(f"  搜索入口：{result.search_url}")


def run_if_requested(args, parser) -> bool:
    """处理独立解析模式；返回 False 时继续原有用户名查询。"""
    enabled = args.resolve or args.search
    if not enabled:
        if args.platform or args.result_json is not None or args.max_results is not None:
            parser.error("--platform、--result-json、--max-results 需配合 --resolve 或 --search。")
        return False
    if args.max_results is not None and not args.search:
        parser.error("--max-results 仅用于 --search。")

    # 避免接受原有模式的参数却静默忽略其含义。
    incompatible = {
        "--site": args.site_list, "--local": args.local, "--json": args.json_file is not None,
        "--txt": args.output_txt, "--csv": args.csv, "--xlsx": args.xlsx,
        "--output": args.output is not None, "--folderoutput": args.folderoutput is not None,
        "--browse": args.browse, "--dump-response": args.dump_response,
        "--nsfw": args.nsfw, "--ignore-exclusions": args.ignore_exclusions,
    }
    conflicts = [flag for flag, active in incompatible.items() if active]
    if conflicts:
        parser.error(f"国内平台模式不使用 {', '.join(conflicts)}；导出请用 --result-json。")

    from .resolve import resolve
    from .search import search

    selected = list(dict.fromkeys(args.platform))
    platforms = selected or (list(PLATFORMS) if args.search else [None])
    results = []
    with Client(timeout=args.timeout, proxy=args.proxy) as client:
        for value in args.username:
            for platform in platforms:
                if args.search:
                    result = search(value, platform, client, limit=args.max_results or 5)
                else:
                    result = resolve(value, platform, client)
                results.append(result)

    report = {"mode": "search" if args.search else "resolve", "results": [asdict(r) for r in results]}
    if args.result_json == "-":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for result in results:
            _display(result)
        if args.result_json is not None:
            try:
                Path(args.result_json).write_text(
                    json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )
            except OSError as exc:
                parser.error(f"无法写入结果文件：{exc}")
    return True
