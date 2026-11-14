"""用本地清单和替代响应验证主流程拆分后的命令行行为。"""

import csv
import json
from concurrent.futures import Future
from unittest.mock import Mock

import pytest
import requests

from sherlock_project import __version__, cli, runner, sherlock
from sherlock_project.result import QueryResult, QueryStatus


def response(payload):
    result = requests.Response()
    result.status_code = 200
    result._content = json.dumps(payload).encode()
    return result


@pytest.fixture
def manifest(tmp_path):
    data = {
        name: {
            "urlMain": f"https://{name.lower()}.example.com",
            "url": f"https://{name.lower()}.example.com/{{}}",
            "username_claimed": "known",
            "errorType": "status_code",
            "isNSFW": name == "Adult",
        }
        for name in ("GitHub", "Gitee", "Adult")
    }
    path = tmp_path / "sites.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.fixture
def run_cli(monkeypatch):
    # 所有联网请求均由替代响应处理，不访问版本接口或真实社交平台。
    remote = Mock(return_value=response({"tag_name": f"v{__version__}"}))
    monkeypatch.setattr(runner.requests, "get", remote)
    monkeypatch.setattr(runner, "init", Mock())
    monkeypatch.setattr(runner, "QueryNotifyPrint", Mock())
    monkeypatch.setattr(runner, "sherlock", Mock(return_value={}))

    def run(*args):
        monkeypatch.setattr("sys.argv", ["sherlock", *args])
        sherlock.main()

    return run, remote


def test_main_preserves_selection_expansion_options_and_exports(run_cli, manifest, tmp_path, capsys):
    run, remote = run_cli
    folder = tmp_path / "reports"

    def query(username, sites, notify, **options):
        assert list(sites) == ["GitHub", "Adult"]
        assert notify is runner.QueryNotifyPrint.return_value
        assert options == {"dump_response": True, "proxy": "socks5://localhost:1080", "timeout": 7.5}
        return {
            "GitHub": {
                "url_main": "https://github.example.com",
                "url_user": f"https://github.example.com/{username}",
                "status": QueryResult(username, "GitHub", "", QueryStatus.CLAIMED, 0.5),
                "http_status": 200,
            },
        }

    runner.sherlock.side_effect = query
    run(
        "test{?}user", "plain", "--json", str(manifest), "--ignore-exclusions",
        "--site", "github", "--site", "Adult", "--site", "Missing",
        "--txt", "--csv", "--folderoutput", str(folder), "--no-color",
        "--proxy", "socks5://localhost:1080", "--timeout", "7.5", "--dump-response",
        "--verbose", "--print-all", "--browse",
    )
    usernames = ["test_user", "test-user", "test.user", "plain"]
    assert [call.args[0] for call in runner.sherlock.call_args_list] == usernames
    for username in usernames:
        assert (folder / f"{username}.txt").read_text() == (
            f"https://github.example.com/{username}\nTotal Websites Username Detected On : 1\n"
        )
        with (folder / f"{username}.csv").open(newline="") as report:
            assert list(csv.reader(report))[1][0] == username
    runner.QueryNotifyPrint.assert_called_once_with(result=None, verbose=True, print_all=True, browse=True)
    runner.QueryNotifyPrint.return_value.finish.assert_called_once_with()
    runner.init.assert_called_once_with(strip=True, convert=False)
    remote.assert_called_once()
    assert "Desired sites not found: 'Missing'" in capsys.readouterr().out


def test_local_manifest_remains_relative_to_package(run_cli, tmp_path, monkeypatch):
    run, remote = run_cli
    monkeypatch.chdir(tmp_path)
    run("known", "--local", "--site", "GitHub")
    sites = runner.sherlock.call_args.args[1]
    assert list(sites) == ["GitHub"]
    assert sites["GitHub"]["url"].endswith("github.com/{}")
    remote.assert_called_once()


def test_cli_query_and_export_work_together(run_cli, manifest, tmp_path, monkeypatch):
    """使用真实查询与导出模块，仅替换网络传输和终端通知。"""
    from sherlock_project import query

    run, _ = run_cli
    session = Mock()
    futures = []
    for code in (200, 404):
        reply = response({})
        reply.status_code = code
        reply.elapsed = 0.25
        future = Future()
        future.set_result(reply)
        futures.append(future)
    session.head.side_effect = futures
    monkeypatch.setattr(query, "SherlockFuturesSession", Mock(return_value=session))
    monkeypatch.setattr(runner, "sherlock", query.sherlock)
    run("known", "--json", str(manifest), "--ignore-exclusions", "--txt", "--folderoutput", str(tmp_path))
    assert (tmp_path / "known.txt").read_text() == (
        "https://github.example.com/known\nTotal Websites Username Detected On : 1\n"
    )
    assert session.head.call_count == 2
    assert runner.QueryNotifyPrint.return_value.update.call_count == 2


@pytest.mark.parametrize("include_nsfw", [False, True])
def test_nsfw_default_filter_and_explicit_flag(run_cli, manifest, include_nsfw):
    run, _ = run_cli
    options = ["--nsfw"] if include_nsfw else []
    run("known", "--json", str(manifest), "--ignore-exclusions", *options)
    sites = runner.sherlock.call_args.args[1]
    assert ("Adult" in sites) is include_nsfw


@pytest.mark.parametrize(("inputs", "options", "message"), [
    (["one"], ["--output", "one.txt", "--folderoutput", "reports"], "one of the output methods"),
    (["one", "two"], ["--output", "one.txt"], "--output with a single username"),
    (["one"], ["--site", "Missing"], "Desired sites not found"),
])
def test_invalid_traditional_options_keep_exit_status(run_cli, manifest, capsys, inputs, options, message):
    run, _ = run_cli
    with pytest.raises(SystemExit) as error:
        run(*inputs, "--json", str(manifest), "--ignore-exclusions", *options)
    assert error.value.code == 1
    runner.sherlock.assert_not_called()
    assert message in capsys.readouterr().out


def test_version_check_failure_does_not_stop_query(run_cli, manifest, capsys):
    run, remote = run_cli
    remote.side_effect = requests.Timeout("timeout")
    run("known", "--json", str(manifest), "--ignore-exclusions")
    runner.sherlock.assert_called_once()
    assert "A problem occurred while checking for an update: timeout" in capsys.readouterr().out


def test_invalid_manifest_keeps_error_exit(run_cli, tmp_path, capsys):
    run, _ = run_cli
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{", encoding="utf-8")
    with pytest.raises(SystemExit) as error:
        run("known", "--json", str(invalid), "--ignore-exclusions")
    assert error.value.code == 1
    runner.sherlock.assert_not_called()
    assert "ERROR:" in capsys.readouterr().out


def test_pull_request_manifest_and_exclusion_options(run_cli, manifest):
    run, remote = run_cli
    remote.side_effect = [
        response({"tag_name": f"v{__version__}"}),
        response({"head": {"sha": "example-commit"}}),
        response(json.loads(manifest.read_text())),
    ]
    run("known", "--json", "123", "--ignore-exclusions", "--site", "Gitee")
    assert remote.call_args_list[1].args[0].endswith("/pulls/123")
    assert remote.call_args_list[2].kwargs["url"] == (
        "https://raw.githubusercontent.com/sherlock-project/sherlock/"
        "example-commit/sherlock_project/resources/data.json"
    )
    assert list(runner.sherlock.call_args.args[1]) == ["Gitee"]


def test_missing_pull_request_does_not_start_query(run_cli, capsys):
    run, remote = run_cli
    remote.side_effect = [response({"tag_name": f"v{__version__}"}), response({"message": "Not Found"})]
    with pytest.raises(SystemExit) as error:
        run("known", "--json", "123")
    assert error.value.code == 1
    assert "Pull request #123 not found" in capsys.readouterr().out
    runner.sherlock.assert_not_called()


def test_compatibility_entry_uses_cli_and_query_modules():
    from sherlock_project.query import sherlock as query

    assert sherlock.main is cli.main
    assert sherlock.sherlock is query
