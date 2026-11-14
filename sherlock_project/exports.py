"""传统用户名查询的 TXT、CSV 和 XLSX 报告导出。"""

import csv
from argparse import Namespace
from pathlib import Path

from sherlock_project.result import QueryStatus

_COLUMNS = [
    "username",
    "name",
    "url_main",
    "url_user",
    "exists",
    "http_status",
    "response_time_s",
]


def _result_rows(username, results, args):
    """为表格导出生成统一的列顺序，并应用命中结果过滤。"""
    for site, result in results.items():
        status = result["status"]
        if args.print_found and not args.print_all and status.status != QueryStatus.CLAIMED:
            continue
        yield [
            username,
            site,
            result["url_main"],
            result["url_user"],
            str(status.status),
            result["http_status"],
            status.query_time if status.query_time is not None else "",
        ]


def _write_text(path, results):
    """TXT 仅记录命中网址和总数，不受表格显示选项影响。"""
    with open(path, "w", encoding="utf-8") as report:
        count = 0
        for result in results.values():
            if result["status"].status == QueryStatus.CLAIMED:
                report.write(result["url_user"] + "\n")
                count += 1
        report.write(f"Total Websites Username Detected On : {count}\n")


def _write_csv(path, rows):
    """以 UTF-8 写入表头和筛选后的查询结果。"""
    with path.open("w", newline="", encoding="utf-8") as report:
        writer = csv.writer(report)
        writer.writerow(_COLUMNS)
        writer.writerows(rows)


def _write_xlsx(path, rows):
    """按需加载表格依赖，将网址列转换为 Excel 超链接。"""
    import pandas as pd

    data = []
    for row in rows:
        row[2] = f'=HYPERLINK("{row[2]}")'
        row[3] = f'=HYPERLINK("{row[3]}")'
        data.append(row)
    frame = pd.DataFrame(data, columns=_COLUMNS)
    frame.to_excel(path, sheet_name="sheet1", index=False)


def export_results(username: str, results: dict, args: Namespace) -> None:
    """按命令行选项写入报告，沿用各格式既有的文件名和路径规则。"""
    if args.output:
        # 保留用户路径的末尾分隔符，使目录路径仍按原有方式报错。
        text_path = args.output
    elif args.folderoutput:
        folder = Path(args.folderoutput)
        folder.mkdir(parents=True, exist_ok=True)
        text_path = folder / f"{username}.txt"
    else:
        text_path = Path(f"{username}.txt")

    if args.output_txt:
        _write_text(text_path, results)
    if args.csv:
        csv_path = Path(f"{username}.csv")
        if args.folderoutput:
            folder = Path(args.folderoutput)
            folder.mkdir(parents=True, exist_ok=True)
            csv_path = folder / csv_path
        _write_csv(csv_path, _result_rows(username, results, args))
    if args.xlsx:
        # 兼容现有 XLSX 行为：文件写入当前工作目录。
        _write_xlsx(Path(f"{username}.xlsx"), _result_rows(username, results, args))
