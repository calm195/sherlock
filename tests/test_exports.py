"""验证报告导出拆分后的路径、过滤、列格式和空结果行为。"""

import csv
from argparse import Namespace

import pytest
from openpyxl import load_workbook

from sherlock_project.exports import export_results
from sherlock_project.result import QueryResult, QueryStatus

_HEADERS = [
    "username", "name", "url_main", "url_user", "exists", "http_status", "response_time_s",
]


def options(**overrides):
    values = {
        "output": None, "folderoutput": None, "output_txt": False,
        "csv": False, "xlsx": False, "print_found": True, "print_all": False,
    }
    values.update(overrides)
    return Namespace(**values)


@pytest.fixture
def results():
    statuses = [
        ("命中,站点", QueryStatus.CLAIMED, 0.25, 200),
        ("未找到", QueryStatus.AVAILABLE, 0.0, 404),
        ("失败", QueryStatus.UNKNOWN, None, "?"),
    ]
    return {
        name: {
            "url_main": "https://example.com",
            "url_user": f"https://example.com/{index}",
            "status": QueryResult("张三", name, f"https://example.com/{index}", status, query_time),
            "http_status": http_status,
        }
        for index, (name, status, query_time, http_status) in enumerate(statuses)
    }


def test_text_uses_custom_path_and_only_claimed_urls(tmp_path, results):
    target = tmp_path / "指定.txt"
    export_results("张三", results, options(output=str(target), output_txt=True, print_all=True))
    assert target.read_text(encoding="utf-8") == (
        "https://example.com/0\nTotal Websites Username Detected On : 1\n"
    )


def test_output_path_alone_does_not_enable_text(tmp_path, results):
    target = tmp_path / "未启用.txt"
    export_results("张三", results, options(output=str(target)))
    assert not target.exists()


def test_custom_output_keeps_trailing_directory_separator(tmp_path, results):
    target = tmp_path / "不存在的目录"
    with pytest.raises(FileNotFoundError):
        export_results("张三", results, options(output=str(target) + "/", output_txt=True))
    assert not target.exists()


@pytest.mark.parametrize(("print_found", "print_all", "expected_rows"), [
    (True, False, 1), (True, True, 3), (False, False, 3),
])
def test_csv_keeps_columns_filter_and_missing_duration(
    tmp_path, results, print_found, print_all, expected_rows,
):
    folder = tmp_path / "报告" / "用户"
    export_results("张三", results, options(
        csv=True, folderoutput=str(folder), print_found=print_found, print_all=print_all,
    ))
    with (folder / "张三.csv").open(encoding="utf-8", newline="") as report:
        rows = list(csv.reader(report))
    assert rows[0] == _HEADERS
    assert len(rows) == expected_rows + 1
    assert rows[1] == [
        "张三", "命中,站点", "https://example.com", "https://example.com/0", "Claimed", "200", "0.25",
    ]
    if expected_rows == 3:
        assert rows[2][4:] == ["Available", "404", "0.0"]
        assert rows[3][4:] == ["Unknown", "?", ""]


@pytest.mark.parametrize("print_all", [False, True])
def test_xlsx_preserves_hyperlinks_filter_and_current_directory(
    tmp_path, monkeypatch, results, print_all,
):
    monkeypatch.chdir(tmp_path)
    folder = tmp_path / "子目录"
    export_results("张三", results, options(xlsx=True, folderoutput=str(folder), print_all=print_all))
    assert not (folder / "张三.xlsx").exists()
    workbook = load_workbook(tmp_path / "张三.xlsx", data_only=False)
    try:
        assert workbook.sheetnames == ["sheet1"]
        rows = list(workbook["sheet1"].values)
        assert list(rows[0]) == _HEADERS
        assert rows[1] == (
            "张三", "命中,站点", '=HYPERLINK("https://example.com")',
            '=HYPERLINK("https://example.com/0")', "Claimed", 200, 0.25,
        )
        assert len(rows) == (4 if print_all else 2)
        if print_all:
            assert rows[2][6] == 0
            assert rows[3][6] is None
    finally:
        workbook.close()


def test_all_formats_preserve_zero_results_and_independent_paths(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    folder = tmp_path / "报告"
    export_results("空结果", {}, options(
        output_txt=True, csv=True, xlsx=True, folderoutput=str(folder),
    ))
    assert (folder / "空结果.txt").read_text() == "Total Websites Username Detected On : 0\n"
    with (folder / "空结果.csv").open(encoding="utf-8", newline="") as report:
        assert list(csv.reader(report)) == [_HEADERS]
    workbook = load_workbook(tmp_path / "空结果.xlsx")
    try:
        assert list(workbook["sheet1"].values) == [tuple(_HEADERS)]
    finally:
        workbook.close()


def test_default_text_and_csv_names_do_not_share_custom_output(tmp_path, monkeypatch, results):
    monkeypatch.chdir(tmp_path)
    export_results("张三", results, options(output_txt=True, csv=True, output="custom.txt"))
    assert (tmp_path / "custom.txt").is_file()
    assert (tmp_path / "张三.csv").is_file()
    assert not (tmp_path / "张三.txt").exists()
