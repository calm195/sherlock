"""验证新 CLI 路由、结果导出和原有选项之间的边界。"""

import json
from unittest.mock import Mock

import pytest

from sherlock_project import sherlock
from sherlock_project.domestic.models import PLATFORMS, Profile, Result, Status


@pytest.fixture
def run_cli(monkeypatch):
    # 解析模式不应运行版本检查或下载远程站点清单。
    monkeypatch.setattr(sherlock.requests, "get", Mock(side_effect=AssertionError("unexpected network")))

    def run(*args):
        monkeypatch.setattr("sys.argv", ["sherlock", *args])
        sherlock.main()

    return run


def test_search_all_platforms_outputs_json_without_update_check(run_cli, capsys, monkeypatch):
    from sherlock_project.domestic import search

    calls = []

    def fake_search(query, platform, client, limit=5):
        calls.append((query, platform, limit))
        return Result(platform, query, Status.UNSUPPORTED, "请在客户端搜索。")

    monkeypatch.setattr(search, "search", fake_search)
    run_cli("张三", "--search", "--max-results", "2", "--result-json", "-")
    report = json.loads(capsys.readouterr().out)
    assert report["mode"] == "search"
    assert [r["platform"] for r in report["results"]] == list(PLATFORMS)
    assert calls == [("张三", platform, 2) for platform in PLATFORMS]


def test_resolve_multiple_inputs_and_export(run_cli, tmp_path, capsys, monkeypatch):
    from sherlock_project.domestic import resolve

    def fake_resolve(value, platform, client):
        return Result(platform, value, Status.RESOLVED, "仅解析到 QQ 号，尚未验证存在。", [
            Profile(platform, value, f"https://user.qzone.qq.com/{value}", identifier_kind="qq"),
        ])

    monkeypatch.setattr(resolve, "resolve", fake_resolve)
    target = tmp_path / "账号.json"
    run_cli("10000", "10001", "--resolve", "--platform", "QQ", "--platform", "qq", "--result-json", str(target))
    report = json.loads(target.read_text())
    assert [r["profiles"][0]["identifier"] for r in report["results"]] == ["10000", "10001"]
    assert report["results"][0]["status"] == "RESOLVED"
    assert "尚未验证" in capsys.readouterr().out


def test_resolve_automatic_platform(run_cli, monkeypatch):
    from sherlock_project.domestic import resolve

    resolver = Mock(return_value=Result("bilibili", "bilibili:2", Status.RESOLVED, "已解析"))
    monkeypatch.setattr(resolve, "resolve", resolver)
    run_cli("bilibili:2", "--resolve")
    assert resolver.call_args.args[:2] == ("bilibili:2", None)


def test_remote_nickname_cannot_control_terminal(run_cli, monkeypatch, capsys):
    from sherlock_project.domestic import search

    monkeypatch.setattr(search, "search", Mock(return_value=Result(
        "bilibili", "昵称", Status.FOUND, "候选", [
            Profile("bilibili", "2", "https://space.bilibili.com/2", nickname="假名\x1b[2J\n伪造状态"),
        ],
    )))
    run_cli("昵称", "--search", "--platform", "bilibili")
    output = capsys.readouterr().out
    assert "\x1b" not in output
    assert "\\x1b[2J\\n伪造状态" in output


@pytest.mark.parametrize("options", [
    ["--platform", "qq"], ["--result-json", "-"], ["--max-results", "5"],
    ["--resolve", "--search"], ["--resolve", "--max-results", "2"],
    ["--search", "--platform", "invalid"], ["--search", "--max-results", "0"],
    ["--search", "--max-results", "21"], ["--search", "--max-results", "many"],
    ["--resolve", "--local"], ["--search", "--site", "GitHub"],
    ["--search", "--json", "manifest.json"], ["--resolve", "--csv"],
    ["--resolve", "--txt"], ["--resolve", "--browse"],
    ["--resolve", "--timeout", "nan"], ["--search", "--timeout", "inf"],
    ["--search", "--json", ""],
])
def test_rejects_conflicting_arguments(run_cli, options):
    with pytest.raises(SystemExit) as error:
        run_cli("test", *options)
    assert error.value.code == 2
